import pytest
from pydantic import ValidationError

from dashboard.schema import frame_adapter

CAMS = [1.0, 2.0, None, 4.0, 5.0, 6.0, 7.0, 8.0]

VALID = [
    {"type": "bfi", "t": 1.0, "left": CAMS, "right": CAMS},
    {"type": "bvi", "t": 1.0, "left": CAMS, "right": CAMS},
    {"type": "hr", "t": 1.0, "source": "optical", "bpm": 72},
    {"type": "hr", "t": 1.0, "source": "ecg", "bpm": 71.5},
    {"type": "cq", "t": 1.0, "left": 0.9, "right": 0.2},
    {"type": "stress", "t": 1.0, "index": 0.4},
    {"type": "phase", "t": 1.0, "session_id": "s1", "phase": "hold", "source": "manual"},
    {"type": "status", "source": "mentalab", "connected": True},
]


@pytest.mark.parametrize("frame", VALID, ids=lambda f: f["type"])
def test_valid_frames_round_trip(frame):
    dumped = frame_adapter.validate_python(frame).model_dump(mode="json")
    assert dumped["type"] == frame["type"]


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "bfi", "t": 1.0, "left": CAMS[:7], "right": CAMS},  # 7 cameras
        {"type": "hr", "t": 1.0, "source": "ppg", "bpm": 72},  # unknown source
        {"type": "hr", "t": 1.0, "source": "ecg", "bpm": 0},  # impossible rate
        {"type": "cq", "t": 1.0, "left": 1.5, "right": 0.5},  # out of 0..1
        {"type": "phase", "t": 1.0, "session_id": "s1", "phase": "nap", "source": "manual"},
        {"type": "status", "source": "x", "connected": True, "extra": 1},  # unknown field
        {"type": "eeg", "t": 1.0},  # unknown type
    ],
)
def test_invalid_frames_rejected(frame):
    with pytest.raises(ValidationError):
        frame_adapter.validate_python(frame)
