"""Live dashboard server.

Producers push frames to ``/ws/ingest``; browsers receive them on ``/ws``. Frames are
validated against ``dashboard.schema`` before they are rebroadcast.
"""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from dashboard import dev_feed
from dashboard.hub import Hub, drain
from dashboard.schema import frame_adapter

STATIC = Path(__file__).resolve().parent / "static"


def create_app(*, dev_feed_url: str | None = None) -> FastAPI:
    """Build the app. With ``dev_feed_url`` set, replay sample data into it on startup."""
    hub = Hub()

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(dev_feed.run_forever(dev_feed_url)) if dev_feed_url else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="stress-alert dashboard", lifespan=lifespan)
    app.state.hub = hub
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/clock")
    async def clock() -> dict[str, float]:
        return {"t": time.monotonic()}

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


app = create_app()
