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
            bad = {"type": "hr", "t": 1.0, "source": "ecg", "bpm": -5}
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
    for frame in dev_feed.frames_for(rows[0], t=0.0):
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
