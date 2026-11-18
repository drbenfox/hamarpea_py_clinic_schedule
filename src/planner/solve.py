from dataclasses import dataclass, field
from itertools import combinations

from ortools.sat.python import cp_model

from .checker import implicit_specs
from .models import RuleSpec, Scenario, Session, to_hhmm, to_minutes
from .plan import Plan

FAMILIES = {
    "rooms": "No room is in two sessions at once",
    "people": "No person is in two sessions at once",
    "devices": "No device is in two sessions at once",
    "availability": "People only work on days they are available",
    "max_shifts": "People stay within their max shifts per week",
    "room_needs": "Sessions only use rooms that have the attributes they need",
    "device_rooms": "Devices only run in rooms they are allowed in",
    "staff_pool": "Staff headcount never exceeds the pool for that role",
}


@dataclass
class SVars:
    s: Session
    p: object
    k: int
    count: int
    people: list[str]
    free: list[str]
    d: dict = field(default_factory=dict)
    st: dict = field(default_factory=dict)
    x: dict = field(default_factory=dict)
    prim: list[str] = field(default_factory=list)
    cover: list = field(default_factory=list)
    act: dict = field(default_factory=dict)

    def in_week(self, week: str) -> bool:
        return self.s.weeks in ("weekly", week)


@dataclass
class SolveResult:
    status: str  # solved | infeasible | unknown
    scenario: Scenario | None = None
    free: list[str] = field(default_factory=list)
    objective: int | None = None
    core: list[str] = field(default_factory=list)


