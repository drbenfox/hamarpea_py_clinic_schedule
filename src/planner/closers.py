from .models import Scenario
from .plan import build_plan
from .models import to_hhmm


def closers(sc: Scenario, role: str = "sales") -> dict:
    """Who closes for which doctor and when. Hours are the doctor's session hours."""
    plan = build_plan(sc)
    people = [p.id for p in sc.people if p.role == role]
    office = {r.who: r.room for r in sc.rules if r.type == "pin"}
    weeks = []
    for w in sc.calendar.cycle_weeks:
        days = []
        for d in sc.calendar.days:
            items = [
                {
                    "person": pid,
                    "doctor": o.session.lead,
                    "session": o.session.id,
                    "start": to_hhmm(o.start),
                    "end": to_hhmm(o.end),
                    "office": office.get(pid),
                }
                for o in sorted(plan.occs_on(w, d), key=lambda o: o.start)
                for pid in o.people
                if pid in people and pid != plan.canon(o.session.lead or "")
            ]
            days.append({"day": d, "items": items})
        weeks.append({"week": w, "days": days})
    return {"role": role, "people": people, "weeks": weeks}
