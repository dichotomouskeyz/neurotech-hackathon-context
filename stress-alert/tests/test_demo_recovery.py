"""Demo Mode plays a recovery and never publishes contact quality of 1.00."""

import itertools

import pytest
from fastapi.testclient import TestClient

from dashboard.demo_recovery import CQ_DIP_END_S, CQ_DIP_START_S, demo_frames, demo_sample
from dashboard.live_gate import LiveGate
from dashboard.schema import frame_adapter
from tests.test_live_gate import _phase, _session


def test_demo_contact_stays_below_one_and_the_dip_is_a_real_miss():
    phases = (None, "baseline", "hold", "recovery", "end")
    seen = set()
    for phase, step in itertools.product(phases, range(0, 250)):
        bfi, bvi, cq = demo_sample(phase, step * 0.1)
        seen.add(cq)
        assert 0.0 <= cq < 1.0
        assert bfi > 0 and bvi > 0
        frames = demo_frames(phase, step * 0.1, t=float(step))
        assert [frame["type"] for frame in frames] == ["bfi", "bvi", "cq"]
        assert frames[-1]["left"] < 1.0 and frames[-1]["right"] < 1.0
        frame_adapter.validate_python(frames[-1])
    assert 0.32 in seen
    assert 1.0 not in seen


def test_scripted_recovery_unlocks_then_bad_contact_locks_again():
    """The demo arc: BFI returns and CQ is good, then a contact dip shuts the gate."""
    gate = LiveGate(stress_hold_s=0.4, settle_hold_s=0.4)
    _session(gate)
    _phase(gate, "baseline", 0.0)
    for i in range(40):
        bfi, bvi, cq = demo_sample("baseline", i * 0.1)
        gate.observe(_sided_batch(i * 0.1, bfi, bvi, cq))
    _phase(gate, "hold", 4.0)
    for i in range(30):
        elapsed = i * 0.1
        bfi, bvi, cq = demo_sample("hold", elapsed)
        gate.observe(_sided_batch(4.0 + elapsed, bfi, bvi, cq))
    assert gate.challenge_done(0.0) is True

    _phase(gate, "recovery", 8.0)
    opened = False
    relocked = False
    reopened = False
    for i in range(240):
        elapsed = i * 0.1
        bfi, bvi, cq = demo_sample("recovery", elapsed)
        assert cq < 1.0
        frames = gate.observe(_sided_batch(8.0 + elapsed, bfi, bvi, cq))
        stresses = [frame for frame in frames if frame["type"] == "stress"]
        for frame in stresses:
            frame_adapter.validate_python(frame)
            if elapsed <= 7.0:
                assert frame["gate"] == "locked"
            if 11.0 <= elapsed < CQ_DIP_START_S and frame["gate"] == "open":
                opened = True
                assert frame["difficulty"] >= 2
                assert frame["task"] in {"advance", "hold"}
            if CQ_DIP_START_S + 0.4 <= elapsed < CQ_DIP_END_S:
                assert frame["gate"] == "locked"
                assert frame["gate_reason"] == "locked_cq"
                relocked = True
            if elapsed >= CQ_DIP_END_S + 1.0 and frame["gate"] == "open":
                reopened = True
                assert frame["difficulty"] >= 2
    assert opened and relocked and reopened
    assert gate.settled(0.0) is True


def _sided_batch(t, bfi, bvi, cq):
    return [
        {"type": "bfi", "t": t, "left": [bfi] * 8, "right": [bfi] * 8},
        {"type": "bvi", "t": t, "left": [bvi] * 8, "right": [bvi] * 8},
        {"type": "cq", "t": t, "left": cq, "right": cq},
    ]


def test_recovered_bfi_with_poor_contact_cannot_settle():
    gate = LiveGate(stress_hold_s=0.3, settle_hold_s=0.3)
    _session(gate)
    _phase(gate, "baseline", 0.0)
    for i in range(8):
        gate.observe(_sided_batch(float(i), 2.0, 5.0, 0.9))
    _phase(gate, "hold", 10.0)
    gate.observe(_sided_batch(11.0, 2.8, 5.0, 0.9))
    gate.observe(_sided_batch(12.0, 2.8, 5.0, 0.9))
    _phase(gate, "recovery", 13.0)
    frames = []
    for i in range(8):
        frames.extend(gate.observe(_sided_batch(14.0 + i * 0.3, 2.02, 5.0, 0.28)))
    stresses = [frame for frame in frames if frame["type"] == "stress"]
    assert stresses
    assert all(frame["gate"] == "locked" for frame in stresses)
    assert all(frame["gate_reason"] == "locked_cq" for frame in stresses)
    assert gate.settled(0.0) is False


def test_demo_start_refuses_a_live_scan_and_stop_is_safe(app):
    app.state.device.state = lambda: {"scanning": True}
    with TestClient(app) as client:
        refused = client.post("/api/demo/start")
        assert refused.status_code == 409
        assert "contact" in refused.json()["detail"].lower()
        assert client.get("/api/demo").json()["running"] is False


@pytest.fixture
def app(tmp_path):
    from dashboard.app import create_app

    return create_app(sessions_dir=tmp_path, lsl_markers=False)


def test_demo_start_and_stop_round_trip(app):
    with TestClient(app) as client:
        started = client.post("/api/demo/start")
        assert started.status_code == 200
        body = started.json()
        assert body["running"] is True
        assert body["subject_id"] == "demo"
        assert body["gate"] == "locked"
        stopped = client.post("/api/demo/stop")
        assert stopped.status_code == 200
        assert stopped.json()["running"] is False
        assert stopped.json()["active"] is False
