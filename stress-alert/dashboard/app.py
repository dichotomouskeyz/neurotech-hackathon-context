"""Live dashboard server.

Producers push frames to ``/ws/ingest``; browsers receive them on ``/ws``. Frames are
validated against ``dashboard.schema`` before they are rebroadcast. The session and
phase logger is driven through ``/api/session``, ``/api/phase`` and ``/api/protocol``;
the Open-Motion device through ``/api/device``.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from dashboard import clock, dev_feed
from dashboard.demo_recovery import DEMO_DURATIONS, run_recovery_demo
from dashboard.device import DeviceError, DeviceManager
from dashboard.hub import Hub, drain
from dashboard.live_gate import LiveGate
from dashboard.replay import (
    ReplayEngine,
    ensure_session_scan_copy,
    list_recordings,
    newest_scan_csv,
)
from dashboard.schema import PhaseName, frame_adapter
from features.recovery_gate import (
    BFI_RECOVERED_BELOW,
    RECOVERED_WITHIN_PCT_MAX,
    RECOVERED_WITHIN_PCT_MIN,
)
from session.phase_logger import (
    LONG_BASELINE_S,
    LONG_HOLD_S,
    LONG_RECOVERY_S,
    LONG_WORK_MAX_S,
    LONG_WORK_S,
    MarkerOutlet,
    PhaseError,
    PhaseLogger,
)

log = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent / "static"
SESSIONS = Path(__file__).resolve().parent.parent / "sessions"
DATA = Path(__file__).resolve().parent.parent / "data"
DEMO_SCAN = DATA / "sample_scan.csv"


class SessionStart(BaseModel):
    subject_id: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=2000)


class PhaseMark(BaseModel):
    phase: PhaseName


class ProtocolStart(BaseModel):
    """Long session defaults: 20 s baseline, no breath-hold, 20 min of work.

    Hold at 0 skips the breath-hold and its recovery. ``work_until_end`` keeps
    Work running until the operator presses End. Demo Mode does not use this
    body; it keeps the short offline durations.
    """

    baseline: float = Field(default=LONG_BASELINE_S, gt=0, le=600)
    hold: float = Field(default=LONG_HOLD_S, ge=0, le=120)
    recovery: float = Field(default=LONG_RECOVERY_S, gt=0, le=600)
    continue_s: float = Field(default=LONG_WORK_S, gt=0, le=LONG_WORK_MAX_S)
    cycles: int = Field(default=1, ge=1, le=10)
    closed_loop: bool = False
    work_until_end: bool = False
    # Percent of baseline. 5 means the gate opens when the BFI rise is under 5%.
    recovered_within_pct: float = Field(
        default=BFI_RECOVERED_BELOW * 100.0,
        ge=RECOVERED_WITHIN_PCT_MIN,
        le=RECOVERED_WITHIN_PCT_MAX,
    )
    subject_id: str = Field(default="", max_length=64)


class DemoStart(BaseModel):
    """Optional body. An empty post keeps the gate's current recovery boundary."""

    recovered_within_pct: float | None = Field(
        default=None,
        ge=RECOVERED_WITHIN_PCT_MIN,
        le=RECOVERED_WITHIN_PCT_MAX,
    )


