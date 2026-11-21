import asyncio
import json
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .contracts import NewRun, Playhead
from .journal import Journal
from .media import (MAX_CAMERA_JPEG_BYTES, MAX_UPLOAD_BYTES, CameraFrames, MediaError,
                    VideoFrames, prepare)
from .models import GeminiVision
from .runs import RunConflict, Runs
from .settings import ROOT, Settings
from fixit.app import server as fixit_server

FIXIT_STATIC = ROOT / "fixit" / "static"

DEMO_ID = "counter-demo-v1"  # authored synthetic scene: offline fallback only
DEMO_LABEL = "Offline demo (synthetic)"
REAL_ID = "cafe-781-counter-v1"  # real café footage fetched by scripts/fetch_real_default.sh
REAL_LABEL = "Café 781 counter · real footage (Café dataset)"
REAL_VIDEO = ROOT / "demo" / "real" / "cafe-781-counter.mp4"


async def bundled_source(journal: Journal, home: Path, path: Path, source_id: str, label: str, kind: str) -> None:
    if not path.exists():
        return
    if journal.source(source_id):
        journal.relabel(source_id, label)
        return
    dest = home / "media" / source_id
    if dest.exists():
        shutil.rmtree(dest)
    journal.add_source(await asyncio.to_thread(prepare, path, dest, source_id, label, kind))


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.home.mkdir(parents=True, exist_ok=True)
        journal = Journal(settings.home / "operations.sqlite3")
        journal.interrupt_runs()
        await bundled_source(journal, settings.home, ROOT / "demo" / "counter.mp4", DEMO_ID, DEMO_LABEL, "synthetic")
        await bundled_source(journal, settings.home, REAL_VIDEO, REAL_ID, REAL_LABEL, "cafe")
        app.state.journal = journal
        sink = lambda kind, payload: journal.log("fixit", kind, payload)  # noqa: E731
        fixit_server.EVENT_SINKS.append(sink)
        app.state.upload_lock = asyncio.Semaphore(1)
        async with httpx.AsyncClient(follow_redirects=False) as client:
            app.state.runs = Runs(journal, settings, GeminiVision(settings, client))
            try:
                yield
            finally:
                workers = []
                for runner in list(app.state.runs.active.values()):
                    if runner.worker:
                        workers.append(runner.worker)
                    runner.finish("interrupted")
                if workers:
                    await asyncio.gather(*workers, return_exceptions=True)
                if sink in fixit_server.EVENT_SINKS:
                    fixit_server.EVENT_SINKS.remove(sink)

    app = FastAPI(title="Restaurant Ops Copilot", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.middleware("http")
    async def validate_request(request: Request, call_next):
        if request.method in {"POST", "PATCH", "DELETE"}:
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Open Café Ops to perform this action."}, status_code=403)
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES + 64 * 1024:
                return JSONResponse({"detail": "The video upload limit is 150 MiB."}, status_code=413)
        return await call_next(request)

    @app.get("/api/config")
    def config():
        return {
            "gemini_ready": bool(settings.api_key), "observer": settings.observer,
            "verifier": settings.verifier,
            # Default source: real café footage when it has been fetched, else the synthetic fallback.
            "demo_id": REAL_ID if app.state.journal.source(REAL_ID) else DEMO_ID, "synthetic_id": DEMO_ID, "threshold": settings.queue_threshold,
            "max_lag_ms": settings.max_lag_ms, "cadence_ms": settings.cadence_ms,
            "max_upload_bytes": MAX_UPLOAD_BYTES, "max_calls": settings.max_calls_run,
        }

    @app.get("/api/sources")
    def sources():
        return [source for source in app.state.journal.sources() if source["kind"] != "camera"]

    @app.post("/api/sources", status_code=201)
    async def upload(video: Annotated[UploadFile, File()], kind: Annotated[Literal["upload", "cafe"], Form()] = "upload"):
        source_id = uuid.uuid4().hex
        incoming_dir = settings.home / "incoming"
        incoming_dir.mkdir(exist_ok=True)
        incoming = incoming_dir / source_id
        size = 0
        try:
            with incoming.open("wb") as file:
                while chunk := await video.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "The video upload limit is 150 MiB.")
                    file.write(chunk)
            name = Path((video.filename or "Video").replace("\\", "/")).stem.strip()[:90] or "Video"
            async with app.state.upload_lock:
                source = await asyncio.to_thread(
                    prepare, incoming, settings.home / "media" / source_id, source_id, name, kind,
                )
            app.state.journal.add_source(source)
            return source
        except MediaError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            incoming.unlink(missing_ok=True)
            await video.close()

    @app.get("/api/sources/{source_id}/video")
    def source_video(source_id: str):
        source = app.state.journal.source(source_id)
        if source is None or source.kind == "camera":
            raise HTTPException(404, "Video not found.")
        path = settings.home / "media" / source.id / "video.mp4"
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/sources/{source_id}/frames/{at_ms}")
    def video_frame(source_id: str, at_ms: int):
        source = app.state.journal.source(source_id)
        frame = None
        if source:
            directory = settings.home / "media" / source.id
            stream = CameraFrames(directory / "frames") if source.kind == "camera" else VideoFrames(source, directory)
            frame = stream.exact(at_ms)
        if frame is None:
            raise HTTPException(404, "Frame not found.")
        return FileResponse(frame.path, media_type="image/jpeg")

    @app.get("/api/runs")
    def recent_runs():
        return app.state.journal.runs()

    @app.post("/api/runs", status_code=201)
    async def start_run(request: NewRun):
        try:
            return app.state.runs.start(request)
        except KeyError as exc:
            raise HTTPException(404, "Video source not found.") from exc
        except RunConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/runs/{run_id}/advance", status_code=202)
    async def advance(run_id: str, playhead: Playhead):
        runner = app.state.runs.active.get(run_id)
        if runner is None or runner.source.kind == "camera":
            raise HTTPException(409, "Start a new video run.")
        try:
            runner.advance(playhead.at_ms, playhead.final)
        except RunConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"at_ms": runner.watermark, "pending": runner.pending}

    @app.post("/api/runs/{run_id}/frame", status_code=202)
    async def camera_frame(run_id: str, request: Request,
                           at_ms: Annotated[int, Query(ge=0, le=45 * 60 * 1000)]):
        runner = app.state.runs.active.get(run_id)
        if runner is None or not isinstance(runner.frames, CameraFrames):
            raise HTTPException(409, "Start a new camera run.")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > MAX_CAMERA_JPEG_BYTES:
                raise HTTPException(413, "Camera image exceeds the frame size limit.")
        if runner.status != "running":
            raise HTTPException(409, "This camera run has ended.")
        try:
            runner.frames.add(at_ms, bytes(data))
            runner.advance(at_ms, False)
        except (MediaError, RunConflict) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"at_ms": at_ms}

    @app.post("/api/runs/{run_id}/stop")
    async def stop(run_id: str):
        if runner := app.state.runs.active.get(run_id):
            runner.finish("stopped")
        return {"status": "stopped"}

    @app.post("/api/runs/{run_id}/tasks/{task_id}/acknowledge")
    async def acknowledge(run_id: str, task_id: str):
        task = app.state.runs.acknowledge(run_id, task_id)
        if task is None:
            raise HTTPException(409, "This task is already acknowledged, resolved, or unavailable.")
        return task

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request, last_event_id: Annotated[str, Header()] = "0"):
        if app.state.journal.run(run_id) is None:
            raise HTTPException(404, "Run not found.")
        try:
            first = max(0, min(int(last_event_id), 2**63 - 1))
        except ValueError:
            first = 0

        async def stream():
            cursor = first
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                updates = app.state.journal.events(run_id, cursor)
                for event in updates:
                    cursor = event["id"]
                    yield f"id: {cursor}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"
                if len(updates) == 200:
                    continue
                if time.monotonic() - heartbeat > 10:
                    heartbeat = time.monotonic()
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/evaluation")
    def evaluation():
        report = settings.home / "evaluation.json"
        if not report.is_file():
            report = ROOT / "eval" / "fixture-report.json"
        if not report.is_file():
            raise HTTPException(404, "No evaluation report has been run.")
        return FileResponse(report, media_type="application/json")

    # ---- Fix-It Cam: film a broken thing -> diagnose -> Shop MCP -> fit check -> real checkout
    app.include_router(fixit_server.router, prefix="/api/fixit", tags=["fixit"])

    @app.get("/fixit", include_in_schema=False)
    def fixit_redirect():
        return RedirectResponse("/fixit/")

    @app.get("/fixit/", include_in_schema=False)
    def fixit_page():
        return fixit_server.index_response()

    @app.get("/fixit/eval-upload", include_in_schema=False)
    def fixit_eval_page(k: str = ""):
        fixit_server._check_key(k)
        return FileResponse(FIXIT_STATIC / "eval_upload.html", headers={"Cache-Control": "no-store"})

    app.mount("/fixit/static", StaticFiles(directory=FIXIT_STATIC), name="fixit-static")

    @app.get("/api/health")
    def health():
        return {"ok": True, "queue_monitor": {"gemini_ready": bool(settings.api_key), "observer": settings.observer},
                "fixit": {"identify_model": fixit_server.gemini.IDENTIFY_MODEL,
                          "gate_model": fixit_server.gemini.DECISION_MODEL}}

    @app.get("/api/timeline")
    def timeline(limit: Annotated[int, Query(ge=1, le=500)] = 100):
        return app.state.journal.timeline(limit)

    static = ROOT / "frontend" / "dist"
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="dashboard")
    return app


app = create_app()
