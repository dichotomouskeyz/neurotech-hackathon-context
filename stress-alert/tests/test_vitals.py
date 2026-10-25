import json
import math

import pytest
from fastapi.testclient import TestClient

from dashboard import dev_feed
from dashboard.app import create_app
from dashboard.vitals import HeartRateEstimator


def pulse_frames(bpm, seconds, rate_hz=40.0, start=100.0):
    """A clean sine pulse on every camera. A test fixture, not app data."""
    frames = []
    for i in range(int(seconds * rate_hz)):
        t = start + i / rate_hz
        v = 2.2 + 0.2 * math.sin(2 * math.pi * (bpm / 60.0) * t)
        frames.append({"type": "bfi", "t": t, "left": [v] * 8, "right": [v] * 8})
    return frames


def test_sine_pulse_gives_its_rate():
    published = []
    est = HeartRateEstimator(published.extend)
    est.feed(pulse_frames(72, 12))
    frame = est.tick()
    assert frame is not None and published == [frame]
    assert frame["bpm"] == pytest.approx(72, abs=2)
    assert frame["source"] == "optical" and frame["confidence"] > 0.9
    assert frame["window_s"] <= est.window_s


def test_short_buffer_publishes_nothing():
    published = []
    est = HeartRateEstimator(published.extend)
    est.feed(pulse_frames(72, 5))
    assert est.tick() is None and published == []


def test_flat_signal_is_not_guessed():
    published = []
    est = HeartRateEstimator(published.extend)
    flat = [
        {"type": "bfi", "t": 100 + i / 40, "left": [2.0] * 8, "right": [2.0] * 8}
        for i in range(480)
    ]
    est.feed(flat)
    assert est.tick() is None and published == []


def test_window_rolls_and_ignores_out_of_order_and_other_frames():
    est = HeartRateEstimator(lambda frames: None, window_s=12)
    est.feed(pulse_frames(72, 30))
    est.feed([{"type": "bfi", "t": 0.0, "left": [9.0] * 8, "right": [9.0] * 8}])  # old
    est.feed([{"type": "hr", "t": 200.0, "source": "optical", "bpm": 70}])
    assert est._t[-1] - est._t[0] <= 12
    assert est._t[-1] < 200.0


def test_null_cameras_are_skipped():
    est = HeartRateEstimator(lambda frames: None)
    frames = pulse_frames(80, 12)
    for f in frames:
        f["left"][3] = None
        f["right"] = [None] * 8  # one side fully dark
    est.feed(frames)
    frame = est.tick()
    assert frame is not None and frame["bpm"] == pytest.approx(80, abs=2)


def test_openwater_sample_scan_reads_about_77_bpm():
    rows = dev_feed.load_rows()
    est = HeartRateEstimator(lambda frames: None, window_s=30)
    frames = []
    for i, row in enumerate(rows):
        frames.extend(f for f in dev_feed.frames_for(row, t=i / 40.0) if f["type"] == "bfi")
    est.feed(frames)
    frame = est.tick()
    assert frame is not None and frame["bpm"] == pytest.approx(77, abs=3)


def test_app_publishes_hr_frames_to_the_browser(tmp_path):
    app = create_app(sessions_dir=tmp_path, lsl_markers=False)
    frames = pulse_frames(66, 12)
    last_t = frames[-1]["t"]
    with TestClient(app) as client, client.websocket_connect("/ws") as browser:
        with client.websocket_connect("/ws/ingest?source=test") as producer:
            producer.send_text(json.dumps(frames))
            seen = []
            # Wait until the server has published the last frame, then estimate.
            while not any(f.get("type") == "bfi" and f["t"] == last_t for f in seen):
                seen.extend(browser.receive_json())
            frame = app.state.heart_rate.tick()  # the app also ticks every second
        assert frame["bpm"] == pytest.approx(66, abs=2)
        while not any(f.get("type") == "hr" for f in seen):
            seen.extend(browser.receive_json())
        hr = next(f for f in seen if f.get("type") == "hr")
        assert hr["confidence"] > 0.9


async def test_replay_stamps_frames_on_an_even_cadence(monkeypatch):
    sent = []

    class FakeSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def send(self, text):
            sent.append(json.loads(text))
            if len(sent) == 3:
                raise ConnectionError("stop")

    monkeypatch.setattr(dev_feed, "connect", lambda url: FakeSocket())
    with pytest.raises(ConnectionError):
        await dev_feed.run("ws://test")
    ts = [f["t"] for batch in sent for f in batch if f["type"] == "bfi"]
    steps = [b - a for a, b in zip(ts, ts[1:], strict=False)]
    assert all(step == pytest.approx(1 / dev_feed.RATE_HZ) for step in steps)
