"""Find, connect, and stream from the Openwater Open-Motion device.

``DeviceManager`` wraps ``openmotion-sdk``'s ``MotionInterface``. Connecting starts
the SDK's own USB/serial discovery and hotplug monitor. It does not power cameras
or write laser registers. Start scan writes the SDK's bundled laser-driver
registers (``apply_laser_power``, the bloodflow console-connect step), powers the
scan mask, programs camera FPGAs and sensor registers
(``start_configure_camera_sensors``, about 2 minutes for all 16 cameras), requires
``enable_camera`` to succeed, then starts the SDK scan. Frames are live BFI/BVI
through a pipeline sink on the SDK's ``live`` channel, published to the dashboard
hub on the shared LSL clock.

The SDK runs its connection monitor and scan worker on its own threads, so every
hub publish is marshalled onto the event loop with ``call_soon_threadsafe``.

For research. The laser write uses the SDK's locked baseline and does not edit
pulse widths or load the interlock-trip set. The trigger still uses the SDK
default, which turns the laser on.
"""

import asyncio
import math
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dashboard import clock
from features.cq_score import DEFAULT_DARK_MAX_DN, DEFAULT_LIGHT_MIN_DN, cq_score

SCAN_SECONDS = 3600  # upper bound; the operator stops the scan from the dashboard
SIDES = ("left", "right")
# All 8 cameras on a module. Power, the enable check, and ScanRequest use this
# same mask. 0x66 (middle) is the older narrower default; keep All.
CAMERA_MASK_ALL = 0xFF
# Bloodflow connect sleeps this long after enable_camera_power before the next command.
CAMERA_POWER_SETTLE_S = 0.5
# Shown while apply_laser_power writes the bundled driver registers. That I2C
# pass is seconds, not the multi-minute FPGA program that follows.
LASER_SETUP_STATUS = "Writing laser driver registers. Cold start, before camera setup."
# ScanWorkflow enables cameras on its worker after start_scan returns. Each
# enable waits up to 1.5 s, so two sides plus frame-sync setup fit in this window.
CAMERA_ENABLE_WAIT_S = 8.0
# FPGA programming is about 14 s per camera. The two modules run in parallel,
# so mask 0xFF (8 cameras a side) is about 2 minutes. The bloodflow flash
# watchdog is 250 s; this waits the same order of time before failing.
CAMERA_CONFIGURE_TIMEOUT_S = 240.0
# A SRAM load that returns faster than this did not program the camera. The
# SDK's program_fpga waits on the firmware (timeout 60 s) and is about 14 s.
CAMERA_PROGRAM_MIN_S = 2.0
# enable_camera only ACKs the stream command. Wait this long for a finite
# BFI or BVI value before treating the scan as running.
CAMERA_FRAME_WAIT_S = 12.0
FRAME_WAIT_STATUS = "Waiting for the first BFI/BVI frame."
# get_camera_status bits: 0 READY, 1 firmware programmed, 2 registers configured.
CAMERA_STATUS_FLASHED = (1 << 0) | (1 << 1) | (1 << 2)

Emit = Callable[[list[dict[str, Any]]], None]


class DeviceError(RuntimeError):
    """A device action that cannot run, with a message an operator can act on."""


def _mask_label(mask: int) -> str:
    return f"0x{mask:02X}"


def _camera_call(sensor: Any, method: str, mask: int) -> bool:
    fn = getattr(sensor, method, None)
    if not callable(fn):
        raise DeviceError(f"Open-Motion SDK is missing {method}; cannot start a scan.")
    try:
        return bool(fn(mask))
    except Exception as exc:
        raise DeviceError(f"{method} on mask {_mask_label(mask)} failed: {exc}") from exc


def _configure_request(left_mask: int, right_mask: int) -> Any:
    """Same object the bloodflow app passes to ``start_configure_camera_sensors``."""
    try:
        from omotion.ScanWorkflow import ConfigureRequest
    except ImportError as exc:
        raise DeviceError(
            "Open-Motion SDK is missing ConfigureRequest; cannot start a scan."
        ) from exc
    return ConfigureRequest(
        left_camera_mask=left_mask,
        right_camera_mask=right_mask,
        power_off_unused_cameras=False,
    )


