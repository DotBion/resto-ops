import hashlib
import json
import uuid
from collections import deque
from dataclasses import asdict, dataclass
from typing import Callable

from .contracts import Scene
from .journal import now_ms
from .media import Frame, Frames, evenly_spaced
from .models import PROMPT_VERSION, Budget, ProviderError, Result
from .settings import Settings

SCHEMA_VERSION = "1"
MAX_REVIEWS = 12


@dataclass(frozen=True)
class Policy:
    threshold: int
    persistence_ms: int
    max_gap_ms: int
    cooldown_ms: int = 5000
    update_interval_ms: int = 5000

    @property
    def clear_threshold(self) -> int:
        return max(0, self.threshold - 2)


def run_configuration(settings: Settings, provider: str, strategy: str, threshold: int | None) -> dict:
    policy = Policy(threshold or settings.queue_threshold, settings.persistence_ms,
                    max(settings.cadence_ms * 3, settings.persistence_ms * 2, settings.max_lag_ms))
    data = {
        "provider": provider, "strategy": strategy, "policy": asdict(policy),
        "observer": settings.observer if provider == "gemini" else "authored fixture",
        "verifier": settings.verifier if provider == "gemini" else "authored fixture",
        "schema": SCHEMA_VERSION, "prompt": PROMPT_VERSION, "window_ms": settings.window_ms,
        "cadence_ms": settings.cadence_ms, "max_lag_ms": settings.max_lag_ms,
        "thinking_level": settings.thinking_level, "max_calls": settings.max_calls_run,
    }
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]
    return {**data, "id": fingerprint}


def is_high(scene: Scene, threshold: int) -> bool:
    return (
        scene.visibility == "clear" and scene.queue_min is not None
        and scene.queue_min >= threshold
    )


def is_clear(scene: Scene, threshold: int) -> bool:
    return (
        scene.visibility == "clear" and scene.queue_max is not None
        and scene.queue_max <= threshold
    )


@dataclass
class Streak:
    start_ms: int | None = None
    latest_ms: int | None = None

    def update(self, matches: bool, at_ms: int, max_gap_ms: int) -> int:
        if not matches:
            self.start_ms = self.latest_ms = None
            return 0
        if self.latest_ms is None or at_ms - self.latest_ms > max_gap_ms:
            self.start_ms = at_ms
        self.latest_ms = at_ms
        assert self.start_ms is not None
        return at_ms - self.start_ms


class TaskState:
    def __init__(self, policy: Policy, strategy: str):
        self.policy = policy
        self.strategy = strategy
        self.high = Streak()
        self.clear = Streak()
        self.active: dict | None = None
        self.resolved_ms: int | None = None

    def apply(self, scene: Scene, at_ms: int, evidence: list[int], verified: bool) -> dict | None:
        baseline = self.strategy == "baseline"
        policy = self.policy
        usable = bool(evidence) and max(evidence) >= at_ms - 500
        independently_sampled = verified and len(set(evidence)) >= 2
        high = usable and is_high(scene, policy.threshold)
        clear = usable and is_clear(scene, policy.clear_threshold)
        high_span = self.high.update(high, at_ms, policy.max_gap_ms)
        clear_span = self.clear.update(clear, at_ms, policy.max_gap_ms)
        meta = dict(
            reason=scene.summary, evidence_ms=evidence, updated_ms=at_ms,
            queue_min=scene.queue_min, queue_max=scene.queue_max,
        )
        if self.active:
            if clear and (baseline or (independently_sampled and clear_span >= policy.persistence_ms)):
                task = {**self.active, **meta, "status": "resolved", "action": "resolve"}
                self.active = None
                self.resolved_ms = at_ms
                return task
            if high and at_ms - self.active["updated_ms"] >= policy.update_interval_ms:
                self.active = {**self.active, **meta, "action": "update"}
                return self.active
            return None
        cooled = self.resolved_ms is None or at_ms - self.resolved_ms >= policy.cooldown_ms
        if cooled and high and (baseline or (independently_sampled and high_span >= policy.persistence_ms)):
            self.active = dict(
                id=uuid.uuid4().hex[:12], kind="queue_attention", status="open", action="create",
                created_ms=at_ms, **meta,
            )
            return self.active
        return None

    def interrupt_streaks(self) -> None:
        self.high = Streak()
        self.clear = Streak()

    def acknowledge(self, task_id: str) -> dict | None:
        if self.active is None or self.active["id"] != task_id or self.active["status"] != "open":
            return None
        self.active = {**self.active, "status": "acknowledged", "action": "acknowledge"}
        return self.active


def observed_scene(result: Result, frames: list[Frame]) -> tuple[Scene, list[int]]:
    scene = result.scene
    allowed = [frames[n - 1].ms for n in scene.evidence_frames if n <= len(frames)]
    return scene, sorted(set(allowed))


def review_input(frames: Frames, first: list[Frame], scene: Scene, recent: list[dict],
                 at_ms: int, window_ms: int) -> tuple[str, list[Frame], dict]:
    request = scene.inspection
    tool = request.tool if request else "inspect_frames"
    start = max(0, at_ms - window_ms)
    details = {}
    if tool == "compare_observations":
        start = max(0, at_ms - 2 * window_ms)
        details["compared_ms"] = [item["at_ms"] for item in recent[-3:]]
    dense = frames.between(start, at_ms, 8)
    if tool == "inspect_region" and request and request.frame and request.region:
        if request.frame <= len(first) and len(dense) >= 1:
            selected = first[request.frame - 1]
            dense = evenly_spaced(dense, 5)
            # Keep a full final frame after the crop so returned boxes have one coordinate system.
            crop = Frame(selected.ms, selected.path, request.region)
            earlier = sorted([*dense[:-1], crop], key=lambda frame: frame.ms)
            if crop.ms <= dense[-1].ms:
                details = {"crop_ms": selected.ms, "region": request.region.model_dump()}
                return tool, [*earlier, dense[-1]], details
        tool = "inspect_frames"
    return tool, dense, details


