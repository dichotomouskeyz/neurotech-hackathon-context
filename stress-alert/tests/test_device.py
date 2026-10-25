from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app
from dashboard.device import DeviceError, DeviceManager, LiveSink


class FakeRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeInterface:
    """Stands in for omotion.MotionInterface."""

    def __init__(self, flags=(True, True, True), accept_scan=True):
        self.flags = flags
        self.accept_scan = accept_scan
        self.started = False
        self.stopped = False
        self.request = None
        self.canceled = False
        self.scan_workflow = SimpleNamespace(running=False, last_scan_error="sensor busy")

    def start(self, wait=True, wait_timeout=2.0):
        self.started = True

    def stop(self):
        self.stopped = True

    def is_device_connected(self):
        return self.flags

    def start_scan(self, request):
        self.request = request
        self.scan_workflow.running = self.accept_scan
        return self.accept_scan

    def cancel_scan(self, **kwargs):
        self.canceled = True
        self.scan_workflow.running = False


def manager(tmp_path, iface):
    frames = []
    mgr = DeviceManager(frames.extend, tmp_path, factory=lambda d: (iface, FakeRequest, "1.12.0"))
    mgr.frames = frames
    return mgr


def test_connect_finds_console_and_both_sensors(tmp_path):
    iface = FakeInterface()
    mgr = manager(tmp_path, iface)
    state = mgr.connect()
    assert iface.started
    assert state["connected"] and state["console"] and state["left"] and state["right"]
    assert state["error"] == "" and state["sdk_version"] == "1.12.0"
    assert mgr.frames[-1]["type"] == "device"


def test_connect_without_console_says_what_to_check(tmp_path):
    mgr = manager(tmp_path, FakeInterface(flags=(False, False, False)))
    state = mgr.connect()
    assert state["connected"] and not state["console"]
    assert "No Open-Motion console found" in state["error"]
    with pytest.raises(DeviceError):
        mgr.start_scan("s1")


def test_missing_side_is_named_and_masked_off(tmp_path):
    iface = FakeInterface(flags=(True, True, False))
    mgr = manager(tmp_path, iface)
    assert mgr.connect()["error"] == "Console found; right sensor not connected."
    mgr.start_scan("jb")
    assert iface.request.left_camera_mask == 0xFF
    assert iface.request.right_camera_mask == 0x00
    assert iface.request.subject_id == "jb"
    assert isinstance(iface.request.sinks[0], LiveSink)


def test_sdk_problem_is_reported_not_crashed(tmp_path):
    def broken(_):
        raise DeviceError("libusb was not found. On macOS run: brew install libusb")

    frames = []
    mgr = DeviceManager(frames.extend, tmp_path, factory=broken)
    with pytest.raises(DeviceError):
        mgr.connect()
    assert "brew install libusb" in mgr.state()["error"]
    assert not mgr.state()["connected"]


def test_scan_start_stop_and_refusal(tmp_path):
    iface = FakeInterface()
    mgr = manager(tmp_path, iface)
    with pytest.raises(DeviceError):
        mgr.start_scan()
    mgr.connect()
    assert mgr.start_scan()["scanning"]
    assert not mgr.stop_scan()["scanning"] and iface.canceled

    refusing = FakeInterface(accept_scan=False)
    mgr2 = manager(tmp_path, refusing)
    mgr2.connect()
    with pytest.raises(DeviceError, match="sensor busy"):
        mgr2.start_scan()


def test_disconnect_stops_interface(tmp_path):
    iface = FakeInterface()
    mgr = manager(tmp_path, iface)
    mgr.connect()
    mgr.start_scan()
    state = mgr.disconnect()
    assert iface.stopped and iface.canceled
    assert not state["connected"] and not state["scanning"]


def live_batch(rows, quality=None, low_light=None):
    """rows: (abs_frame_id, side, cam, t, bfi, bvi, frame_type)."""
    n = len(rows)
    bfi = np.full((n, 2, 8), np.nan)
    bvi = np.full((n, 2, 8), np.nan)
    for i, (_, side, cam, _, b, v, _) in enumerate(rows):
        bfi[i, side, cam] = b
        bvi[i, side, cam] = v
    batch = SimpleNamespace(
        bfi_live=bfi,
        bvi_live=bvi,
        side_ids=np.array([r[1] for r in rows]),
        cam_ids=np.array([r[2] for r in rows]),
        abs_frame_ids=np.array([r[0] for r in rows]),
        timestamp_s=np.array([r[3] for r in rows]),
        frame_type=np.array([r[6] for r in rows]),
    )
    if quality is not None:
        batch.quality = np.array(quality)
    if low_light is not None:
        batch.low_light_rt = low_light
    return batch