class Builder:
    def __init__(self, sc: Scenario) -> None:
        self.sc = sc
        self.plan = Plan(sc)
        self.m = cp_model.CpModel()
        self.lits: dict[str, object] = {}
        self.desc: dict[str, str] = {}
        self.obj: list = []
        cal = sc.calendar
        self.days, self.weeks, self.slot = cal.days, cal.cycle_weeks, cal.slot_minutes
        self.open = to_minutes(cal.open)
        self.N = (to_minutes(cal.close) - self.open) // self.slot
        self.sv: list[SVars] = []
        self._and: dict = {}
        self._occ_cache: dict = {}
        self._busy_cache: dict = {}
        self._pcover: dict = {}

    # ------------------------------------------------------------ helpers
    def lit(self, key: str, text: str):
        v = self.m.NewBoolVar(key)
        self.lits[key], self.desc[key] = v, text
        return v

    def and_(self, a, b):
        key = (a.Index(), b.Index())
        if key not in self._and:
            v = self.m.NewBoolVar("")
            self.m.AddBoolAnd([a, b]).OnlyEnforceIf(v)
            self.m.AddBoolOr([a.Not(), b.Not()]).OnlyEnforceIf(v.Not())
            self._and[key] = v
        return self._and[key]

    def on(self, ct, *lits):
        lits = [l for l in lits if l is not None]
        if lits:
            ct.OnlyEnforceIf(lits)
        return ct

    def pen(self, weight: int):
        v = self.m.NewBoolVar("")
        self.obj.append((weight, v))
        return v

    def limit(self, spec: RuleSpec, g, expr, bound: int) -> None:
        if g is not None:
            self.on(self.m.Add(expr <= bound), g)
        else:
            self.m.Add(expr <= bound + self.pen(spec.weight))

    def active(self, sv: SVars, day: str, i: int):
        if day not in sv.d:
            return None
        if (day, i) not in sv.act:
            sv.act[(day, i)] = self.and_(sv.d[day], sv.cover[i])
        return sv.act[(day, i)]

    def prep_active(self, sv: SVars, day: str, i: int, p: int):
        """Active in slot i, or starting within the next p slots (staff arrive early)."""
        if p == 0:
            return self.active(sv, day, i)
        if day not in sv.d:
            return None
        key = (sv.s.id, i, p)
        if key not in self._pcover:
            c = self.m.NewBoolVar("")
            self.m.Add(c == sum(sv.st[t] for t in range(max(0, i - sv.k + 1), min(i + p, self.N - sv.k) + 1) if t in sv.st))
            self._pcover[key] = c
        return self.and_(sv.d[day], self._pcover[key])

    def occ(self, sv: SVars, r: str, day: str, i: int):
        key = (sv.s.id, r, day, i)
        if key not in self._occ_cache:
            a = self.active(sv, day, i)
            self._occ_cache[key] = None if a is None or r not in sv.x else self.and_(sv.x[r], a)
        return self._occ_cache[key]

    def busy(self, r: str, week: str, day: str, i: int):
        key = (r, week, day, i)
        if key not in self._busy_cache:
            terms = [o for sv in self.sv if sv.in_week(week) and (o := self.occ(sv, r, day, i)) is not None]
            if not terms:
                self._busy_cache[key] = None
            else:
                b = self.m.NewBoolVar("")
                for o in terms:
                    self.m.AddImplication(o, b)
                self._busy_cache[key] = b
        return self._busy_cache[key]

    # ----------------------------------------------------------- sessions
    def add_session(self, s: Session) -> None:
        m, slot = self.m, self.slot
        locked = s.locked
        has_time = bool(s.start and s.end)
        if has_time:
            a = to_minutes(s.start)
            minutes = to_minutes(s.end) - a
        elif s.duration:
            minutes = s.duration
        else:
            raise ValueError(f"{s.id}: start/end are open, so it needs a duration (minutes).")
        if minutes <= 0 or minutes % slot:
            raise ValueError(f"{s.id}: length {minutes} min is not a positive multiple of {slot}.")
        if has_time and (a - self.open) % slot:
            raise ValueError(f"{s.id}: start {s.start} is not on a {slot}-minute slot.")
        k = minutes // slot
        primary = list(s.rooms.primary)
        count = len(primary) if primary else s.rooms.count
        if not count:
            raise ValueError(f"{s.id}: rooms are open, so it needs rooms.count.")
        day_fixed = s.day is not None and locked.get("day", True)
        time_fixed = has_time and locked.get("time", True)
        rooms_fixed = bool(primary) and locked.get("rooms", True)
        people = list(dict.fromkeys(([self.plan.canon(s.lead)] if s.lead else []) + [self.plan.canon(p) for p in s.staff.named]))
        free = [n for n, fixed in (("day", day_fixed), ("time", time_fixed), ("rooms", rooms_fixed)) if not fixed]

        p = self.lit(f"need:{s.id}", f"Session {s.id} must be placed")
        sv = SVars(s, p, k, count, people, free)
        sv.d = {d: m.NewBoolVar("") for d in self.days if not s.allowed_days or d in s.allowed_days}
        m.Add(sum(sv.d.values()) == p)
        lo, hi = (to_minutes(s.window[0]), to_minutes(s.window[1])) if s.window else (0, 24 * 60)
        sv.st = {
            t: m.NewBoolVar("")
            for t in range(0, self.N - k + 1)
            if self.open + t * slot >= lo and self.open + (t + k) * slot <= hi
        }
        m.Add(sum(sv.st.values()) == p)
        for i in range(self.N):
            c = m.NewBoolVar("")
            m.Add(c == sum(sv.st[t] for t in range(max(0, i - k + 1), min(i, self.N - k) + 1) if t in sv.st))
            sv.cover.append(c)

        room_ids = [r.id for r in self.sc.rooms]
        overflow = [r for r in s.rooms.overflow if r in room_ids]
        base = s.allowed_rooms or room_ids
        sv.prim = [r for r in room_ids if (r in base and r not in overflow) or (rooms_fixed and r in primary)]
        for r in sv.prim:
            sv.x[r] = m.NewBoolVar("")
        for r in overflow:
            sv.x[r] = m.NewBoolVar("")
            m.Add(sv.x[r] == p)
        m.Add(sum(sv.x[r] for r in sv.prim) == count * p)

        if day_fixed or time_fixed or rooms_fixed:
            fixed = [n for n, f in (("day", day_fixed), ("time", time_fixed), ("rooms", rooms_fixed)) if f]
            l = self.lit(f"lock:{s.id}", f"Session {s.id} keeps its fixed {'/'.join(fixed)}")
            both = [l, p]
            if day_fixed:
                if s.day in sv.d:
                    m.Add(sv.d[s.day] == 1).OnlyEnforceIf(both)
                else:
                    m.AddBoolOr([l.Not(), p.Not()])
            if time_fixed:
                t0 = (a - self.open) // slot
                if t0 in sv.st:
                    m.Add(sv.st[t0] == 1).OnlyEnforceIf(both)
                else:
                    m.AddBoolOr([l.Not(), p.Not()])
            if rooms_fixed:
                if any(r not in sv.x for r in primary):
                    m.AddBoolOr([l.Not(), p.Not()])
                else:
                    for r in sv.prim:
                        m.Add(sv.x[r] == int(r in primary)).OnlyEnforceIf(both)
        self.sv.append(sv)

    # ------------------------------------------------------ built-in rules
    def exclusive(self, fam, groups: dict[str, list[SVars]]) -> None:
        for members in groups.values():
            if len(members) < 2:
                continue
            for w in self.weeks:
                ws = [sv for sv in members if sv.in_week(w)]
                for day in self.days:
                    for i in range(self.N):
                        terms = [a for sv in ws if (a := self.active(sv, day, i)) is not None]
                        if len(terms) > 1:
                            self.m.Add(sum(terms) <= 1).OnlyEnforceIf(fam)

    def add_builtins(self) -> None:
        m, sc = self.m, self.sc
        fam = {k: self.lit(f"family:{k}", v) for k, v in FAMILIES.items()}

        rooms: dict[str, list[SVars]] = {}
        people: dict[str, list[SVars]] = {}
        devices: dict[str, list[SVars]] = {}
        for sv in self.sv:
            for r in sv.x:
                rooms.setdefault(r, []).append(sv)
            for pid in sv.people:
                people.setdefault(pid, []).append(sv)
            for did in sv.s.devices or []:
                devices.setdefault(did, []).append(sv)
        for w in self.weeks:
            for day in self.days:
                for i in range(self.N):
                    for r, members in rooms.items():
                        terms = [o for sv in members if sv.in_week(w) and (o := self.occ(sv, r, day, i)) is not None]
                        if len(terms) > 1:
                            m.Add(sum(terms) <= 1).OnlyEnforceIf(fam["rooms"])
        self.exclusive(fam["people"], people)
        self.exclusive(fam["devices"], devices)

        for sv in self.sv:
            for pid in sv.people:
                person = self.plan.person(pid)
                if not person:
                    continue
                for day, var in sv.d.items():
                    if (person.unavailable_days and day in person.unavailable_days) or (person.days is not None and day not in person.days):
                        m.Add(var == 0).OnlyEnforceIf(fam["availability"])
            for r in sv.prim:
                room = self.plan.room(r)
                if room and any(a not in room.attributes for a in sv.s.room_needs):
                    m.Add(sv.x[r] == 0).OnlyEnforceIf(fam["room_needs"])
            for did in sv.s.devices or []:
                dev = next((d for d in sc.devices if d.id == did), None)
                if dev:
                    ok = [sv.x[r] for r in sv.prim if r in dev.allowed_rooms]
                    m.Add(sum(ok) >= 1).OnlyEnforceIf([fam["device_rooms"], sv.p])

        for p in sc.people:
            if p.max_shifts_per_week is None or p.id not in people:
                continue
            for w in self.weeks:
                worked = []
                for day in self.days:
                    v = m.NewBoolVar("")
                    for sv in people[p.id]:
                        if sv.in_week(w) and day in sv.d:
                            m.AddImplication(sv.d[day], v)
                    worked.append(v)
                m.Add(sum(worked) <= p.max_shifts_per_week).OnlyEnforceIf(fam["max_shifts"])

        roles = sorted({r for sv in self.sv for r in sv.s.staff.count})
        pools = ", ".join(f"{r}: {sum(1 for p in sc.people if p.role == r)}" for r in roles)
        self.desc["family:staff_pool"] = f"Staff headcount never exceeds the pool ({pools})"
        for role in roles:
            pool = sum(1 for p in sc.people if p.role == role)
            named = {p.id for p in sc.people if p.role == role}
            prep_slots = -(-sc.options.staff_prep_minutes.get(role, 0) // self.slot)
            for w in self.weeks:
                for day in self.days:
                    peak = m.NewIntVar(0, 100, "")
                    for i in range(self.N):
                        terms = []
                        for sv in self.sv:
                            c = sv.s.staff.count.get(role, 0) + len(set(sv.people) & named)
                            a = self.prep_active(sv, day, i, prep_slots) if sv.in_week(w) else None
                            if c and a is not None:
                                terms.append(c * a)
                        if terms:
                            m.Add(sum(terms) <= pool).OnlyEnforceIf(fam["staff_pool"])
                            m.Add(sum(terms) <= peak)
                    self.obj.append((1, peak))

    # --------------------------------------------------------- data rules
    def add_rule(self, spec: RuleSpec) -> None:
        handler = getattr(self, f"rule_{spec.type}", None)
        if handler is None:
            return
        relax = getattr(spec, "relaxed_by", None)
        if spec.strength == "hard" and relax and getattr(self.sc.options, relax, False):
            spec = spec.model_copy(update={"strength": "soft", "weight": getattr(spec, "relaxed_weight", spec.weight)})
        g = self.lit(f"rule:{spec.id}", f"Rule {spec.id} ({spec.type})") if spec.strength == "hard" else None
        handler(spec, g)

    def rule_pin(self, spec, g) -> None:
        who = self.plan.canon(spec.who)
        person = self.plan.person(who)
        pdays = person.days if person and person.days else self.days
        for sv in self.sv:
            if who in sv.people or spec.room not in sv.x:
                continue
            for day in pdays:
                if day in sv.d:
                    self.limit(spec, g, sv.x[spec.room] + sv.d[day], 1)

    def rule_shared_access(self, spec, g) -> None:
        weight = spec.weight
        fridge = self.plan.rooms_with(spec.attribute)
        for sv in self.sv:
            if spec.attribute not in (sv.s.needs_access or []):
                continue
            for w in self.weeks:
                if not sv.in_week(w):
                    continue
                for day in sv.d:
                    slack = None
                    for i in range(self.N):
                        opts, satisfied = [], False
                        for r in fridge:
                            b = self.busy(r, w, day, i)
                            if b is None:
                                satisfied = True
                                break
                            if r in sv.x:
                                opts.append(sv.x[r])
                            opts.append(b.Not())
                        if satisfied:
                            continue
                        lits = [self.active(sv, day, i).Not()] + opts
                        if g is not None:
                            self.on(self.m.AddBoolOr(lits), g)
                        else:
                            slack = self.pen(weight) if slack is None else slack
                            self.m.AddBoolOr(lits + [slack])

    def _constant_rule(self, spec, g, bad) -> None:
        if g is None:
            return
        for sv in self.sv:
            if bad(sv):
                self.m.Add(sv.p == 0).OnlyEnforceIf(g)

    def rule_pairing(self, spec, g) -> None:
        partners: dict[str, set[str]] = {}
        for a, b in spec.pairs:
            partners.setdefault(self.plan.canon(a), set()).add(self.plan.canon(b))
        self._constant_rule(spec, g, lambda sv: any(a in sv.people and not (al & set(sv.people)) for a, al in partners.items()))

    def rule_avoid_pairing(self, spec, g) -> None:
        a, b = (self.plan.canon(p) for p in spec.people)
        self._constant_rule(spec, g, lambda sv: a in sv.people and b in sv.people)

    def rule_prefer_pairing(self, spec, g) -> None:
        a, b = (self.plan.canon(p) for p in spec.people)
        self._constant_rule(spec, g, lambda sv: (a in sv.people) != (b in sv.people))

    def rule_mutex(self, spec, g) -> None:
        if getattr(spec, "sessions", None):
            items = spec.sessions
            match = lambda sv, x: sv.s.id == x
        elif getattr(spec, "people", None):
            items = spec.people
            match = lambda sv, x: self.plan.canon(x) in sv.people
        else:
            items = getattr(spec, "tags", [])
            match = lambda sv, x: x in sv.s.focus
        for x, y in combinations(items, 2):
            for a in (sv for sv in self.sv if match(sv, x)):
                for b in (sv for sv in self.sv if match(sv, y) and sv is not a):
                    for w in self.weeks:
                        if not (a.in_week(w) and b.in_week(w)):
                            continue
                        for day in a.d:
                            for i in range(self.N):
                                ta, tb = self.active(a, day, i), self.active(b, day, i)
                                if ta is not None and tb is not None:
                                    self.limit(spec, g, ta + tb, 1)

    def rule_prefer_room(self, spec, g) -> None:
        wanted = getattr(spec, "rooms", None)
        avoid = getattr(spec, "avoid", None) or []
        only = getattr(spec, "session", None)
        for sv in self.sv:
            if only and sv.s.id != only:
                continue
            if wanted:
                hit = [sv.x[r] for r in sv.prim if r in wanted]
                if g is not None:
                    self.m.Add(sum(hit) >= 1).OnlyEnforceIf([g, sv.p])
                else:
                    self.m.Add(sum(hit) + self.pen(spec.weight) >= sv.p)
            used = [sv.x[r] for r in avoid if r in sv.x]
            if used:
                if g is not None:
                    for u in used:
                        self.m.Add(u == 0).OnlyEnforceIf(g)
                else:
                    v = self.pen(spec.weight)
                    for u in used:
                        self.m.AddImplication(u, v)

    def rule_prefer_location(self, spec, g) -> None:
        for sv in self.sv:
            away = [sv.x[r] for r in sv.x if self.plan.room(r) and self.plan.room(r).location != spec.location]
            if not away:
                continue
            if g is not None:
                for u in away:
                    self.m.Add(u == 0).OnlyEnforceIf(g)
            else:
                v = self.pen(spec.weight)
                for u in away:
                    self.m.AddImplication(u, v)

    def rule_stability(self, spec, g) -> None:
        lead = self.plan.canon(spec.lead)
        a_week, b_week = self.weeks[0], self.weeks[1]
        sides = []
        for w in (a_week, b_week):
            mine = [sv for sv in self.sv if sv.s.lead and self.plan.canon(sv.s.lead) == lead and sv.in_week(w)]
            if not mine:
                return
            used = {}
            for r in {r for sv in mine for r in sv.prim}:
                v = self.m.NewBoolVar("")
                self.m.AddMaxEquality(v, [sv.x[r] for sv in mine if r in sv.x])
                used[r] = v
            sides.append(used)
        differs = None if g is not None else self.pen(spec.weight)
        for r in set(sides[0]) | set(sides[1]):
            za, zb = sides[0].get(r, 0), sides[1].get(r, 0)
            if g is not None:
                self.on(self.m.Add(za - zb == 0), g)
            else:
                self.m.Add(za - zb <= differs)
                self.m.Add(zb - za <= differs)

    # -------------------------------------------------------------- solve
    def build(self) -> None:
        for s in self.sc.sessions:
            self.add_session(s)
        self.add_builtins()
        for spec in self.sc.rules + implicit_specs(self.sc):
            self.add_rule(spec)
        if self.obj:
            self.m.Minimize(sum(w * v for w, v in self.obj))
        self.m.AddAssumptions(list(self.lits.values()))


def _solver(time_limit: float) -> cp_model.CpSolver:
    s = cp_model.CpSolver()
    s.parameters.max_time_in_seconds = time_limit
    s.parameters.num_workers = 1
    return s


def _describe(b: Builder, key: str) -> str:
    return b.desc[key]


def _explain(b: Builder, solver: cp_model.CpSolver, time_limit: float) -> list[str]:
    by_index = {v.Index(): k for k, v in b.lits.items()}
    core = [by_index[i] for i in solver.SufficientAssumptionsForInfeasibility() if i in by_index]
    b.m.ClearObjective()
    proto = b.m.Proto()

    def infeasible(keys: list[str]) -> bool:
        # fixing the literals in a copy lets presolve work; assumption mode is far slower
        m = cp_model.CpModel()
        m.Proto().copy_from(proto)
        m.Proto().assumptions.clear()
        for k in keys:
            domain = m.Proto().variables[b.lits[k].Index()].domain
            domain.clear()
            domain.extend([1, 1])
        return _solver(time_limit).Solve(m) == cp_model.INFEASIBLE

    for key in list(core):
        trial = [k for k in core if k != key]
        if infeasible(trial):
            core = trial
    return [_describe(b, k) for k in core]


def _apply(b: Builder, solver: cp_model.CpSolver) -> Scenario:
    new = b.sc.model_copy(deep=True)
    for sv, s in zip(b.sv, new.sessions):
        day = next(d for d, v in sv.d.items() if solver.BooleanValue(v))
        t = next(t for t, v in sv.st.items() if solver.BooleanValue(v))
        s.day = day
        s.start = to_hhmm(b.open + t * b.slot)
        s.end = to_hhmm(b.open + (t + sv.k) * b.slot)
        s.rooms.primary = [r for r in sv.prim if solver.BooleanValue(sv.x[r])]
    return new


def solve(sc: Scenario, time_limit: float = 30.0) -> SolveResult:
    b = Builder(sc)
    b.build()
    solver = _solver(time_limit)
    status = solver.Solve(b.m)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return SolveResult(
            "solved",
            _apply(b, solver),
            [sv.s.id for sv in b.sv if sv.free],
            int(solver.ObjectiveValue()) if b.obj else 0,
        )
    if status == cp_model.INFEASIBLE:
        return SolveResult("infeasible", core=_explain(b, solver, time_limit))
    return SolveResult("unknown")
