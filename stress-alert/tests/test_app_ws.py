import json

from fastapi.testclient import TestClient

from dashboard import dev_feed
from dashboard.app import create_app

CAMS = [1.0] * 8


def test_index_and_static_served():
    client = TestClient(create_app())
    assert "stress-alert" in client.get("/").text
    assert client.get("/static/vendor/uPlot.iife.min.js").status_code == 200


def test_ingest_frames_reach_browser_and_errors_go_back_to_producer():
    client = TestClient(create_app())
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


def test_malformed_json_is_reported():
    client = TestClient(create_app())
    with client.websocket_connect("/ws/ingest") as producer:
        producer.send_text("{not json")
        assert producer.receive_json()["errors"][0].startswith("invalid JSON")


def test_dev_feed_frames_match_the_contract():
    from dashboard.schema import frame_adapter

    rows = dev_feed.load_rows()
    assert len(rows) == 1201
    for frame in dev_feed.frames_for(rows[0], t=0.0):
        frame_adapter.validate_python(frame)
