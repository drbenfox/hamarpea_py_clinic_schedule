from dataclasses import dataclass, field

from .models import Room, Scenario, Session, to_hhmm, to_minutes


@dataclass(frozen=True)
class Occ:
    """One session in one cycle week, fully placed."""

    session: Session
    week: str
    day: str
    start: int
    end: int
    rooms: tuple[str, ...]  # primary + overflow
    people: tuple[str, ...]  # lead + named staff
    devices: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.session.id} (week {self.week} {self.day} {to_hhmm(self.start)}-{to_hhmm(self.end)})"

    def overlaps(self, other: "Occ") -> bool:
        return (
            self.week == other.week
            and self.day == other.day
            and self.start < other.end
            and other.start < self.end
        )


@dataclass
class Plan:
    scenario: Scenario
    occs: list[Occ] = field(default_factory=list)
    unplaced: list[tuple[Session, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._rooms = {r.id: r for r in self.scenario.rooms}
        self._people = {p.id: p for p in self.scenario.people}
        self._alias = {a: p.id for p in self.scenario.people for a in p.aliases}

    def room(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def canon(self, person_id: str) -> str:
        return self._alias.get(person_id, person_id)

    def person(self, person_id: str):
        return self._people.get(self.canon(person_id))

    def rooms_with(self, attribute: str) -> list[str]:
        return [r.id for r in self.scenario.rooms if attribute in r.attributes]

    def occs_on(self, week: str, day: str) -> list[Occ]:
        return [o for o in self.occs if o.week == week and o.day == day]


def build_plan(scenario: Scenario) -> Plan:
    plan = Plan(scenario)
    cycle = scenario.calendar.cycle_weeks
    for s in scenario.sessions:
        missing = [
            name
            for name, v in (("day", s.day), ("start", s.start), ("end", s.end))
            if v is None
        ]
        if not s.rooms.primary:
            missing.append("rooms")
        if missing:
            plan.unplaced.append((s, ", ".join(missing)))
            continue
        weeks = cycle if s.weeks == "weekly" else [s.weeks]
        people = ([plan.canon(s.lead)] if s.lead else []) + [
            plan.canon(p) for p in s.staff.named
        ]
        for w in weeks:
            plan.occs.append(
                Occ(
                    session=s,
                    week=w,
                    day=s.day,
                    start=to_minutes(s.start),
                    end=to_minutes(s.end),
                    rooms=tuple(s.rooms.primary + s.rooms.overflow),
                    people=tuple(dict.fromkeys(people)),
                    devices=tuple(s.devices or []),
                )
            )
    return plan
