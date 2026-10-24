"""Live dashboard server.

Producers push frames to ``/ws/ingest``; browsers receive them on ``/ws``. Frames are
validated against ``dashboard.schema`` before they are rebroadcast. The session and
phase logger is driven through ``/api/session``, ``/api/phase`` and ``/api/protocol``.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from dashboard import clock, dev_feed
from dashboard.hub import Hub, drain
from dashboard.schema import PhaseName, frame_adapter
from session.phase_logger import MarkerOutlet, PhaseError, PhaseLogger

STATIC = Path(__file__).resolve().parent / "static"
SESSIONS = Path(__file__).resolve().parent.parent / "sessions"


class SessionStart(BaseModel):
    subject_id: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=2000)


class PhaseMark(BaseModel):
    phase: PhaseName


class ProtocolStart(BaseModel):
    baseline: float = Field(default=60, gt=0, le=600)
    hold: float = Field(default=30, gt=0, le=120)
    recovery: float = Field(default=90, gt=0, le=600)
    cycles: int = Field(default=1, ge=1, le=10)


def create_app(
    *,
    dev_feed_url: str | None = None,
    sessions_dir: Path = SESSIONS,
    lsl_markers: bool = True,
) -> FastAPI:
    """Build the app. With ``dev_feed_url`` set, replay sample data into it on startup."""
    hub = Hub()
    markers = MarkerOutlet() if lsl_markers else None
    logger = PhaseLogger(sessions_dir, emit=hub.publish, markers=markers)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if markers is not None:
            hub.publish(
                [
                    {
                        "type": "status",
                        "source": "lsl markers",
                        "connected": markers.available,
                        "detail": markers.error,
                    }
                ]
            )
        hub.publish([logger.state()])
        task = asyncio.create_task(dev_feed.run_forever(dev_feed_url)) if dev_feed_url else None
        yield
        logger.stop_session()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="stress-alert dashboard", lifespan=lifespan)
    app.state.hub = hub
    app.state.logger = logger
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def guarded(action: Any) -> dict[str, Any]:
        try:
            action()
        except PhaseError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return logger.state()

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
        return guarded(logger.stop_session)

    @app.post("/api/phase")
    async def phase(body: PhaseMark) -> dict[str, Any]:
        return guarded(lambda: logger.mark(body.phase, "manual"))

    @app.post("/api/protocol/start")
    async def protocol_start(body: ProtocolStart) -> dict[str, Any]:
        durations = {"baseline": body.baseline, "hold": body.hold, "recovery": body.recovery}
        return guarded(lambda: logger.start_timer(durations, body.cycles))

    @app.post("/api/protocol/stop")
    async def protocol_stop() -> dict[str, Any]:
        return guarded(logger.cancel_timer)

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
                    hub.publish(accepted)
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