def _cancel_configure(iface: Any) -> None:
    cancel = getattr(iface, "cancel_configure_camera_sensors", None)
    if not callable(cancel):
        return
    try:
        cancel()
    except Exception:
        pass


def _disable_cameras(enabled: list[tuple[Any, int]]) -> None:
    """Best-effort stream off. A failed disable must not hide an enable error."""
    for sensor, mask in enabled:
        fn = getattr(sensor, "disable_camera", None)
        if not callable(fn):
            continue
        try:
            fn(mask)
        except Exception:
            pass


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


def _cell(batch: Any, name: str, index: int, side: int, cam: int) -> float | None:
    arr = getattr(batch, name, None)
    if arr is None:
        return None
    try:
        return _value(float(arr[index, side, cam]))
    except (IndexError, TypeError, ValueError):
        return None


def _flag(batch: Any, name: str, index: int, side: int, cam: int) -> bool:
    arr = getattr(batch, name, None)
    if arr is None:
        return False
    try:
        return bool(arr[index, side, cam])
    except (IndexError, TypeError, ValueError):
        return False


def _light_term(light: float) -> float:
    """Same light term as ``cq_score``'s graded contact, without inventing a dark pass."""
    if light >= DEFAULT_LIGHT_MIN_DN:
        return 1.0
    return max(0.0, light / DEFAULT_LIGHT_MIN_DN)


def _dark_term(dark: float) -> float:
    if dark <= DEFAULT_DARK_MAX_DN:
        return 1.0
    return max(0.0, 1.0 - (dark - DEFAULT_DARK_MAX_DN) / DEFAULT_DARK_MAX_DN)


def _camera_contact(
    light: float | None, dark: float | None, unlit: bool
) -> float | dict[str, float] | None:
    """One camera's contact input for ``cq_score``, or None when nothing was measured.

    The pipeline ``quality`` string is not contact. ``ok`` only means the
    timestamp was left alone, so it must not become a score of 1.
    """
    if unlit:
        return 0.0
    if light is not None and dark is not None:
        return {"light_avg_dn": light, "dark_max_dn": dark}
    if light is not None:
        return _light_term(light)
    # A dark frame inside the ambient threshold is not evidence of coupling.
    if dark is not None and dark > DEFAULT_DARK_MAX_DN:
        return _dark_term(dark)
    return None


