"""Start a live Open-Motion scan from a script.

The dashboard's Connect device button (``dashboard/device.py``) is the main live
path and streams BFI/BVI into the charts. ``start_live_scan`` is the scripted
equivalent: it imports ``MotionInterface`` and ``ScanRequest`` only when
``allow_live=True`` and writes the SDK's corrected CSV under ``data_dir``.
``demo_mode`` is refused: on 2026-10-24 a Mac check of
``MotionInterface(demo_mode=True)`` wrote a telemetry CSV and no BFI/BVI frames
(see docs/OPEN-MOTION.md). CSV replay was removed on 2026-10-24; the team runs on
live device data only. This module does not change laser power or any
safety-critical optical output.

For research.
"""

from __future__ import annotations


def start_live_scan(
    *,
    data_dir: str,
    subject_id: str = "phantom-01",
    duration_sec: float = 60,
    operator_id: str = "stress-alert",
    demo_mode: bool = False,
    allow_live: bool = False,
):
    """Start a station scan and return the ``MotionInterface``.

    Refuses to run unless ``allow_live=True``. Refuses ``demo_mode`` because
    that mode did not emit BFI/BVI in the 2026-10-24 check. The corrected CSV
    is written under ``data_dir`` when no scan database is configured. Stop
    the interface with ``iface.stop()`` after ``scan_workflow.await_complete()``.

    This does not set laser power and does not change safety-critical optical
    output.
    """
    if not allow_live:
        raise RuntimeError(
            "Live Open-Motion is gated. Pass allow_live=True only on the machine "
            "with the console plugged in, or use the dashboard's Connect device button."
        )
    if demo_mode:
        raise RuntimeError(
            "MotionInterface(demo_mode=True) did not emit BFI/BVI in the "
            "2026-10-24 Mac check (telemetry CSV only). Connect the real device."
        )
    motion_interface, scan_request = _import_live_types()
    interface = motion_interface(data_dir=data_dir, operator_id=operator_id)
    interface.start(wait=True, wait_timeout=3.0)
    started = interface.start_scan(
        scan_request(
            subject_id=subject_id,
            duration_sec=duration_sec,
            left_camera_mask=0xFF,
            right_camera_mask=0xFF,
        )
    )
    if not started:
        error = getattr(interface.scan_workflow, "last_scan_error", None)
        interface.stop()
        raise RuntimeError(error or "start_scan was refused")
    return interface


def _import_live_types():
    try:
        from omotion import MotionInterface
        from omotion.ScanWorkflow import ScanRequest
    except ImportError as exc:
        raise ImportError("openmotion-sdk is not installed. Run uv sync in stress-alert/.") from exc
    return MotionInterface, ScanRequest
