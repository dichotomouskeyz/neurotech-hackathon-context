"""CQ-gated stress from BFI and BVI. Optical heart rate stays a side panel."""

import math

import pytest

from dashboard.live_gate import ChannelStat, LiveGate, select_responsive
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
    return _sided(t, [bfi] * 8, [bfi] * 8, [bvi] * 8, [bvi] * 8, cq)


def _sided(t, bfi_left, bfi_right, bvi_left, bvi_right, cq):
    return [
        {"type": "bfi", "t": t, "left": bfi_left, "right": bfi_right},
        {"type": "bvi", "t": t, "left": bvi_left, "right": bvi_right},
        {"type": "cq", "t": t, "left": cq, "right": cq},
    ]


def _stresses(frames):
    return [frame for frame in frames if frame["type"] == "stress"]


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


def test_half_rate_wave_does_not_halve_optical_hr_or_raise_stress():
    """A stronger ~50 bpm tone on BFI must not replace a 100 bpm pulse.

    Heart rate stays on the side panel. Baseline still does not alert.
    """
    import numpy as np

    gate = LiveGate()
    _session(gate)
    _phase(gate, "baseline", 0.0)
    sample_rate = 40.0
    count = int(14 * sample_rate)
    timestamps = np.arange(count) / sample_rate
    phase = (timestamps * (100.0 / 60.0)) % 1.0
    width = np.minimum(phase, 1.0 - phase)
    pulse = np.exp(-0.5 * (width / 0.07) ** 2)
    pulse = pulse / float(np.std(pulse))
    slow = np.sin(2 * np.pi * (50.0 / 60.0) * timestamps)
    hr = None
    alerts = []
    for i in range(count):
        bfi = float(2.2 + 0.35 * pulse[i] + 0.5 * slow[i])
        for frame in gate.observe(_batch(float(timestamps[i]), bfi, 5.0, 0.95)):
            if frame["type"] == "hr":
                hr = frame
            if frame["type"] == "stress":
                alerts.append(frame)
    assert hr is not None
    frame_adapter.validate_python(hr)
    assert hr["source"] == "optical"
    assert hr["bpm"] == pytest.approx(100, abs=3)
    assert alerts
    assert not any(frame["alert"] for frame in alerts)
    assert all("bpm" not in frame["reason"] for frame in alerts)


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


def test_ten_percent_rise_completes_the_challenge_and_five_percent_does_not():
    quiet = LiveGate(stress_hold_s=0.5)
    _session(quiet)
    _phase(quiet, "baseline", 1.0)
    _rest(quiet)
    _phase(quiet, "hold", 20.0)
    low = []
    for t in (20.2, 20.6, 21.2):
        low.extend(quiet.observe(_batch(t, 2.10, 5.0, 0.95)))
    assert _stresses(low)
    assert not any(frame["alert"] for frame in _stresses(low))
    assert quiet.challenge_done(0.0) is False

    gate = LiveGate(stress_hold_s=0.5)
    _session(gate)
    _phase(gate, "baseline", 1.0)
    _rest(gate)
    _phase(gate, "hold", 20.0)
    raised = []
    for t in (30.0, 30.4, 30.9):
        raised.extend(gate.observe(_batch(t, 2.2, 5.0, 0.95)))
    stresses = _stresses(raised)
    assert stresses
    assert all(frame["alert"] for frame in stresses)
    assert stresses[-1]["index"] == pytest.approx(0.10, abs=0.01)
    assert stresses[-1]["alert_at"] == pytest.approx(0.10)
    assert gate.challenge_done(0.0) is True
    for frame in stresses:
        frame_adapter.validate_python(frame)