class LiveSink:
    """SDK pipeline sink: ``live`` FrameBatches become ``bfi``, ``bvi``, and ``cq``.

    Live batches are row-addressed: each row is one camera on one side
    (``side_ids[i]``, ``cam_ids[i]``) for one capture (``abs_frame_ids[i]``). The
    sink keeps the latest value per camera and emits one 16-camera frame per
    capture when the next capture begins. Batch timestamps start at 0 when the
    scan starts; ``t0`` maps them onto the shared clock.

    Contact quality uses the same DN path as ``features.cq_score``: light frames
    contribute ``mean_dc_rt``, dark frames contribute ``subtracted_mean``, and
    ``low_light_rt`` (a frame that arrived with no light) scores 0. A side with
    no such samples is null. The timestamp-repair ``quality`` flag is ignored.
    Dark, warmup, and stale rows are not written into BFI or BVI. Dark rows
    still contribute their dark DN. This sink does not estimate heart rate or
    stress. The live gate does that from these frames.
    """

    channels = {"live"}

    def __init__(
        self,
        publish: Emit,
        now: Callable[[], float] = clock.now,
        on_sample: Callable[[], None] | None = None,
    ) -> None:
        self._publish = publish
        self._now = now
        self._on_sample = on_sample
        self._t0 = 0.0
        self._current: int | None = None
        self._t: float = 0.0
        self._bfi = [[None] * 8, [None] * 8]
        self._bvi = [[None] * 8, [None] * 8]
        self._light = [[None] * 8, [None] * 8]
        self._dark = [[None] * 8, [None] * 8]
        self._unlit = [[False] * 8, [False] * 8]

    def on_scan_start(self, meta: Any) -> None:
        self._t0 = self._now()
        self._current = None
        self._light = [[None] * 8, [None] * 8]
        self._dark = [[None] * 8, [None] * 8]
        self._unlit = [[False] * 8, [False] * 8]

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
            frame_type = str(types[i]).lower() if types is not None else ""
            # Warmup and stale rows are not measurements.
            if frame_type in {"stale", "warmup"}:
                continue
            if side_ids is not None and cam_ids is not None:
                cells = [(int(side_ids[i]), int(cam_ids[i]))]
            else:
                cells = [(s, c) for s in range(2) for c in range(8)]
            # Dark frames are laser-off. Their BFI/BVI would spike the trace and
            # the heatmap, but the dark DN is the contact measurement.
            if frame_type == "dark":
                for side, cam in cells:
                    if 0 <= side < 2 and 0 <= cam < 8:
                        self._note_contact(batch, i, side, cam, frame_type)
                continue
            capture = int(abs_ids[i]) if abs_ids is not None else i
            if self._current is not None and capture != self._current:
                frames.extend(self._snapshot())
            self._current = capture
            self._t = self._t0 + float(batch.timestamp_s[i])
            for side, cam in cells:
                if 0 <= side < 2 and 0 <= cam < 8:
                    bfi = _value(float(batch.bfi_live[i, side, cam]))
                    bvi = _value(float(batch.bvi_live[i, side, cam]))
                    self._bfi[side][cam] = bfi
                    self._bvi[side][cam] = bvi
                    if (bfi is not None or bvi is not None) and self._on_sample is not None:
                        self._on_sample()
                    self._note_contact(batch, i, side, cam, frame_type)
        if frames:
            self._publish(frames)

    def on_complete(self) -> None:
        if self._current is not None:
            self._publish(self._snapshot())
        self._current = None

    def _note_contact(self, batch: Any, index: int, side: int, cam: int, frame_type: str) -> None:
        if frame_type == "dark":
            dark = _cell(batch, "subtracted_mean", index, side, cam)
            if dark is not None:
                self._dark[side][cam] = dark
            return
        if _flag(batch, "low_light_rt", index, side, cam):
            self._unlit[side][cam] = True
            return
        light = _cell(batch, "mean_dc_rt", index, side, cam)
        if light is not None:
            self._light[side][cam] = light
            self._unlit[side][cam] = False

    def _side_cq(self, side: int) -> float | None:
        values: list[float | dict[str, float]] = []
        for cam in range(8):
            scored = _camera_contact(
                self._light[side][cam], self._dark[side][cam], self._unlit[side][cam]
            )
            if scored is not None:
                values.append(scored)
        if not values:
            return None
        try:
            return cq_score(values).score
        except (TypeError, ValueError):
            return None

    def _snapshot(self) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = [
            {"type": metric, "t": self._t, "left": list(values[0]), "right": list(values[1])}
            for metric, values in (("bfi", self._bfi), ("bvi", self._bvi))
        ]
        left = self._side_cq(0)
        right = self._side_cq(1)
        # A side with no samples stays null. The live gate ignores that side
        # instead of treating a missing sensor as perfect or as poor contact.
        if left is not None or right is not None:
            frames.append({"type": "cq", "t": self._t, "left": left, "right": right})
        return frames