def test_live_sink_assembles_one_frame_per_capture():
    published = []
    sink = LiveSink(published.extend, now=lambda: 1000.0)
    sink.on_scan_start(None)
    sink.consume(
        "live",
        live_batch(
            [
                (10, 0, 0, 0.0, 2.1, 6.0, "light"),
                (10, 1, 7, 0.0, 2.4, 6.3, "light"),
                (10, 0, 3, 0.0, 9.9, 9.9, "stale"),  # skipped
                (11, 0, 0, 0.025, 2.2, 6.1, "light"),
            ]
        ),
    )
    assert [f["type"] for f in published] == ["bfi", "bvi"]
    bfi = published[0]
    assert bfi["t"] == pytest.approx(1000.0)
    assert bfi["left"][0] == pytest.approx(2.1) and bfi["right"][7] == pytest.approx(2.4)
    assert bfi["left"][3] is None  # stale row ignored, unseen camera is null
    sink.on_complete()
    assert published[-2]["left"][0] == pytest.approx(2.2)
    assert published[-2]["t"] == pytest.approx(1000.025)


def test_interleaved_sides_keep_40_hz_and_a_100_bpm_pulse():
    """Left and right share a capture id. The sink must not stretch time 2x.

    Firmware timestamps are one light frame apart (0.025 s). A 100 bpm tone
    on that cadence stays near 100. The half-rate failure is spectral.
    """
    import math

    from dashboard.live_gate import LiveGate

    published = []
    gate = LiveGate()

    def emit(frames):
        published.extend(frames)
        published.extend(gate.observe(frames))

    sink = LiveSink(emit, now=lambda: 1000.0)
    sink.on_scan_start(None)
    for index in range(16 * 40):
        t = index / 40.0
        bfi = 2.2 + 0.25 * math.sin(2 * math.pi * (100.0 / 60.0) * t)
        # Same capture id on both sides. Right stamp is a fraction of a millisecond later.
        sink.consume(
            "live",
            live_batch(
                [
                    (index + 10, 0, 0, t, bfi, 5.0, "light"),
                    (index + 10, 1, 0, t + 0.0004, bfi, 5.0, "light"),
                ]
            ),
        )
    sink.on_complete()
    times = [frame["t"] for frame in published if frame["type"] == "bfi"]
    assert len(times) >= 600
    assert float(np.median(np.diff(times))) == pytest.approx(0.025, abs=0.002)
    hrs = [frame for frame in published if frame["type"] == "hr"]
    assert hrs
    assert hrs[-1]["bpm"] == pytest.approx(100, abs=3)


def test_live_sink_skips_dark_and_warmup_rows():
    published = []
    sink = LiveSink(published.extend, now=lambda: 1000.0)
    sink.on_scan_start(None)
    sink.consume(
        "live",
        live_batch(
            [
                (10, 0, 0, 0.0, 2.0, 6.0, "light"),
                (10, 0, 1, 0.0, 50.0, 50.0, "dark"),
                (10, 0, 2, 0.0, 40.0, 40.0, "warmup"),
                (11, 0, 0, 0.025, 2.1, 6.1, "light"),
            ]
        ),
    )
    bfi = next(frame for frame in published if frame["type"] == "bfi")
    assert bfi["left"][0] == pytest.approx(2.0)
    assert bfi["left"][1] is None
    assert bfi["left"][2] is None


def test_live_sink_frames_are_scored_by_the_gate(tmp_path):
    """BFI, BVI, and DN contact from the scan sink are what the stress label reads."""
    from dashboard.live_gate import LiveGate

    published = []
    gate = LiveGate(stress_hold_s=0.4)

    def emit(frames):
        published.extend(frames)
        published.extend(gate.observe(frames))

    iface = FakeInterface()
    mgr = DeviceManager(
        emit, tmp_path, factory=lambda d: (iface, FakeRequest, "1.12.0"), now=lambda: 1000.0
    )
    mgr.connect()
    mgr.start_scan("scan")
    sink = iface.request.sinks[0]
    emit(
        [
            {
                "type": "session",
                "t": 1000.0,
                "active": True,
                "session_id": "s1",
                "subject_id": "scan",
                "phase": None,
                "loop": "off",
                "loop_cue": "",
            }
        ]
    )
    emit(
        [
            {
                "type": "phase",
                "t": 1000.0,
                "session_id": "s1",
                "phase": "baseline",
                "source": "manual",
            }
        ]
    )
    sink.on_scan_start(None)

    def push(frame_id, t, bfi):
        batch = live_batch(
            [
                (frame_id, 0, 0, t, bfi, 5.0, "light"),
                (frame_id + 1, 0, 0, t + 0.01, bfi, 5.0, "light"),
            ]
        )
        light = np.full((2, 2, 8), np.nan)
        light[:, 0, 0] = 30.0  # above the light threshold; timestamp "ok" is not contact
        batch.mean_dc_rt = light
        sink.consume("live", batch)

    for i in range(6):
        push(i * 2, i * 0.3, 2.0)
    emit([{"type": "phase", "t": 1005.0, "session_id": "s1", "phase": "hold", "source": "manual"}])
    push(30, 8.0, 2.8)
    push(34, 8.6, 2.8)
    assert any(
        frame["type"] == "cq" and frame["left"] == pytest.approx(1.0) and frame["right"] is None
        for frame in published
    )
    assert any(
        frame["type"] == "stress" and frame["alert"] and "BFI" in frame["reason"]
        for frame in published
    )
    assert gate.challenge_done(0.0)


