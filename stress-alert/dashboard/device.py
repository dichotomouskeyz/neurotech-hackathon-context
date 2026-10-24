"""Find, connect, and stream from the Openwater Open-Motion device.

``DeviceManager`` wraps ``openmotion-sdk``'s ``MotionInterface``. Connecting starts
the SDK's own USB/serial discovery and hotplug monitor; a scan streams live BFI/BVI
through a pipeline sink on the SDK's ``live`` channel. Frames go to the dashboard hub
on the shared LSL clock.

The SDK runs its connection monitor and scan worker on its own threads, so every
hub publish is marshalled onto the event loop with ``call_soon_threadsafe``.

For research. Starting a scan turns the laser on through the SDK's standard scan
path only; nothing here changes laser parameters or safety outputs.
"""

import asyncio
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dashboard import clock

SCAN_SECONDS = 3600  # upper bound; the operator stops the scan from the dashboard
SIDES = ("left", "right")

Emit = Callable[[list[dict[str, Any]]], None]


class DeviceError(RuntimeError):
    """A device action that cannot run, with a message an operator can act on."""


def _default_factory(data_dir: Path):
    """Import the SDK lazily so the dashboard runs without it installed."""
    try:
        import omotion
        from omotion import MotionInterface, usb_backend
        from omotion.ScanWorkflow import ScanRequest
    except ImportError as exc:
        raise DeviceError(
            "openmotion-sdk is not installed in this environment. Run uv sync."
        ) from exc
    if sys.platform != "win32" and usb_backend.get_libusb1_backend() is None:
        raise DeviceError("libusb was not found. On macOS run: brew install libusb")
    data_dir.mkdir(parents=True, exist_ok=True)
    iface = MotionInterface(data_dir=str(data_dir), operator_id="stress-alert")
    return iface, ScanRequest, omotion.__version__


def _value(x: float) -> float | None:
    return float(x) if math.isfinite(x) else None


class LiveSink:
    """SDK pipeline sink: turns ``live`` FrameBatches into ``bfi`` and ``bvi`` frames.

    Live batches are row-addressed: each row is one camera on one side
    (``side_ids[i]``, ``cam_ids[i]``) for one capture (``abs_frame_ids[i]``). The
    sink keeps the latest value per camera and emits one 16-camera frame per
    capture when the next capture begins. Batch timestamps start at 0 when the
    scan starts; ``t0`` maps them onto the shared clock.
    """

    channels = {"live"}

    def __init__(self, publish: Emit, now: Callable[[], float] = clock.now) -> None:
        self._publish = publish
        self._now = now
        self._t0 = 0.0
        self._current: int | None = None
        self._t: float = 0.0
        self._bfi = [[None] * 8, [None] * 8]
        self._bvi = [[None] * 8, [None] * 8]

    def on_scan_start(self, meta: Any) -> None:
        self._t0 = self._now()
        self._current = None

    def consume(self, channel: str, batch: Any) -> None:
        if channel != "live" or getattr(batch, "bfi_live", None) is None:
            return
        frames: list[dict[str, Any]] = []
        n = batch.bfi_live.shape[0]
        side_ids = getattr(batch, "side_ids", None)
        cam_ids = getattr(batch, "cam_ids", None)
        abs_ids = getattr(batch, "abs_frame_ids", None)
        types = getattr(batch, "frame_type", None)
        for i in range(n):
            if types is not None and str(types[i]) == "stale":
                continue
            capture = int(abs_ids[i]) if abs_ids is not None else i
            if self._current is not None and capture != self._current:
                frames.extend(self._snapshot())
            self._current = capture
            self._t = self._t0 + float(batch.timestamp_s[i])
            if side_ids is not None and cam_ids is not None:
                cells = [(int(side_ids[i]), int(cam_ids[i]))]
            else:
                cells = [(s, c) for s in range(2) for c in range(8)]
            for side, cam in cells:
                if 0 <= side < 2 and 0 <= cam < 8:
                    self._bfi[side][cam] = _value(float(batch.bfi_live[i, side, cam]))
                    self._bvi[side][cam] = _value(float(batch.bvi_live[i, side, cam]))
        if frames:
            self._publish(frames)

    def on_complete(self) -> None:
        if self._current is not None:
            self._publish(self._snapshot())
        self._current = None

    def _snapshot(self) -> list[dict[str, Any]]:
        return [
            {"type": metric, "t": self._t, "left": list(values[0]), "right": list(values[1])}
            for metric, values in (("bfi", self._bfi), ("bvi", self._bvi))
        ]


