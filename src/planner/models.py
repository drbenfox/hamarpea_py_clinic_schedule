import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class _Base(BaseModel):
    # free-form: new attributes in YAML are kept, never rejected
    model_config = ConfigDict(extra="allow")


class Calendar(_Base):
    days: list[str] = ["sun", "mon", "tue", "wed", "thu"]
    open: str = "08:00"
    close: str = "18:00"
    slot_minutes: int = 30
    cycle_weeks: list[str] = ["A", "B"]


class Options(_Base):
    layout_fixed: bool = True
    curtain_room5: bool = False


class Location(_Base):
    id: str
    name: str | None = None
    rooms_known: bool = True


class Room(_Base):
    id: str
    location: str = "main"
    attributes: list[str] = []


class Person(_Base):
    id: str
    role: str
    aliases: list[str] = []
    days: list[str] | None = None
    unavailable_days: list[str] | None = None
    max_shifts_per_week: int | None = None
    works_with: list[str] = []
    notes: str | None = None


class Device(_Base):
    id: str
    allowed_rooms: list[str] = []


class SessionRooms(_Base):
    primary: list[str] = []
    preferred: list[str] = []
    overflow: list[str] = []


class SessionStaff(_Base):
    named: list[str] = []
    count: dict[str, int] = {}


class Session(_Base):
    id: str
    lead: str | None = None
    weeks: str = "weekly"
    day: str | None = None
    start: str | None = None
    end: str | None = None
    rooms: SessionRooms = Field(default_factory=SessionRooms)
    room_needs: list[str] = []
    staff: SessionStaff = Field(default_factory=SessionStaff)
    devices: list[str] | None = None
    needs_access: list[str] | None = None
    focus: list[str] = []
    covers_tasks: list[str] = []
    locked: dict[str, bool] = {}

    @field_validator("start", "end")
    @classmethod
    def _time_format(cls, v: str | None) -> str | None:
        if v is not None and not _TIME.match(v):
            raise ValueError(f"time must be HH:MM, got {v!r}")
        return v


class Task(_Base):
    id: str
    currently: str | None = None
    may_become_session: bool = False


class RuleSpec(_Base):
    id: str
    type: str
    strength: Literal["hard", "soft"] = "hard"
    weight: int = 1


class Scenario(_Base):
    version: int = 1
    calendar: Calendar = Field(default_factory=Calendar)
    options: Options = Field(default_factory=Options)
    locations: list[Location] = []
    rooms: list[Room] = []
    people: list[Person] = []
    devices: list[Device] = []
    appointment_types: list[dict] = []
    sessions: list[Session] = []
    tasks: list[Task] = []
    rules: list[RuleSpec] = []
    proposals: list[dict] = []
    focus_targets: dict[str, float | None] = {}
    # source lines carrying TODO / ASSUMED markers; filled by the loader
    notes: list[tuple[int, str]] = Field(default_factory=list, exclude=True)