def test_quality_label_ok_does_not_invent_perfect_cq():
    """Pipeline quality 'ok' is a timestamp flag, not contact. It must not score 1."""
    published = []
    sink = LiveSink(published.extend, now=lambda: 1000.0)
    sink.on_scan_start(None)
    batch = live_batch(
        [
            (1, 0, 0, 0.0, 2.0, 6.0, "light"),
            (2, 0, 0, 0.025, 2.1, 6.1, "light"),
        ]
    )
    batch.quality = np.array(["ok", "ok"])
    sink.consume("live", batch)
    sink.on_complete()
    assert [f["type"] for f in published] == ["bfi", "bvi", "bfi", "bvi"]


def test_contact_dn_scores_and_drops_when_light_falls():
    published = []
    sink = LiveSink(published.extend, now=lambda: 0.0)
    sink.on_scan_start(None)

    def batch(capture, light_dn):
        frame = live_batch([(capture, 0, 0, 0.0, 2.0, 6.0, "light")])
        light = np.full((1, 2, 8), np.nan)
        dark = np.full((1, 2, 8), np.nan)
        light[0, 0, 0] = light_dn
        dark[0, 0, 0] = 1.0  # inside the ambient threshold
        frame.mean_dc_rt = light
        frame.subtracted_mean = dark
        return frame

    sink.consume("live", batch(1, 30.0))
    sink.consume("live", batch(2, 7.5))
    sink.on_complete()
    cqs = [f for f in published if f["type"] == "cq"]
    assert len(cqs) == 2
    assert cqs[0]["left"] == pytest.approx(1.0)
    assert cqs[0]["right"] is None
    assert cqs[1]["left"] == pytest.approx(0.5)
    assert cqs[1]["right"] is None


def test_unlit_camera_scores_zero_and_good_dark_alone_does_not():
    published = []
    sink = LiveSink(published.extend, now=lambda: 0.0)
    sink.on_scan_start(None)
    frame = live_batch(
        [
            (1, 0, 1, 0.0, 2.0, 6.0, "dark"),
            (2, 0, 2, 0.025, 2.0, 6.0, "light"),
        ]
    )
    dark = np.full((2, 2, 8), np.nan)
    dark[0, 0, 1] = 1.0  # within threshold, no light yet: not a pass
    frame.subtracted_mean = dark
    low = np.zeros((2, 2, 8), dtype=bool)
    low[1, 0, 2] = True
    frame.low_light_rt = low
    sink.consume("live", frame)
    sink.on_complete()
    cqs = [f for f in published if f["type"] == "cq"]
    assert len(cqs) == 1
    assert cqs[0]["left"] == pytest.approx(0.0)
    assert cqs[0]["right"] is None


def test_ambient_dark_lowers_contact_without_a_light_sample():
    published = []
    sink = LiveSink(published.extend, now=lambda: 0.0)
    sink.on_scan_start(None)
    frame = live_batch(
        [
            (1, 1, 4, 0.0, 2.0, 6.0, "dark"),
            (2, 1, 4, 0.025, 2.0, 6.0, "light"),
        ]
    )
    dark = np.full((2, 2, 8), np.nan)
    dark[0, 1, 4] = 6.0  # twice the 3.0 DN ceiling -> 0
    frame.subtracted_mean = dark
    sink.consume("live", frame)
    sink.on_complete()
    cqs = [f for f in published if f["type"] == "cq"]
    assert cqs
    assert all(f["left"] is None and f["right"] == pytest.approx(0.0) for f in cqs)


def test_live_sink_ignores_other_channels():
    published = []
    sink = LiveSink(published.extend, now=lambda: 0.0)
    sink.consume("final", object())
    sink.consume("live", SimpleNamespace(bfi_live=None))
    assert published == []


def test_device_api_streams_scan_frames_to_browser(tmp_path):
    iface = FakeInterface()
    app = create_app(
        sessions_dir=tmp_path,
        lsl_markers=False,
        device_factory=lambda d: (iface, FakeRequest, "1.12.0"),
    )
    with TestClient(app) as client, client.websocket_connect("/ws") as browser:
        assert client.post("/api/device/scan/start").status_code == 409
        assert client.post("/api/device/connect").json()["console"]
        assert client.post("/api/device/scan/start").json()["scanning"]
        sink = iface.request.sinks[0]
        sink.on_scan_start(None)
        sink.consume("live", live_batch([(1, 0, 0, 0.0, 2.0, 6.0, "light")]))
        sink.on_complete()
        seen = []
        while not any(f["type"] == "bfi" for f in seen):
            seen.extend(browser.receive_json())
        bfi = next(f for f in seen if f["type"] == "bfi")
        assert bfi["left"][0] == pytest.approx(2.0)
        assert client.post("/api/device/scan/stop").json()["scanning"] is False
        assert client.get("/api/device").json()["connected"]
