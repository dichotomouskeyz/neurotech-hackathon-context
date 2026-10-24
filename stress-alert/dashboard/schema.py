"""Message contract between producers (ingest, features, logger) and the dashboard.

Every frame is a JSON object with a ``type`` field. ``t`` is seconds on the shared
clock, LSL ``local_clock()`` (see ``dashboard.clock``). See SCHEMA.md for the
human-readable version.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

Unit = Annotated[float, Field(ge=0.0, le=1.0)]
Cameras = Annotated[list[float | None], Field(min_length=8, max_length=8)]


class _Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hemo(_Frame):
    """BFI or BVI for the 8 cameras on each side; null for a disabled camera."""

    type: Literal["bfi", "bvi"]
    t: float
    left: Cameras
    right: Cameras


class HeartRate(_Frame):
    type: Literal["hr"]
    t: float
    source: Literal["optical"]
    bpm: Annotated[float, Field(gt=0, lt=300)]


class ContactQuality(_Frame):
    type: Literal["cq"]
    t: float
    left: Unit
    right: Unit


class Stress(_Frame):
    type: Literal["stress"]
    t: float
    index: float
    recovery_score: float | None = None
    alert: bool = False
    reason: str = ""


PhaseName = Literal["baseline", "hold", "recovery", "end"]


class Phase(_Frame):
    type: Literal["phase"]
    t: float
    session_id: str
    phase: PhaseName
    source: Literal["manual", "timer"]


class Session(_Frame):
    """Current session state, sent by the dashboard itself whenever it changes."""

    type: Literal["session"]
    t: float
    active: bool
    session_id: str | None = None
    subject_id: str = ""
    phase: PhaseName | None = None
    phase_t: float | None = None
    timer_next: PhaseName | None = None
    timer_ends_t: float | None = None


class Status(_Frame):
    type: Literal["status"]
    source: str
    connected: bool
    detail: str = ""


Frame = Annotated[
    Hemo | HeartRate | ContactQuality | Stress | Phase | Session | Status,
    Field(discriminator="type"),
]

frame_adapter: TypeAdapter[Frame] = TypeAdapter(Frame)
