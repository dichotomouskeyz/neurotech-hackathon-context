"""Session replay: list recordings, seek, and hub frames."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.hub import Hub
from dashboard.live_gate import LiveGate
from dashboard.replay import (
    ReplayEngine,
    ensure_session_scan_copy,
    list_recordings,
    newest_scan_csv,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_scan.csv"


def test_list_empty_skips_phase_logs_and_stays_fast(tmp_path):
    assert list_recordings(tmp_path) == []
    for index in range(40):
        session = tmp_path / f"20261024-15{index:04d}_anon"
        session.mkdir()
        (session / "meta.json").write_text(
            f'{{"session_id": "{session.name}", "subject_id": "anon"}}'
        )
        (session / "events.csv").write_text(
            "t,wall_time,session_id,phase,source\n1,2026,s,baseline,manual\n"
        )
    scans = tmp_path / "device-scans"
    scans.mkdir()
    (scans / "scan99_anon.csv").write_text(
        "frame_id,timestamp_s,bfi_l1\n1,0.025,1.5\n400,10.0,1.6\n"
    )
    import time

    started = time.perf_counter()
    listed = list_recordings(tmp_path)
    assert time.perf_counter() - started < 1.0
    assert len(listed) == 1
    assert listed[0]["path"].endswith("scan99_anon.csv")
    assert listed[0]["duration_s"] == 10.0
    assert listed[0]["frames"] is None


def test_replay_page_does_not_stick_on_loading():
    html = (ROOT / "dashboard/static/index.html").read_text()
    js = (ROOT / "dashboard/static/app.js").read_text()
    assert "Loading…" not in html
    assert "Restart dashboard, then refresh" in html
    assert "No recordings found" in js
    assert "timestamp_s and bfi_l1" in js
    assert "stress-alert/data/" in js
    assert "Could not list recordings" in js
    assert "Restart dashboard, then refresh" in js
    assert "AbortSignal.timeout" not in js
    assert "new AbortController()" in js
    assert "controller.abort()" in js
    assert "String(err" in js
    assert "Restart the dashboard on this branch and hard-refresh" not in js
    assert "if (populated) return" in js
    assert "/api/replay/sessions" in js


def test_list_recordings_includes_bundled_scan(tmp_path):
    listed = list_recordings(tmp_path, ROOT / "data")
    paths = {item["path"] for item in listed}
    assert str(SAMPLE.resolve()) in paths
    row = next(item for item in listed if item["path"] == str(SAMPLE.resolve()))
    assert row["duration_s"] > 20
    assert row["frames"] is None
    names = {Path(item["path"]).name for item in listed}
    assert "sample_scan.csv" in names
    assert "synthetic_scan.csv" in names


def test_seek_publishes_bfi_frames_through_gate():
    hub = Hub()
    gate = LiveGate()
    published: list[dict] = []

    def publish(frames):
        published.extend(frames)
        hub.publish(frames)

    engine = ReplayEngine()
    engine.load(SAMPLE)
    result = engine.seek(5.0, gate=gate, publish=publish)
    assert result["position_s"] == 5.0
    assert result["published_frames"] > 0
    types = {frame["type"] for frame in published}
    assert "bfi" in types and "bvi" in types
    assert any(frame["type"] == "status" and frame["source"] == "replay" for frame in published)
    bfi_times = [frame["t"] for frame in published if frame["type"] == "bfi"]
    assert bfi_times == sorted(bfi_times)


@pytest.fixture
def app(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    scan = data / "sample_scan.csv"
    scan.write_bytes(SAMPLE.read_bytes())
    return create_app(sessions_dir=tmp_path / "sessions", lsl_markers=False)


def test_replay_api_list_load_seek(app, tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "scan.csv").write_bytes(SAMPLE.read_bytes())
    client = TestClient(app)
    listed = client.get("/api/replay/sessions").json()["sessions"]
    assert any("scan.csv" in item["path"] for item in listed)
    path = next(item["path"] for item in listed if item["path"].endswith("scan.csv"))
    with client.websocket_connect("/ws") as browser:
        loaded = client.post("/api/replay/load", json={"path": path}).json()
        assert loaded["active"] and loaded["duration_s"] > 0
        batch = browser.receive_json()
        assert any(frame["type"] == "bfi" for frame in batch)
        seek = client.post("/api/replay/seek", json={"t_s": 10.0}).json()
        assert seek["position_s"] == 10.0
        assert seek["published_frames"] > 0
        batch2 = browser.receive_json()
        assert any(frame["type"] == "bvi" for frame in batch2)
    assert not client.post("/api/replay/stop").json()["active"]


def test_demo_start_writes_session_scan_copy(app):
    client = TestClient(app)
    client.post("/api/demo/start", json={})
    root = app.state.logger.root
    sessions = list(root.glob("*"))
    assert sessions
    session_dir = sessions[0]
    assert (session_dir / "scan.csv").is_file()
    meta = json.loads((session_dir / "meta.json").read_text())
    assert meta.get("scan_csv") == "scan.csv"


def test_meta_only_sessions_still_list_data_scans(tmp_path):
    sessions = tmp_path / "sessions"
    folder = sessions / "20261024-152354_anon"
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(
        '{"session_id": "20261024-152354_anon", "subject_id": "anon"}'
    )
    (folder / "events.csv").write_text("t,wall_time,session_id,phase,source\n")
    data = tmp_path / "data"
    data.mkdir()
    (data / "sample_scan.csv").write_text("frame_id,timestamp_s,bfi_l1\n1,0,1\n2,1.25,1\n")
    (data / "raymond_locked_scan.csv").write_text(
        "frame_id,timestamp_s,bfi_l1\n1,0,2\n9,not-a-time,2\n8,4.5,2\n"
    )
    app = create_app(sessions_dir=sessions, data_dir=data, lsl_markers=False)
    listed = TestClient(app).get("/api/replay/sessions").json()["sessions"]
    names = {Path(item["path"]).name for item in listed}
    assert names == {"sample_scan.csv", "raymond_locked_scan.csv"}
    locked = next(item for item in listed if item["path"].endswith("raymond_locked_scan.csv"))
    assert locked["duration_s"] == 4.5


def test_session_stop_links_device_scan_into_the_session(app, tmp_path):
    scans = tmp_path / "sessions" / "device-scans"
    scans.mkdir(parents=True)
    source = scans / "abc_anon.csv"
    source.write_text("frame_id,timestamp_s,bfi_l1\n1,0.0,1\n2,3.5,1\n")
    assert newest_scan_csv(scans) == source
    client = TestClient(app)
    client.post("/api/session/start", json={"subject_id": "anon"})
    app.state.device.scan_started_at = 0
    client.post("/api/session/stop")
    session_dirs = [
        path
        for path in (tmp_path / "sessions").iterdir()
        if path.is_dir() and path.name != "device-scans"
    ]
    assert len(session_dirs) == 1
    linked = session_dirs[0] / "scan.csv"
    assert linked.is_file()
    assert linked.read_text() == source.read_text()
    again = list_recordings(tmp_path / "sessions")
    assert any(item["path"].endswith("scan.csv") for item in again)


def test_ensure_session_scan_copy_is_idempotent(tmp_path):
    session_dir = tmp_path / "20261025_demo"
    session_dir.mkdir()
    first = ensure_session_scan_copy(session_dir, SAMPLE)
    second = ensure_session_scan_copy(session_dir, SAMPLE)
    assert first == second
    assert first.stat().st_size == SAMPLE.stat().st_size
