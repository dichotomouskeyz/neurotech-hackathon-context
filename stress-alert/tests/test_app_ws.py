import json

import pytest
from fastapi.testclient import TestClient

from dashboard import dev_feed
from dashboard.app import create_app

CAMS = [1.0] * 8


@pytest.fixture
def app(tmp_path):
    return create_app(sessions_dir=tmp_path, lsl_markers=False)


def test_index_and_static_served(app):
    client = TestClient(app)
    assert "stress-alert" in client.get("/").text
    assert client.get("/static/vendor/uPlot.iife.min.js").status_code == 200


def test_ingest_frames_reach_browser_and_errors_go_back_to_producer(app):
    client = TestClient(app)
    with client.websocket_connect("/ws") as browser:
        with client.websocket_connect("/ws/ingest?source=test") as producer:
            assert browser.receive_json() == [
                {"type": "status", "source": "test", "connected": True, "detail": ""}
            ]
            good = {"type": "bfi", "t": 1.0, "left": CAMS, "right": CAMS}
            bad = {"type": "hr", "t": 1.0, "source": "optical", "bpm": -5}
            producer.send_text(json.dumps([good, bad]))
            error = producer.receive_json()
            assert error["type"] == "error"
            assert error["errors"][0].startswith("frame 1: hr.bpm")
            assert browser.receive_json() == [good]
        assert browser.receive_json()[0]["connected"] is False