class DeviceManager:
    def __init__(
        self,
        emit: Emit,
        data_dir: Path,
        factory: Callable[[Path], tuple[Any, Any, str]] = _default_factory,
        now: Callable[[], float] = clock.now,
        camera_power_settle_s: float = CAMERA_POWER_SETTLE_S,
        camera_enable_wait_s: float = CAMERA_ENABLE_WAIT_S,
        camera_configure_timeout_s: float = CAMERA_CONFIGURE_TIMEOUT_S,
        camera_program_min_s: float = CAMERA_PROGRAM_MIN_S,
        camera_frame_wait_s: float = CAMERA_FRAME_WAIT_S,
    ) -> None:
        self._emit = emit
        self._data_dir = data_dir
        self._factory = factory
        self._now = now
        self._camera_power_settle_s = camera_power_settle_s
        self._camera_enable_wait_s = camera_enable_wait_s
        self._camera_configure_timeout_s = camera_configure_timeout_s
        self._camera_program_min_s = camera_program_min_s
        self._camera_frame_wait_s = camera_frame_wait_s
        self._frame_seen = threading.Event()
        self._config_pct = 0
        self._config_note = ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._iface: Any = None
        self._scan_request: Any = None
        self._poller: asyncio.Task[None] | None = None
        self.sdk_version = ""
        self.console = self.left = self.right = False
        self.scanning = False
        self.status = ""
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
            "status": self.status,
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
            _cancel_configure(self._iface)
            self._iface.stop()
        self._iface = None
        self.console = self.left = self.right = self.scanning = False
        self.status = ""
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
        self._frame_seen.clear()

        left_mask = CAMERA_MASK_ALL if self.left else 0x00
        right_mask = CAMERA_MASK_ALL if self.right else 0x00
        try:
            self._apply_laser_driver()
            self._prepare_cameras(left_mask, right_mask)
        except DeviceError as exc:
            self.scanning = False
            self.status = ""
            self.error = str(exc)
            self._emit_state()
            raise

        def on_error(exc: BaseException) -> None:
            self.scanning = False
            self.status = ""
            self.error = f"Scan stopped: {exc}"
            self._emit_state()

        request = self._scan_request(
            subject_id=subject_id or "stress-alert",
            duration_sec=SCAN_SECONDS,
            left_camera_mask=left_mask,
            right_camera_mask=right_mask,
            sinks=[LiveSink(self._publish, self._now, on_sample=self._frame_seen.set)],
            on_error=on_error,
        )
        # start_scan returns True once its worker is spawned. That worker calls
        # enable_camera and only logs a failure, then starts the trigger anyway.
        try:
            watch = self._arm_enable_watch((("left", left_mask), ("right", right_mask)))
        except DeviceError as exc:
            self.scanning = False
            self.status = ""
            self.error = str(exc)
            self._emit_state()
            raise
        try:
            if not self._iface.start_scan(request):
                reason = getattr(self._iface.scan_workflow, "last_scan_error", None)
                self.status = ""
                self.error = f"The SDK refused to start the scan: {reason or 'no reason given'}"
                self._emit_state()
                raise DeviceError(self.error)
            self._require_sdk_enable(watch)
        finally:
            self._disarm_enable_watch(watch)
        self._require_live_frame()
        self.scanning = True
        self.status = ""
        self.error = ""
        self._emit_state()
        return self.state()

    def stop_scan(self) -> dict[str, Any]:
        if self._iface is not None and self.scanning:
            self._iface.cancel_scan()
        self.scanning = False
        self._emit_state()
        return self.state()

    def _apply_laser_driver(self) -> None:
        """Write the bundled laser-driver registers before any camera work.

        Bloodflow does this on every console connect
        (``set_laser_power_from_config`` → ``MotionInterface.apply_laser_power``).
        The registers sit in console FPGA SRAM and are cleared when the console
        loses power. Opening the bloodflow app once leaves them set until that
        power cycle, so a later dashboard scan can emit light without this call.
        A cold console still enables cameras and can report a running scan, but
        the trigger pulses a dark laser and no BFI/BVI arrives.

        Connect stays discovery-only: the 3 s USB wait can return before the
        console is up, and a failed write must fail Start scan (409), not Search.
        ``force_fault`` stays false. That flag loads the interlock-trip set.
        """
        apply = getattr(self._iface, "apply_laser_power", None)
        if not callable(apply):
            raise DeviceError("Open-Motion SDK is missing apply_laser_power; cannot start a scan.")
        self.status = LASER_SETUP_STATUS
        self.error = ""
        self._emit_state()
        try:
            ok = bool(apply(force_fault=False))
        except Exception as exc:
            self.status = ""
            raise DeviceError(
                f"Laser driver setup failed: {exc}. The scan was not started."
            ) from exc
        if not ok:
            self.status = ""
            raise DeviceError(
                "Laser driver setup failed. The console laser registers were not written. "
                "The scan was not started."
            )

    def _prepare_cameras(self, left_mask: int, right_mask: int) -> None:
        """Power the scan mask and require ``enable_camera`` before ``start_scan``.

        The bloodflow app calls ``MotionSensor.enable_camera_power`` at connect
        and leaves those cameras on (``motion_connector._run_sensor_init_impl``,
        mask 0xFF, then 0.5 s). ``ScanWorkflow.start_scan`` calls ``enable_camera``
        and only logs a failure, so an unpowered module still returns a running
        scan and an empty live pipe. Power the same mask the scan will stream,
        settle, and refuse to start when enable fails. Laser registers are
        already written by ``_apply_laser_driver``.

        A successful enable is turned back off so ``start_scan`` keeps its own
        order: external frame sync, then ``enable_camera``, then the trigger.

        Between power and that enable, ``start_configure_camera_sensors`` programs
        each camera FPGA and writes sensor registers. That is the bloodflow flash
        step, and it has to run after a power loss because FPGA SRAM does not
        keep the bitstream. Mask stays ``CAMERA_MASK_ALL``. Both modules run at
        once, about 2 minutes for 16 cameras. Progress is published on ``status``.
        """
        active = [
            (side, mask) for side, mask in (("left", left_mask), ("right", right_mask)) if mask
        ]
        for side, mask in active:
            sensor = self._sensor(side)
            if not _camera_call(sensor, "enable_camera_power", mask):
                raise DeviceError(
                    f"Failed to power on cameras on {side} (mask {_mask_label(mask)}). "
                    "The scan was not started."
                )
            if self._camera_power_settle_s > 0:
                time.sleep(self._camera_power_settle_s)

        self._configure_cameras(left_mask, right_mask)

        enabled: list[tuple[Any, int]] = []
        try:
            for side, mask in active:
                sensor = self._sensor(side)
                if not _camera_call(sensor, "enable_camera", mask):
                    raise DeviceError(
                        f"Failed to enable camera on {side} (mask {_mask_label(mask)}). "
                        "The scan was not started."
                    )
                enabled.append((sensor, mask))
        except DeviceError:
            _disable_cameras(enabled)
            raise
        _disable_cameras(enabled)

    def _configure_cameras(self, left_mask: int, right_mask: int) -> None:
        """Program FPGAs and sensor registers for the scan mask. Block until done.

        Bloodflow scan order is flash, then trigger, then capture. Flash is
        ``start_configure_camera_sensors``: power (again), ``program_fpga``, then
        ``camera_configure_registers`` for each camera in the mask. Sides run in
        parallel. A failure here must not fall through to ``start_scan``.
        """
        start = getattr(self._iface, "start_configure_camera_sensors", None)
        if not callable(start):
            raise DeviceError(
                "Open-Motion SDK is missing start_configure_camera_sensors; cannot start a scan."
            )
        done = threading.Event()
        holder: dict[str, Any] = {}

        def on_progress(pct: int) -> None:
            self._config_pct = int(pct)
            self._publish_config_status()

        def on_log(msg: str) -> None:
            self._config_note = str(msg)
            self._publish_config_status()

        def on_complete(result: Any) -> None:
            holder["result"] = result
            done.set()

        self._reject_demo_mode(left_mask, right_mask)
        self._config_pct = 0
        self._config_note = "Programming camera FPGAs and registers"
        self._publish_config_status()
        watch = self._arm_program_watch(left_mask, right_mask)
        try:
            try:
                started = bool(
                    start(
                        _configure_request(left_mask, right_mask),
                        on_progress_fn=on_progress,
                        on_log_fn=on_log,
                        on_complete_fn=on_complete,
                    )
                )
            except DeviceError:
                self.status = ""
                raise
            except Exception as exc:
                self.status = ""
                raise DeviceError(
                    f"Camera configure failed: {exc}. The scan was not started."
                ) from exc
            if not started:
                self.status = ""
                raise DeviceError("Camera configure could not start. The scan was not started.")
            if not done.wait(self._camera_configure_timeout_s):
                _cancel_configure(self._iface)
                self.status = ""
                raise DeviceError(
                    "Camera configure timed out after "
                    f"{int(self._camera_configure_timeout_s)} s. The scan was not started."
                )
        finally:
            self._disarm_program_watch(watch)
        result = holder.get("result")
        ok = bool(getattr(result, "ok", False))
        err = str(getattr(result, "error", "") or "no result")
        self.status = ""
        if not ok:
            raise DeviceError(f"Camera configure failed: {err}. The scan was not started.")
        # result.ok only means every program_fpga call returned True. In
        # demo_mode, and on any path that ACKs without loading SRAM, that
        # return is immediate. A real load is about 14 s per camera.
        self._require_real_program(watch)
        self._require_programmed_status(left_mask, right_mask)

    def _reject_demo_mode(self, left_mask: int, right_mask: int) -> None:
        """``demo_mode`` makes program_fpga and enable_camera return True immediately."""
        for side, mask in (("left", left_mask), ("right", right_mask)):
            if not mask:
                continue
            sensor = self._sensor(side)
            if getattr(sensor, "demo_mode", False):
                raise DeviceError(
                    f"Open-Motion {side} sensor is in demo_mode, which does not program "
                    "cameras or emit BFI/BVI. The scan was not started."
                )

    def _arm_program_watch(self, left_mask: int, right_mask: int) -> dict[str, Any]:
        """Time each ``program_fpga`` while configure runs. Restored by the caller."""
        records: list[tuple[str, int, float]] = []
        originals: list[tuple[Any, Any]] = []
        if self._camera_program_min_s <= 0:
            return {"records": records, "originals": originals}
        for side, mask in (("left", left_mask), ("right", right_mask)):
            if not mask:
                continue
            sensor = self._sensor(side)
            original = getattr(sensor, "program_fpga", None)
            if not callable(original):
                raise DeviceError("Open-Motion SDK is missing program_fpga; cannot start a scan.")

            def program_fpga(*args, _side=side, _orig=original, **kwargs):
                position = kwargs.get("camera_position", args[0] if args else 0)
                started = time.monotonic()
                try:
                    return _orig(*args, **kwargs)
                finally:
                    records.append((_side, int(position), time.monotonic() - started))

            sensor.program_fpga = program_fpga
            originals.append((sensor, original))
        return {"records": records, "originals": originals}

    def _disarm_program_watch(self, watch: dict[str, Any]) -> None:
        for sensor, original in watch["originals"]:
            sensor.program_fpga = original

    def _require_real_program(self, watch: dict[str, Any]) -> None:
        """Refuse a configure that did not spend real time inside ``program_fpga``."""
        if self._camera_program_min_s <= 0:
            return
        records: list[tuple[str, int, float]] = watch["records"]
        if not records:
            raise DeviceError(
                "Camera configure reported success without calling program_fpga. "
                "The scan was not started."
            )
        for side, mask, elapsed in records:
            if elapsed < self._camera_program_min_s:
                raise DeviceError(
                    f"program_fpga on {side} (mask {_mask_label(mask)}) returned in "
                    f"{elapsed:.2f} s. A camera FPGA SRAM load takes about 14 s. "
                    "The scan was not started."
                )

    def _require_programmed_status(self, left_mask: int, right_mask: int) -> None:
        """READY + programmed + configured, for every camera in the scan mask."""
        for side, mask in (("left", left_mask), ("right", right_mask)):
            if not mask:
                continue
            sensor = self._sensor(side)
            read = getattr(sensor, "get_camera_status", None)
            if not callable(read):
                raise DeviceError(
                    "Open-Motion SDK is missing get_camera_status; cannot start a scan."
                )
            try:
                status_map = read(mask)
            except Exception as exc:
                raise DeviceError(
                    f"Could not read camera status on {side} after configure: {exc}. "
                    "The scan was not started."
                ) from exc
            if not status_map:
                raise DeviceError(
                    f"Could not read camera status on {side} after configure. "
                    "The scan was not started."
                )
            for pos in range(8):
                if not (mask & (1 << pos)):
                    continue
                status = status_map.get(pos)
                if status is None or (int(status) & CAMERA_STATUS_FLASHED) != CAMERA_STATUS_FLASHED:
                    shown = "missing" if status is None else _mask_label(int(status))
                    raise DeviceError(
                        f"{side.capitalize()} camera {pos + 1} is not programmed after "
                        f"configure (status {shown}). The scan was not started."
                    )

    def _require_live_frame(self) -> None:
        """Do not report scanning until a finite BFI or BVI value has arrived.

        ``enable_camera`` only acknowledges the stream command. ``start_scan``
        then returns while its worker is still starting the trigger. An empty
        histogram pipe still looks like a running scan.
        """
        if self._camera_frame_wait_s <= 0:
            return
        self.status = FRAME_WAIT_STATUS
        self.error = ""
        self._emit_state()
        if self._frame_seen.wait(self._camera_frame_wait_s):
            return
        try:
            self._iface.cancel_scan()
        except Exception:
            pass
        self.scanning = False
        self.status = ""
        self.error = (
            f"No BFI/BVI frame arrived within {int(self._camera_frame_wait_s)} s "
            "after the scan started. The scan was not started."
        )
        self._emit_state()
        raise DeviceError(self.error)

    def _publish_config_status(self) -> None:
        note = self._config_note or "Programming camera FPGAs and registers"
        self.status = (
            f"Configuring cameras {self._config_pct}%: {note}. About 2 minutes for all 16 cameras."
        )
        self.error = ""
        self._emit_state()

    def _sensor(self, side: str) -> Any:
        sensor = getattr(self._iface, side, None)
        if sensor is None:
            raise DeviceError(f"Open-Motion {side} sensor handle is missing; cannot power cameras.")
        connected = getattr(sensor, "is_connected", None)
        if callable(connected) and not connected():
            raise DeviceError(f"{side.capitalize()} sensor is not connected.")
        return sensor

    def _arm_enable_watch(self, masks: tuple[tuple[str, int], ...]) -> dict[str, Any]:
        """Record ``enable_camera`` results while ``start_scan``'s worker runs."""
        expected = {side for side, mask in masks if mask}
        failures: list[tuple[str, int]] = []
        seen: list[str] = []
        originals: list[tuple[Any, Any]] = []
        pending: list[tuple[Any, Any, Any]] = []
        lock = threading.Lock()
        done = threading.Event()

        for side, mask in masks:
            if not mask:
                continue
            sensor = self._sensor(side)
            original = getattr(sensor, "enable_camera", None)
            if not callable(original):
                raise DeviceError("Open-Motion SDK is missing enable_camera; cannot start a scan.")

            def enable_camera(camera_mask, *args, _side=side, _orig=original, **kwargs):
                ok = False
                try:
                    ok = bool(_orig(camera_mask, *args, **kwargs))
                    return ok
                finally:
                    with lock:
                        seen.append(_side)
                        if not ok:
                            failures.append((_side, int(camera_mask)))
                        if expected.issubset(seen):
                            done.set()

            pending.append((sensor, enable_camera, original))

        for sensor, wrapped, original in pending:
            sensor.enable_camera = wrapped
            originals.append((sensor, original))

        return {
            "expected": expected,
            "failures": failures,
            "seen": seen,
            "lock": lock,
            "done": done,
            "originals": originals,
            "masks": dict(masks),
        }

    def _require_sdk_enable(self, watch: dict[str, Any]) -> None:
        """Cancel the scan when the SDK's ``enable_camera`` fails or never runs."""
        expected: set[str] = watch["expected"]
        if not expected:
            return
        done: threading.Event = watch["done"]
        if not done.is_set():
            done.wait(self._camera_enable_wait_s)
        with watch["lock"]:
            failures = list(watch["failures"])
            seen = set(watch["seen"])
        if not failures and expected.issubset(seen):
            return
        try:
            self._iface.cancel_scan()
        except Exception:
            pass
        self.scanning = False
        self.status = ""
        if failures:
            side, mask = failures[0]
        else:
            side = next(item for item in ("left", "right") if item in expected - seen)
            mask = int(watch["masks"][side])
        self.error = (
            f"Failed to enable camera on {side} (mask {_mask_label(mask)}). "
            "The scan was not started."
        )
        self._emit_state()
        raise DeviceError(self.error)

    def _disarm_enable_watch(self, watch: dict[str, Any]) -> None:
        for sensor, original in watch["originals"]:
            sensor.enable_camera = original

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