class ReplayLoad(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class ReplaySeek(BaseModel):
    t_s: float = Field(ge=0.0)


_DEMO_START = Body(default_factory=DemoStart)


def create_app(
    *,
    dev_feed_url: str | None = None,
    sessions_dir: Path = SESSIONS,
    data_dir: Path = DATA,
    lsl_markers: bool = True,
    device_factory: Any = None,
) -> FastAPI:
    """Build the app. With ``dev_feed_url`` set, replay sample data into it on startup.

    ``device_factory`` replaces the openmotion-sdk constructor (tests use a fake).
    """
    hub = Hub()
    gate = LiveGate()
    replay = ReplayEngine()
    demo_task: asyncio.Task[None] | None = None
    dev_feed_task: asyncio.Task[None] | None = None

    def publish(frames: list[dict[str, Any]], *, heart_rate: bool = True) -> None:
        """Broadcast ``frames`` and any stress or heart-rate frames derived from them."""
        extra: list[dict[str, Any]] = []
        try:
            extra = gate.observe(frames)
        except Exception:
            log.exception("hemodynamic gate failed")
        if not heart_rate:
            extra = [frame for frame in extra if frame.get("type") != "hr"]
        hub.publish([*frames, *extra])

    def publish_demo(frames: list[dict[str, Any]]) -> None:
        # The demo script has no pulse, so any optical heart rate from it is noise.
        publish(frames, heart_rate=False)

    markers = MarkerOutlet() if lsl_markers else None
    logger = PhaseLogger(sessions_dir, emit=publish, markers=markers)
    device_kwargs = {"factory": device_factory} if device_factory else {}
    device = DeviceManager(publish, sessions_dir / "device-scans", **device_kwargs)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if markers is not None:
            publish(
                [
                    {
                        "type": "status",
                        "source": "lsl markers",
                        "connected": markers.available,
                        "detail": markers.error,
                    }
                ]
            )
        publish([logger.state(), device.state()])
        device.start_polling(asyncio.get_running_loop())
        nonlocal dev_feed_task
        if dev_feed_url:
            dev_feed_task = asyncio.create_task(dev_feed.run_forever(dev_feed_url))
        yield
        await _cancel_demo(stop_protocol=False)
        replay.stop()
        logger.stop_session()
        await asyncio.to_thread(device.shutdown)
        await _stop_dev_feed()

    app = FastAPI(title="stress-alert dashboard", lifespan=lifespan)

    @app.middleware("http")
    async def dashboard_assets_not_cached(request, call_next):
        """Keep Operator on the files from this process after a restart."""
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.state.hub = hub
    app.state.logger = logger
    app.state.device = device
    app.state.gate = gate
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def guarded(action: Any) -> dict[str, Any]:
        try:
            action()
        except PhaseError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return logger.state()

    async def device_call(action: Any, *args: Any) -> dict[str, Any]:
        """Run a blocking SDK call off the event loop; device errors become 409s."""
        try:
            return await asyncio.to_thread(action, *args)
        except DeviceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/device")
    async def device_state() -> dict[str, Any]:
        return device.state()

    @app.post("/api/device/connect")
    async def device_connect() -> dict[str, Any]:
        return await device_call(device.connect)

    @app.post("/api/device/disconnect")
    async def device_disconnect() -> dict[str, Any]:
        return await device_call(device.disconnect)

    @app.post("/api/device/scan/start")
    async def device_scan_start() -> dict[str, Any]:
        # A live scan owns contact quality. Stop Demo Mode before the laser path
        # so the script cannot publish a stand-in CQ over the headset.
        await _cancel_demo(stop_protocol=True)
        if logger.session is not None and logger.session.subject_id == "demo":
            logger.stop_session()
        subject = logger.session.subject_id if logger.session else ""
        return await device_call(device.start_scan, subject)

    def _keep_scan_with_session() -> None:
        """Link the SDK scan CSV into the open session so replay can find it later."""
        if logger.session is None or device.scan_started_at is None:
            return
        source = newest_scan_csv(sessions_dir / "device-scans", since=device.scan_started_at - 1.0)
        if source is not None:
            ensure_session_scan_copy(logger.session.directory, source)

    @app.post("/api/device/scan/stop")
    async def device_scan_stop() -> dict[str, Any]:
        state = await device_call(device.stop_scan)
        _keep_scan_with_session()
        return state

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/clock")
    async def shared_clock() -> dict[str, Any]:
        return {"t": clock.now(), "clock": clock.NAME}

    @app.get("/api/session")
    async def session_state() -> dict[str, Any]:
        return logger.state()

    @app.post("/api/session/start")
    async def session_start(body: SessionStart) -> dict[str, Any]:
        return guarded(lambda: logger.start_session(body.subject_id, body.notes))

    @app.post("/api/session/stop")
    async def session_stop() -> dict[str, Any]:
        _keep_scan_with_session()
        return guarded(logger.stop_session)

    @app.post("/api/phase")
    async def phase(body: PhaseMark) -> dict[str, Any]:
        return guarded(lambda: logger.mark(body.phase, "manual"))

    @app.post("/api/protocol/start")
    async def protocol_start(body: ProtocolStart) -> dict[str, Any]:
        if body.closed_loop and logger.session is not None and logger.session.phase == "end":
            guarded(logger.stop_session)
        if logger.session is None and body.closed_loop:
            guarded(lambda: logger.start_session(body.subject_id.strip() or "demo"))
        work = None if body.work_until_end else body.continue_s
        durations = {
            "baseline": body.baseline,
            "hold": body.hold,
            "recovery": body.recovery,
            "work": work,
            "continue": work,
        }
        previous = gate.recovered_below

        def begin() -> None:
            # Apply the line first so the timer's samples use it, and put the
            # old line back if the protocol cannot start.
            gate.set_recovered_within_pct(body.recovered_within_pct)
            try:
                logger.start_timer(
                    durations,
                    body.cycles,
                    closed_loop=body.closed_loop,
                    signals=gate if body.closed_loop else None,
                )
            except Exception:
                gate.recovered_below = previous
                gate.settle_index = previous
                raise

        return guarded(begin)

    @app.post("/api/protocol/stop")
    async def protocol_stop() -> dict[str, Any]:
        await _cancel_demo(stop_protocol=False)
        return guarded(logger.cancel_timer)

    def _demo_running() -> bool:
        return demo_task is not None and not demo_task.done()

    async def _stop_dev_feed() -> None:
        nonlocal dev_feed_task
        task = dev_feed_task
        dev_feed_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _start_dev_feed() -> None:
        nonlocal dev_feed_task
        if not dev_feed_url or dev_feed_task is not None:
            return
        dev_feed_task = asyncio.create_task(dev_feed.run_forever(dev_feed_url))

    async def _cancel_demo(*, stop_protocol: bool) -> None:
        nonlocal demo_task
        running = demo_task
        demo_task = None
        if running is not None and not running.done():
            running.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await running
        if stop_protocol:
            logger.cancel_timer()

    async def _begin_replay(path: Path) -> dict[str, Any]:
        await _cancel_demo(stop_protocol=True)
        await _stop_dev_feed()
        try:
            loaded = replay.load(path)
        except ValueError as exc:
            await _start_dev_feed()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        replay.seek(0.0, gate=gate, publish=publish)
        return loaded

    @app.get("/api/replay/sessions")
    async def replay_sessions() -> dict[str, Any]:
        # Header and tail only. A full CSV parse here blocks the dashboard.
        sessions = await asyncio.to_thread(list_recordings, data_dir, sessions_dir)
        return {"sessions": sessions, "data_dir": str(data_dir)}

    @app.get("/api/replay")
    async def replay_state() -> dict[str, Any]:
        return replay.state()

    @app.post("/api/replay/load")
    async def replay_load(body: ReplayLoad) -> dict[str, Any]:
        return await _begin_replay(Path(body.path))

    @app.post("/api/replay/seek")
    async def replay_seek(body: ReplaySeek) -> dict[str, Any]:
        if not replay.loaded:
            raise HTTPException(status_code=409, detail="Load a recording first.")
        try:
            return replay.seek(body.t_s, gate=gate, publish=publish)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/replay/stop")
    async def replay_stop() -> dict[str, Any]:
        replay.stop()
        publish(
            [
                {
                    "type": "status",
                    "source": "replay",
                    "connected": False,
                    "detail": "",
                }
            ]
        )
        await _start_dev_feed()
        return replay.state()

    async def _run_demo() -> None:
        publish(
            [
                {
                    "type": "status",
                    "source": "demo",
                    "connected": True,
                    "detail": "Simulated calibration, then work. Contact quality stays below 1.00.",
                }
            ]
        )
        try:
            reason = await run_recovery_demo(
                publish_demo,
                lambda: logger.session.phase if logger.session else None,
                lambda: bool(device.state().get("scanning")),
            )
            if reason == "scan":
                logger.cancel_timer()
        finally:
            publish(
                [
                    {
                        "type": "status",
                        "source": "demo",
                        "connected": False,
                        "detail": "",
                    }
                ]
            )

    @app.get("/api/demo")
    async def demo_state() -> dict[str, Any]:
        return {"running": _demo_running()}

    @app.post("/api/demo/start")
    async def demo_start(body: DemoStart = _DEMO_START) -> dict[str, Any]:
        nonlocal demo_task
        if device.state().get("scanning"):
            raise HTTPException(
                status_code=409,
                detail="A live scan is running. Demo mode does not replace contact quality.",
            )
        if _demo_running():
            raise HTTPException(status_code=409, detail="Demo mode is already running.")

        def begin() -> None:
            if logger.session is not None:
                logger.stop_session()
            logger.start_session("demo")
            if body.recovered_within_pct is not None:
                gate.set_recovered_within_pct(body.recovered_within_pct)
            logger.start_timer(dict(DEMO_DURATIONS), 1, closed_loop=True, signals=gate)

        state = guarded(begin)
        if logger.session is not None and DEMO_SCAN.is_file():
            ensure_session_scan_copy(logger.session.directory, DEMO_SCAN)
        demo_task = asyncio.create_task(_run_demo())
        return {"running": True, **state}

    @app.post("/api/demo/stop")
    async def demo_stop() -> dict[str, Any]:
        await _cancel_demo(stop_protocol=True)
        if logger.session is not None:
            guarded(logger.stop_session)
        return {"running": False, **logger.state()}

    @app.websocket("/ws")
    async def browser(ws: WebSocket) -> None:
        await ws.accept()
        queue = hub.subscribe()

        async def send() -> None:
            while True:
                await ws.send_text(json.dumps(await drain(queue)))

        async def receive() -> None:
            while True:
                await ws.receive_text()

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            hub.unsubscribe(queue)

    @app.websocket("/ws/ingest")
    async def ingest(ws: WebSocket, source: str = "unknown") -> None:
        await ws.accept()
        hub.publish([{"type": "status", "source": source, "connected": True, "detail": ""}])
        try:
            while True:
                accepted, errors = _validate(await ws.receive_text())
                if accepted:
                    publish(accepted)
                if errors:
                    await ws.send_text(json.dumps({"type": "error", "errors": errors}))
        except WebSocketDisconnect:
            pass
        finally:
            hub.publish([{"type": "status", "source": source, "connected": False, "detail": ""}])

    return app


def _validate(text: str) -> tuple[list[dict], list[str]]:
    """Parse one message (a frame or a list of frames) into valid frames and error strings."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"invalid JSON: {exc.msg}"]
    items = payload if isinstance(payload, list) else [payload]
    accepted, errors = [], []
    for i, item in enumerate(items):
        try:
            accepted.append(frame_adapter.validate_python(item).model_dump(mode="json"))
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            errors.append(f"frame {i}: {where}: {first['msg']}")
    return accepted, errors