class Analysis:
    """Shared observation and task logic for the dashboard and offline evaluation."""

    def __init__(self, source: Frames, vision, config: dict):
        self.source = source
        self.vision = vision
        self.config = config
        self.strategy = config["strategy"]
        self.policy = Policy(**config["policy"])
        self.tasks = TaskState(self.policy, self.strategy)
        self.budget = Budget(config["max_calls"])
        self.history: deque[dict] = deque(maxlen=8)
        self.reviews = 0

    async def step(self, at_ms: int, is_current: Callable[[], bool],
                   emit: Callable[..., None]) -> str | None:
        started_ms = now_ms()
        window = self.config["window_ms"]
        observe_frames = self.source.between(max(0, at_ms - window), at_ms, 6)
        if not observe_frames:
            emit(("error", dict(code="no_frames", message="No frame is available at this playback position.",
                                at_ms=at_ms, phase="observe")))
            return None

        async def analyze(frames: list[Frame], review: bool, history: list[dict]) -> Result | None:
            phase = "review" if review else "observe"
            try:
                return await self.vision.inspect(frames, history, review, self.budget)
            except ProviderError as exc:
                emit(("error", dict(
                    code=exc.code, message=str(exc), at_ms=at_ms, phase=phase, calls=exc.calls,
                    tokens=exc.tokens, frames=len(frames), elapsed_ms=exc.elapsed_ms,
                )))
                return None

        result = await analyze(observe_frames, False, [])
        if result is None:
            self.tasks.interrupt_streaks()
            return "missing"

        def payload(output: Result, frames: list[Frame], phase: str, current: bool) -> dict:
            scene, evidence = observed_scene(output, frames)
            return dict(
                **scene.model_dump(), phase=phase, at_ms=at_ms,
                first_frame_ms=frames[0].ms, frame_ms=frames[-1].ms,
                sampled_ms=sorted({frame.ms for frame in frames}),
                evidence_ms=evidence, current=current, frames=output.frames,
                calls=output.calls, elapsed_ms=output.elapsed_ms, tokens=output.tokens,
                completed_ms=now_ms(), step_started_ms=started_ms,
                normalization_notes=list(output.normalizations),
            )

        observation = payload(result, observe_frames, "observe", is_current())
        emit(("observation", observation))
        if not observation["current"]:
            self.tasks.interrupt_streaks()
            return "stale"

        scene = result.scene
        evidence = observation["evidence_ms"]
        verified = False
        review_note = None
        expects_review = (
            self.strategy == "agent" and self.reviews < MAX_REVIEWS and (
                (self.tasks.active is None and (
                    (scene.queue_max is not None and scene.queue_max >= self.policy.threshold)
                    or (scene.queue_max is None and scene.inspection is not None)
                )) or (self.tasks.active is not None and is_clear(scene, self.policy.clear_threshold))
            )
        )
        if expects_review:
            self.reviews += 1
            prior = list(self.history)
            tool, frames, details = review_input(self.source, observe_frames, scene, prior, at_ms, window)
            emit(("review_started", dict(tool=tool, at_ms=at_ms, **details)))
            checked = await analyze(frames, True, [*prior[-3:], self.memory(observation)])
            if checked is not None:
                review = payload(checked, frames, "review", is_current())
                emit(("observation", review))
                if review["current"]:
                    scene, evidence = checked.scene, review["evidence_ms"]
                    observation = review
                    verified = True
                    review_note = scene.summary
            if not is_current():
                self.tasks.interrupt_streaks()
                emit(("review_completed", dict(at_ms=at_ms, tool=tool, outcome="stale",
                                               summary="Playback moved beyond this review.")))
                return "stale"

        actionable_evidence = [] if expects_review and not verified else evidence
        task = self.tasks.apply(scene, observe_frames[-1].ms, actionable_evidence, verified)
        self.history.append(self.memory(observation))
        events = []
        if expects_review:
            if task:
                outcome = task["action"]
            elif not verified or scene.visibility == "uncertain" or not evidence:
                outcome = "insufficient_evidence"
            elif is_high(scene, self.policy.threshold):
                outcome = "awaiting_persistence"
            else:
                outcome = "hold" if not self.tasks.active else "monitor"
            events.append(("review_completed", dict(
                tool=tool, at_ms=at_ms, outcome=outcome,
                evidence_ms=evidence if verified else [],
                summary=review_note or "The additional evidence could not be verified.",
            )))
        events.append(("decision", dict(
            at_ms=at_ms, frame_ms=observation["frame_ms"], queue_min=scene.queue_min,
            queue_max=scene.queue_max, visibility=scene.visibility,
            evidence_ms=evidence, verified=verified, elapsed_ms=now_ms() - started_ms,
        )))
        if task:
            events.append(("task", task))
        emit(*events)
        return "ok"

    @staticmethod
    def memory(observation: dict) -> dict:
        return {key: observation[key] for key in ("at_ms", "queue_min", "queue_max", "visibility", "summary")}
