import pytest
from pydantic import ValidationError

from dashboard.schema import frame_adapter

CAMS = [1.0, 2.0, None, 4.0, 5.0, 6.0, 7.0, 8.0]

VALID = [
    {"type": "bfi", "t": 1.0, "left": CAMS, "right": CAMS},
    {"type": "bvi", "t": 1.0, "left": CAMS, "right": CAMS},
    {"type": "hr", "t": 1.0, "source": "optical", "bpm": 72},
    {"type": "cq", "t": 1.0, "left": 0.9, "right": 0.2},
    {"type": "stress", "t": 1.0, "index": 0.4},
    {"type": "phase", "t": 1.0, "session_id": "s1", "phase": "hold", "source": "manual"},
    {"type": "status", "source": "omotion", "connected": True},
    {
        "type": "device",
        "t": 1.0,
        "connected": True,
        "console": True,
        "left": True,
        "right": False,
        "scanning": False,
    },
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
        {"type": "hr", "t": 1.0, "source": "ecg", "bpm": 71},  # ECG dropped 2026-10-24
        {"type": "hr", "t": 1.0, "source": "optical", "bpm": 0},  # impossible rate
        {"type": "cq", "t": 1.0, "left": 1.5, "right": 0.5},  # out of 0..1
        {"type": "phase", "t": 1.0, "session_id": "s1", "phase": "nap", "source": "manual"},
        {"type": "status", "source": "x", "connected": True, "extra": 1},  # unknown field
        {"type": "eeg", "t": 1.0},  # unknown type
    ],
)
def test_invalid_frames_rejected(frame):
    with pytest.raises(ValidationError):
        frame_adapter.validate_python(frame)


def test_stress_tau_and_closed_loop_session_are_in_the_contract():
    stress = frame_adapter.validate_python(
        {
            "type": "stress",
            "t": 1.0,
            "index": 0.35,
            "alert": True,
            "reason": "elevated_stress: BFI 35% >= 20% vs baseline",
            "tau_s": 22.4,
            "recovery_score": 0.8,
            "alert_at": 0.10,
            "channels": "BFI L3, L4, R2",
        }
    )
    assert stress.tau_s == pytest.approx(22.4)
    assert stress.alert_at == pytest.approx(0.10)
    assert stress.channels == "BFI L3, L4, R2"
    session = frame_adapter.validate_python(
        {
            "type": "session",
            "t": 1.0,
            "active": True,
            "phase": "recovery",
            "loop": "coach",
            "loop_cue": "Pause the hold and breathe with the circle.",
        }
    )
    assert session.loop == "coach"
    with pytest.raises(ValidationError):
        frame_adapter.validate_python(
            {"type": "session", "t": 1.0, "active": True, "loop": "stressed"}
        )
