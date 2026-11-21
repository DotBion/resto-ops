import asyncio
import logging
import time
import uuid

from .analysis import Analysis, run_configuration
from .contracts import NewRun, Source
from .journal import Journal
from .media import CameraFrames, VideoFrames
from .models import FixtureVision, GeminiVision
from .settings import Settings

logger = logging.getLogger(__name__)

TERMINAL_ERRORS = {"access", "model", "request", "budget"}


class RunConflict(Exception):
    pass


class Runner:
    def __init__(self, manager: "Runs", run_id: str, source: Source, config: dict, vision):
        self.manager = manager
        self.id = run_id
        self.source = source
        self.config = config
        directory = manager.settings.home / "media" / source.id
        self.frames = CameraFrames(directory / "frames") if source.kind == "camera" else VideoFrames(source, directory)
        self.analysis = Analysis(self.frames, vision, config)
        self.watermark = -1
        self.last_queued = -1
        self.pending: int | None = None
        self.worker: asyncio.Task | None = None
        self.final = False
        self.status = "running"
        self.terminal_error = False
        self.last_activity = time.monotonic()

    def emit(self, *events: tuple[str, dict]) -> None:
        if self.status != "running":
            return
        self.manager.journal.append(self.id, *events)
        if any(kind == "error" and data.get("code") in TERMINAL_ERRORS for kind, data in events):
            self.terminal_error = True

    def advance(self, at_ms: int, final: bool) -> None:
        if self.status != "running" or self.final:
            raise RunConflict("This run has ended. Start a new run.")
        if self.source.kind != "camera":
            at_ms = min(at_ms, self.source.duration_ms)
        if at_ms < self.watermark:
            raise RunConflict("Playback moved backwards. Start a new run.")
        self.watermark = at_ms
        self.final = final
        self.last_activity = time.monotonic()
        cadence = self.config["cadence_ms"]
        if self.last_queued < 0 or at_ms - self.last_queued >= cadence or (
            final and at_ms - self.last_queued >= cadence // 2
        ):
            self.last_queued = at_ms
            self.pending = at_ms
        if not self.worker and (self.pending is not None or final):
            self.worker = asyncio.create_task(self.work())

    async def work(self) -> None:
        try:
            while self.status == "running" and self.pending is not None:
                target = self.pending
                self.pending = None
                await self.analysis.step(
                    target,
                    lambda: self.status == "running" and self.watermark - target <= self.config["max_lag_ms"],
                    self.emit,
                )
                if self.terminal_error:
                    self.finish("blocked", cancel_worker=False)
            if self.final and self.status == "running":
                self.finish("completed", cancel_worker=False)
        except Exception:
            logger.exception("Analysis worker failed")
            self.emit(("error", {"code": "internal", "message": "Analysis stopped after a local error.",
                                 "at_ms": self.watermark, "phase": "observe"}))
            self.finish("failed", cancel_worker=False)
        finally:
            self.worker = None

    def finish(self, status: str, cancel_worker: bool = True) -> None:
        if self.status != "running":
            return
        self.manager.journal.append(self.id, ("run_status", {"status": status}))
        self.manager.journal.finish(self.id, status)
        self.status = status
        self.pending = None
        self.manager.active.pop(self.id, None)
        if cancel_worker and self.worker:
            self.worker.cancel()

    def acknowledge(self, task_id: str) -> dict | None:
        task = self.analysis.tasks.acknowledge(task_id)
        if task:
            self.emit(("task", task))
        return task


class Runs:
    def __init__(self, journal: Journal, settings: Settings, gemini: GeminiVision):
        self.journal, self.settings, self.gemini = journal, settings, gemini
        self.active: dict[str, Runner] = {}

    def start(self, request: NewRun) -> dict:
        if request.provider == "gemini" and not self.settings.api_key:
            raise RunConflict("Set GEMINI_API_KEY on the backend to start Gemini analysis.")
        for runner in list(self.active.values()):
            if time.monotonic() - runner.last_activity > 180 and runner.worker is None:
                runner.finish("expired")
        if len(self.active) >= 8:
            raise RunConflict("Too many runs are open. Stop a run before starting another.")
        source_id = request.source_id
        if source_id == "camera":
            if request.provider != "gemini":
                raise RunConflict("Camera analysis requires Gemini.")
            source_id = uuid.uuid4().hex
            self.journal.add_source(Source(id=source_id, label="Webcam", kind="camera",
                                           duration_ms=0, width=0, height=0, frame_count=0))
        source = self.journal.source(source_id)
        if source is None or (source.kind == "camera" and request.source_id != "camera"):
            raise KeyError(source_id)
        if request.provider == "fixture" and source.kind != "synthetic":
            raise RunConflict("Authored observations are only available for the bundled synthetic video.")

        run_id = uuid.uuid4().hex
        config = run_configuration(self.settings, request.provider, request.strategy, request.threshold)
        self.journal.start(run_id, source.id, config)
        vision = self.gemini if request.provider == "gemini" else FixtureVision()
        self.active[run_id] = Runner(self, run_id, source, config, vision)
        self.journal.append(run_id, ("run_status", {"status": "running"}))
        return {"id": run_id, "source": source.model_dump(), "config": config, "status": "running"}

    def acknowledge(self, run_id: str, task_id: str) -> dict | None:
        if runner := self.active.get(run_id):
            return runner.acknowledge(task_id)
        for event in reversed(self.journal.events(run_id, limit=5000)):
            if event["type"] != "task" or event["data"]["id"] != task_id:
                continue
            old = event["data"]
            if old["status"] == "open":
                task = {**old, "status": "acknowledged", "action": "acknowledge"}
                self.journal.append(run_id, ("task", task))
                return task
            break
        return None