def test_malformed_json_is_reported(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/ingest") as producer:
        producer.send_text("{not json")
        assert producer.receive_json()["errors"][0].startswith("invalid JSON")


def test_dev_feed_frames_match_the_contract():
    from dashboard.schema import frame_adapter

    rows = dev_feed.load_rows()
    assert len(rows) == 1201
    frames = dev_feed.frames_for(rows[0], t=0.0)
    assert [frame["type"] for frame in frames] == ["bfi", "bvi", "cq"]
    assert frames[-1]["left"] == 1
    assert frames[-1]["right"] == 1
    for frame in frames:
        frame_adapter.validate_python(frame)


def test_session_api_drives_logger_and_reaches_browser(app):
    with TestClient(app) as client, client.websocket_connect("/ws") as browser:
        assert client.post("/api/phase", json={"phase": "baseline"}).status_code == 409
        state = client.post("/api/session/start", json={"subject_id": "api"}).json()
        assert state["active"] and state["phase"] is None
        assert client.post("/api/phase", json={"phase": "baseline"}).json()["phase"] == "baseline"
        conflict = client.post("/api/phase", json={"phase": "recovery"})
        assert conflict.status_code == 409 and "baseline to recovery" in conflict.json()["detail"]
        assert client.post("/api/phase", json={"phase": "nap"}).status_code == 422
        assert not client.post("/api/session/stop").json()["active"]

        seen = []
        while not any(f["type"] == "session" and not f["active"] for f in seen[1:]):
            seen.extend(browser.receive_json())
        assert [f["phase"] for f in seen if f["type"] == "phase"] == ["baseline", "end"]


def _hemo(t, bfi, bvi, cq):
    return [
        {"type": "bfi", "t": t, "left": [bfi] * 8, "right": [bfi] * 8},
        {"type": "bvi", "t": t, "left": [bvi] * 8, "right": [bvi] * 8},
        {"type": "cq", "t": t, "left": cq, "right": cq},
    ]


def test_ingest_scores_perfusion_and_gates_on_contact(app):
    """Stress comes from BFI/BVI versus baseline. Poor contact clears the label."""
    from dashboard.schema import frame_adapter

    client = TestClient(app)
    with client.websocket_connect("/ws/ingest?source=sim") as prod:
        assert client.post("/api/session/start", json={"subject_id": "gate"}).status_code == 200
        assert client.post("/api/phase", json={"phase": "baseline"}).status_code == 200
        for i in range(6):
            prod.send_text(json.dumps(_hemo(50 + i * 0.3, 2.0, 5.0, 0.92)))
        assert client.post("/api/phase", json={"phase": "hold"}).status_code == 200
        prod.send_text(json.dumps(_hemo(60.0, 2.8, 5.0, 0.92)))
        prod.send_text(json.dumps(_hemo(61.0, 2.8, 5.0, 0.92)))
        prod.send_text(json.dumps(_hemo(62.0, 4.0, 8.0, 0.28)))
    with client.websocket_connect("/ws") as browser:
        seen = browser.receive_json()
    stress = [frame for frame in seen if frame["type"] == "stress"]
    assert stress, "expected derived stress frames"
    for frame in stress:
        frame_adapter.validate_python(frame)
    assert any(frame["alert"] and "BFI" in frame["reason"] for frame in stress)
    assert any(not frame["alert"] and "poor_coupling" in frame["reason"] for frame in stress)
    assert all("bpm" not in frame["reason"] for frame in stress)


def test_closed_loop_starts_a_session_and_can_run_again_after_end(app):
    client = TestClient(app)
    first = client.post(
        "/api/protocol/start",
        json={
            "baseline": 30,
            "hold": 30,
            "recovery": 30,
            "closed_loop": True,
            "subject_id": "judge",
        },
    )
    assert first.status_code == 200
    assert first.json()["active"] is True and first.json()["subject_id"] == "judge"
    assert client.post("/api/protocol/stop").status_code == 200
    assert client.post("/api/session/stop").status_code == 200

    client.post("/api/session/start", json={"subject_id": "old"})
    for phase in ("baseline", "hold", "recovery", "end"):
        assert client.post("/api/phase", json={"phase": phase}).status_code == 200
    old_id = client.get("/api/session").json()["session_id"]
    again = client.post(
        "/api/protocol/start",
        json={
            "baseline": 30,
            "hold": 30,
            "recovery": 30,
            "closed_loop": True,
            "subject_id": "judge-2",
        },
    )
    assert again.status_code == 200
    assert again.json()["session_id"] != old_id
    assert again.json()["subject_id"] == "judge-2"
    client.post("/api/protocol/stop")


def _protocol(recovered_within_pct=None):
    body = {"baseline": 20, "hold": 0, "recovery": 20, "continue_s": 30, "closed_loop": True}
    if recovered_within_pct is not None:
        body["recovered_within_pct"] = recovered_within_pct
    return body


def test_protocol_start_applies_the_operator_recovery_boundary(app):
    """The timed-protocol percent is the line LiveGate compares. Bad values do not stick."""
    client = TestClient(app)
    assert app.state.gate.recovered_below == pytest.approx(0.05)

    for bad in (0, 26, 100):
        rejected = client.post("/api/protocol/start", json=_protocol(bad))
        assert rejected.status_code == 422
        assert app.state.gate.recovered_below == pytest.approx(0.05)

    # A start that cannot run must not leave a new line behind.
    refused = client.post("/api/protocol/start", json={**_protocol(12), "closed_loop": False})
    assert refused.status_code == 409
    assert app.state.gate.recovered_below == pytest.approx(0.05)

    started = client.post("/api/protocol/start", json=_protocol(12))
    assert started.status_code == 200
    assert app.state.gate.recovered_below == pytest.approx(0.12)
    assert app.state.gate.settle_index == pytest.approx(0.12)
    assert client.post("/api/protocol/stop").status_code == 200
    assert client.post("/api/session/stop").status_code == 200


def test_protocol_start_without_a_boundary_keeps_five_percent(app):
    client = TestClient(app)
    started = client.post("/api/protocol/start", json=_protocol())
    assert started.status_code == 200
    assert app.state.gate.recovered_below == pytest.approx(0.05)
    client.post("/api/protocol/stop")
    client.post("/api/session/stop")


def test_demo_start_does_not_change_the_recovery_boundary(app):
    """The boundary is a Run timed control. Demo Mode only starts the replay."""
    with TestClient(app) as client:
        empty = client.post("/api/demo/start")
        assert empty.status_code == 200
        assert app.state.gate.recovered_below == pytest.approx(0.05)
        assert client.post("/api/demo/stop").status_code == 200

        started = client.post("/api/demo/start", json={"recovered_within_pct": 8})
        assert started.status_code == 200
        assert app.state.gate.recovered_below == pytest.approx(0.05)
        assert client.get("/api/session").json()["active"] is False
        assert client.post("/api/demo/stop").status_code == 200


def _first_bfi(browser, limit=40):
    for _ in range(limit):
        for frame in browser.receive_json():
            if frame.get("type") == "bfi":
                return frame
    return None


def test_take_batch_is_sixteen_varied_channels():
    rows = dev_feed.load_rows()
    batch, index = dev_feed.take_batch(rows, 0)
    assert index == dev_feed.BATCH
    bfi = [frame for frame in batch if frame["type"] == "bfi"]
    assert len(bfi) == dev_feed.BATCH
    expected = next(frame for frame in dev_feed.frames_for(rows[0], 0.0) if frame["type"] == "bfi")
    assert bfi[0]["left"] == expected["left"]
    assert bfi[0]["right"] == expected["right"]
    assert len(bfi[0]["left"]) == 8 and len(bfi[0]["right"]) == 8
    assert len(set(bfi[0]["left"])) > 1
    assert len(set(bfi[0]["right"])) > 1


async def test_replay_stops_before_publishing_over_a_scan():
    calls = {"n": 0}

    def scanning() -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    published: list[list[dict]] = []
    reason = await dev_feed.replay(published.append, scanning=scanning)
    assert reason == "scan"
    assert len(published) == 1
    kinds = [frame["type"] for frame in published[0]]
    assert kinds[0] == "bfi" and "bvi" in kinds and "cq" in kinds


def test_demo_mode_replays_the_same_sample_as_dev_feed(app):
    rows = dev_feed.load_rows()
    sample = dev_feed.frames_for(rows[0], 0.0)
    expected = next(frame for frame in sample if frame["type"] == "bfi")
    expected_cq = next(frame for frame in sample if frame["type"] == "cq")
    with TestClient(app) as client, client.websocket_connect("/ws") as browser:
        assert client.post("/api/demo/start").status_code == 200
        assert client.get("/api/demo").json() == {"running": True}
        seen = []
        bfi = None
        for _ in range(40):
            batch = browser.receive_json()
            seen.extend(batch)
            if bfi is None:
                bfi = next((frame for frame in seen if frame.get("type") == "bfi"), None)
            if bfi is not None and any(frame.get("type") == "stress" for frame in seen):
                break
        assert bfi is not None
        assert bfi["left"] == expected["left"]
        assert bfi["right"] == expected["right"]
        assert len(set(bfi["left"])) > 1
        cq = next(frame for frame in seen if frame.get("type") == "cq" and frame["t"] == bfi["t"])
        assert cq["left"] == expected_cq["left"]
        assert cq["right"] == expected_cq["right"]
        assert any(frame.get("type") == "stress" for frame in seen)
        assert client.post("/api/demo/start").status_code == 409
        assert client.post("/api/demo/stop").json() == {"running": False}
        assert client.get("/api/demo").json()["running"] is False


def test_dev_feed_flag_is_demo_mode(tmp_path):
    app = create_app(sessions_dir=tmp_path, lsl_markers=False, dev_feed=True)
    rows = dev_feed.load_rows()
    sample = {
        (tuple(frame["left"]), tuple(frame["right"]))
        for row in rows
        for frame in dev_feed.frames_for(row, 0.0)
        if frame["type"] == "bfi"
    }
    with TestClient(app) as client, client.websocket_connect("/ws") as browser:
        assert client.get("/api/demo").json()["running"] is True
        bfi = _first_bfi(browser)
        assert bfi is not None
        assert (tuple(bfi["left"]), tuple(bfi["right"])) in sample
        assert len(set(bfi["left"])) > 1
        assert client.post("/api/demo/stop").json()["running"] is False
        assert client.get("/api/demo").json()["running"] is False


def test_protocol_stop_leaves_the_demo_feed_running(app):
    with TestClient(app) as client:
        assert client.post("/api/demo/start").status_code == 200
        assert client.post("/api/session/start", json={"subject_id": "judge"}).status_code == 200
        started = client.post(
            "/api/protocol/start",
            json={
                "baseline": 30,
                "hold": 0,
                "recovery": 20,
                "continue_s": 30,
                "closed_loop": True,
            },
        )
        assert started.status_code == 200
        assert client.get("/api/demo").json()["running"] is True
        assert client.post("/api/protocol/stop").status_code == 200
        assert client.get("/api/demo").json()["running"] is True
        assert client.get("/api/session").json()["active"] is True
        assert client.post("/api/demo/stop").status_code == 200
        assert client.get("/api/session").json()["active"] is True
        client.post("/api/session/stop")


def test_scan_start_stops_demo_before_the_device_is_used(app):
    with TestClient(app) as client:
        assert client.post("/api/demo/start").status_code == 200
        refused = client.post("/api/device/scan/start")
        assert refused.status_code == 409
        assert client.get("/api/demo").json()["running"] is False
        assert "connect" in refused.json()["detail"].lower()