class DeviceManager:
    def __init__(
        self,
        emit: Emit,
        data_dir: Path,
        factory: Callable[[Path], tuple[Any, Any, str]] = _default_factory,
        now: Callable[[], float] = clock.now,
    ) -> None:
        self._emit = emit
        self._data_dir = data_dir
        self._factory = factory
        self._now = now
        self._loop: asyncio.AbstractEventLoop | None = None
        self._iface: Any = None
        self._scan_request: Any = None
        self._poller: asyncio.Task[None] | None = None
        self.sdk_version = ""
        self.console = self.left = self.right = False
        self.scanning = False
        self.error = ""

    # State

    def state(self) -> dict[str, Any]:
        return {
            "type": "device",
            "t": self._now(),
            "connected": self._iface is not None,
            "console": self.console,
            "left": self.left,
            "right": self.right,
            "scanning": self.scanning,
            "sdk_version": self.sdk_version,
            "error": self.error,
        }

    def _publish(self, frames: list[dict[str, Any]]) -> None:
        """Thread-safe publish: SDK threads call this too."""
        if self._loop is None:
            self._emit(frames)
        else:
            self._loop.call_soon_threadsafe(self._emit, frames)

    def _emit_state(self) -> None:
        self._publish([self.state()])

    def _refresh(self) -> bool:
        """Re-read connection flags; return True if anything changed."""
        before = (self.console, self.left, self.right, self.scanning)
        if self._iface is not None:
            flags = self._iface.is_device_connected()
            self.console, self.left, self.right = (bool(x) for x in flags)
            self.scanning = bool(self._iface.scan_workflow.running) if self.scanning else False
        return before != (self.console, self.left, self.right, self.scanning)

    def _found_message(self) -> str:
        if not self.console:
            return "No Open-Motion console found. Check power and the Openwater USB cable."
        missing = [side for side, ok in zip(SIDES, (self.left, self.right), strict=True) if not ok]
        if missing:
            return f"Console found; {' and '.join(missing)} sensor not connected."
        return ""

    # Actions (blocking SDK calls; the app runs them in a worker thread)

    def connect(self) -> dict[str, Any]:
        if self._iface is None:
            try:
                iface, request_type, version = self._factory(self._data_dir)
                iface.start(wait=True, wait_timeout=3.0)
            except DeviceError as exc:
                self.error = str(exc)
                self._emit_state()
                raise
            except Exception as exc:  # SDK and USB failures arrive as many types
                self.error = f"Could not start the Open-Motion interface: {exc}"
                self._emit_state()
                raise DeviceError(self.error) from exc
            self._iface, self._scan_request, self.sdk_version = iface, request_type, version
        self._refresh()
        self.error = self._found_message()
        self._emit_state()
        return self.state()

    def disconnect(self) -> dict[str, Any]:
        if self._iface is not None:
            if self.scanning:
                self.stop_scan()
            self._iface.stop()
        self._iface = None
        self.console = self.left = self.right = self.scanning = False
        self.error = ""
        self._emit_state()
        return self.state()

    def start_scan(self, subject_id: str = "") -> dict[str, Any]:
        if self._iface is None:
            raise DeviceError("Connect the device first.")
        self._refresh()
        if not self.console or not (self.left or self.right):
            raise DeviceError(self._found_message() or "No sensor connected.")
        if self.scanning:
            return self.state()

        def on_error(exc: BaseException) -> None:
            self.scanning = False
            self.error = f"Scan stopped: {exc}"
            self._emit_state()

        request = self._scan_request(
            subject_id=subject_id or "stress-alert",
            duration_sec=SCAN_SECONDS,
            left_camera_mask=0xFF if self.left else 0x00,
            right_camera_mask=0xFF if self.right else 0x00,
            sinks=[LiveSink(self._publish, self._now)],
            on_error=on_error,
        )
        if not self._iface.start_scan(request):
            reason = getattr(self._iface.scan_workflow, "last_scan_error", None)
            self.error = f"The SDK refused to start the scan: {reason or 'no reason given'}"
            self._emit_state()
            raise DeviceError(self.error)
        self.scanning = True
        self.error = ""
        self._emit_state()
        return self.state()

    def stop_scan(self) -> dict[str, Any]:
        if self._iface is not None and self.scanning:
            self._iface.cancel_scan()
        self.scanning = False
        self._emit_state()
        return self.state()

    # Hotplug: re-read connection flags while connected so a replugged sensor shows up

    def start_polling(self, loop: asyncio.AbstractEventLoop, interval_s: float = 1.0) -> None:
        self._loop = loop

        async def poll() -> None:
            while True:
                await asyncio.sleep(interval_s)
                if self._iface is not None and self._refresh():
                    self.error = self._found_message()
                    self._emit([self.state()])

        self._poller = loop.create_task(poll())

    def shutdown(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
        if self._iface is not None:
            try:
                self.disconnect()
            except Exception:  # best effort on server shutdown
                pass
