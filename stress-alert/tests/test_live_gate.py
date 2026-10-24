"""CQ-gated stress from BFI and BVI. Optical heart rate stays a side panel."""

import math

import pytest

from dashboard.live_gate import LiveGate
from dashboard.schema import frame_adapter


def _session(gate, sid="s1"):
    gate.observe(
        [
            {
                "type": "session",
                "t": 0.0,
                "active": True,
                "session_id": sid,
                "subject_id": "s",
                "phase": None,
                "loop": "off",
                "loop_cue": "",
            }
        ]
    )


def _phase(gate, phase, t, sid="s1"):
    gate.observe([{"type": "phase", "t": t, "session_id": sid, "phase": phase, "source": "timer"}])


def _batch(t, bfi, bvi, cq):
    return [
        {"type": "bfi", "t": t, "left": [bfi] * 8, "right": [bfi] * 8},
        {"type": "bvi", "t": t, "left": [bvi] * 8, "right": [bvi] * 8},
        {"type": "cq", "t": t, "left": cq, "right": cq},
    ]


def _rest(gate, t0=10.0, n=6, bfi=2.0, bvi=5.0, cq=0.9):
    frames = []
    for i in range(n):
        frames.extend(gate.observe(_batch(t0 + i * 0.3, bfi, bvi, cq)))
    return frames


def test_bfi_elevation_alerts_and_poor_contact_clears_it():
    gate = LiveGate(stress_hold_s=0.5, settle_hold_s=0.5)
    _session(gate)
    _phase(gate, "baseline", 1.0)
    resting = _rest(gate)
    assert resting[-1]["alert"] is False
    assert "resting baseline" in resting[-1]["reason"]
    _phase(gate, "hold", 20.0)
    raised = []
    raised.extend(gate.observe(_batch(30.0, 2.8, 5.0, 0.9)))
    raised.extend(gate.observe(_batch(30.6, 2.8, 5.0, 0.9)))
    assert any(frame["alert"] and "BFI" in frame["reason"] for frame in raised)
    assert gate.challenge_done(0.0)
    gated = gate.observe(_batch(32.0, 4.0, 9.0, 0.3))
    assert gated[-1]["type"] == "stress"
    assert gated[-1]["alert"] is False
    assert "poor_coupling" in gated[-1]["reason"]
    assert gate.challenge_done(0.0) is False
    for frame in raised + gated:
        if frame["type"] == "stress":
            frame_adapter.validate_python(frame)


def test_bvi_elevation_alerts_while_bfi_stays_at_baseline():
    gate = LiveGate()
    _session(gate)
    _phase(gate, "baseline", 1.0)
    _rest(gate)
    _phase(gate, "hold", 20.0)
    frames = gate.observe(_batch(30.0, 2.0, 7.0, 0.95))
    stress = frames[-1]
    assert stress["alert"] is True
    assert "BVI" in stress["reason"]
    assert "bpm" not in stress["reason"]


def test_optical_pulse_fills_hr_and_does_not_set_the_stress_label():
    gate = LiveGate()
    _session(gate)
    _phase(gate, "baseline", 0.0)
    hr = None
    alerts = []
    # 12 s of a 1.2 Hz (72 bpm) pulse around a flat perfusion mean.
    for i in range(480):
        t = i / 40.0
        bfi = 2.0 + 0.12 * math.sin(2 * math.pi * 1.2 * t)
        frames = gate.observe(_batch(t, bfi, 5.0, 0.95))
        for frame in frames:
            if frame["type"] == "hr":
                hr = frame
            if frame["type"] == "stress":
                alerts.append(frame)
    _phase(gate, "hold", 12.0)
    for i in range(40):
        t = 12.0 + i / 40.0
        bfi = 2.0 + 0.12 * math.sin(2 * math.pi * 1.2 * t)
        for frame in gate.observe(_batch(t, bfi, 5.0, 0.95)):
            if frame["type"] == "stress":
                alerts.append(frame)
    assert hr is not None
    frame_adapter.validate_python(hr)
    assert hr["source"] == "optical"
    assert hr["bpm"] == pytest.approx(72, abs=3)
    assert alerts
    assert not any(frame["alert"] for frame in alerts)


def test_recovery_tau_is_attached_when_perfusion_decays():
    gate = LiveGate()
    _session(gate)
    _phase(gate, "baseline", 0.0)
    _rest(gate, t0=1.0)
    _phase(gate, "hold", 5.0)
    gate.observe(_batch(6.0, 2.8, 5.0, 0.95))
    _phase(gate, "recovery", 7.0)
    last = None
    # Smooth BFI decays toward 2.0 with tau about 8 s, long enough to fit.
    for i in range(80):
        t = 8.0 + i * 0.25
        bfi = 2.0 + 0.8 * math.exp(-(t - 8.0) / 8.0)
        frames = gate.observe(_batch(t, bfi, 5.0, 0.95))
        for frame in frames:
            if frame["type"] == "stress":
                last = frame
    assert last is not None
    assert last.get("tau_s") is not None
    assert 2.0 < last["tau_s"] < 30.0
    frame_adapter.validate_python(last)