def test_responsive_cameras_set_the_index_and_are_named():
    """Four cameras rise. The other twelve stay flat and must not wash the index out."""
    gate = LiveGate(select_after_s=1.0)
    _session(gate)
    _phase(gate, "baseline", 1.0)
    _rest(gate, n=6, bfi=2.0, bvi=5.0)
    _phase(gate, "hold", 20.0)

    bfi_left = [2.0] * 8
    bfi_right = [2.0] * 8
    # L1 +30%, L3 +25%, L4 +25%, R2 +20%, R3 +12%. Top 4 drop R3.
    bfi_left[0] = 2.6
    bfi_left[2] = 2.5
    bfi_left[3] = 2.5
    bfi_right[1] = 2.4
    bfi_right[2] = 2.24
    flat_bvi = [5.0] * 8

    early = []
    for t in (20.2, 20.5):
        early.extend(gate.observe(_sided(t, bfi_left, bfi_right, flat_bvi, flat_bvi, 0.95)))
    early_stress = _stresses(early)[-1]
    # Before the rank locks, every eligible camera is in the median, so the
    # flat majority keeps the index under the 10% line.
    assert early_stress["index"] < 0.10
    assert early_stress["alert"] is False
    assert "channels" not in early_stress or early_stress["channels"] == ""

    locked = gate.observe(_sided(21.2, bfi_left, bfi_right, flat_bvi, flat_bvi, 0.95))
    stress = _stresses(locked)[-1]
    assert stress["index"] == pytest.approx(0.25, abs=0.02)
    assert stress["alert"] is True
    assert "L1" in stress["channels"]
    assert "L3" in stress["channels"]
    assert "L4" in stress["channels"]
    assert "R2" in stress["channels"]
    assert "R3" not in stress["channels"].split("BVI")[0]
    assert "BFI" in stress["channels"]
    frame_adapter.validate_python(stress)


def test_one_spiked_camera_does_not_amplify_the_index():
    gate = LiveGate(select_after_s=1.0)
    _session(gate)
    _phase(gate, "baseline", 1.0)
    _rest(gate)
    _phase(gate, "hold", 20.0)
    left = [2.0] * 8
    right = [2.0] * 8
    left[0] = 4.0
    frames = []
    for t in (20.2, 20.6, 21.2):
        frames.extend(gate.observe(_sided(t, left, right, [5.0] * 8, [5.0] * 8, 0.95)))
    stress = _stresses(frames)[-1]
    assert stress["index"] == pytest.approx(0.0, abs=0.02)
    assert stress["alert"] is False
    assert "all cameras" in stress["channels"]


def test_uniform_rise_is_not_inflated_above_the_measurement():
    gate = LiveGate(select_after_s=1.0)
    _session(gate)
    _phase(gate, "baseline", 1.0)
    _rest(gate)
    _phase(gate, "hold", 20.0)
    frames = []
    for t in (20.2, 20.6, 21.2):
        frames.extend(gate.observe(_batch(t, 2.2, 5.5, 0.95)))
    stress = _stresses(frames)[-1]
    assert stress["index"] == pytest.approx(0.10, abs=0.01)
    assert "BFI L1" in stress["channels"]


def test_session_hold_clears_the_resting_baseline_reason():
    gate = LiveGate()
    _session(gate)
    _phase(gate, "baseline", 1.0)
    _rest(gate)
    gate.observe(
        [
            {
                "type": "session",
                "t": 20.0,
                "active": True,
                "session_id": "s1",
                "subject_id": "s",
                "phase": "hold",
                "loop": "challenge",
                "loop_cue": "",
            }
        ]
    )
    frames = gate.observe(_batch(21.0, 2.0, 5.0, 0.95))
    stress = _stresses(frames)[-1]
    assert "resting baseline" not in stress["reason"]
    assert stress["alert"] is False


def test_nonpositive_hold_still_publishes_a_stress_frame():
    gate = LiveGate()
    _session(gate)
    _phase(gate, "baseline", 1.0)
    _rest(gate)
    _phase(gate, "hold", 20.0)
    zeros = [0.0] * 8
    frames = gate.observe(
        [
            {"type": "bfi", "t": 21.0, "left": zeros, "right": zeros},
            {"type": "bvi", "t": 21.0, "left": zeros, "right": zeros},
        ]
    )
    stress = _stresses(frames)[-1]
    assert "resting baseline" not in stress["reason"]
    assert stress["alert"] is False
    frame_adapter.validate_python(stress)


def _stat(side, index, current, cv=0.05):
    return ChannelStat((side, index), 2.0, current, cv, n_baseline=8, n_current=4)


def test_select_responsive_keeps_movers_and_drops_unstable_cameras():
    flat = _stat("left", 0, 2.0)
    mover_a = _stat("left", 2, 2.4)
    mover_b = _stat("right", 1, 2.3)
    noisy = _stat("right", 4, 3.0, cv=0.80)
    keys, amplified = select_responsive([flat, mover_a, mover_b, noisy])
    assert amplified is True
    assert keys == [("left", 2), ("right", 1)]
    only_one, amplified_one = select_responsive([flat, mover_a])
    assert amplified_one is False
    assert ("left", 0) in only_one and ("left", 2) in only_one
