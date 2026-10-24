"""Message contract between producers (ingest, features, logger) and the dashboard.

Every frame is a JSON object with a ``type`` field. ``t`` is seconds on the shared
clock (LSL ``local_clock()`` when available, otherwise ``time.monotonic()`` on the
host running the dashboard). See SCHEMA.md for the human-readable version.
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
    source: Literal["optical", "ecg"]
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


class Phase(_Frame):
    type: Literal["phase"]
    t: float
    session_id: str
    phase: Literal["baseline", "hold", "recovery", "end"]
    source: Literal["manual", "timer"]


class Status(_Frame):
    type: Literal["status"]
    source: str
    connected: bool
    detail: str = ""


Frame = Annotated[
    Hemo | HeartRate | ContactQuality | Stress | Phase | Status,
    Field(discriminator="type"),
]

frame_adapter: TypeAdapter[Frame] = TypeAdapter(Frame)
