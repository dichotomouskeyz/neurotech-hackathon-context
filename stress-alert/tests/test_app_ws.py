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
