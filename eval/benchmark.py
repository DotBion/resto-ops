"""Compare queue decisions on identical inputs. Reviewed labels are scorer-only."""

import argparse
import asyncio
import hashlib
import itertools
import json
import math
import statistics
import tempfile
from collections import Counter
from pathlib import Path
from typing import Literal

import httpx
from pydantic import Field, model_validator

from backend.app.analysis import Analysis, run_configuration
from backend.app.contracts import Contract, Group, Person
from backend.app.media import FRAME_MS, VideoFrames, prepare
from backend.app.models import Budget, FixtureVision, GeminiVision, ProviderError
from backend.app.settings import ROOT, Settings
from demo.scene import world


class Label(Contract):
    at_ms: int = Field(ge=0)
    queue_count: int | None = Field(ge=0)
    people: list[Person] | None = None
    groups: list[Group] | None = None

    @model_validator(mode="after")
    def validate_members(self):
        actors = {person.id for person in self.people or []}
        grouped = [member for group in self.groups or [] for member in group.members]
        if len(actors) != len(self.people or []) or not set(grouped) <= actors or len(set(grouped)) != len(grouped):
            raise ValueError("reference groups must contain distinct annotated people")
        return self


class AlertWindow(Contract):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class Clip(Contract):
    id: str
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    recording_group: str
    cafe: str
    view: str
    split: Literal["development", "held_out"]
    references: list[Label] = Field(min_length=1)
    reviewed_until_ms: int | None = Field(default=None, ge=1)
    alert_windows: list[AlertWindow] | None = None
    continuous: bool = False

    @model_validator(mode="after")
    def validate_timeline(self):
        times = [ref.at_ms for ref in self.references]
        if times != sorted(set(times)) or any(time % FRAME_MS for time in times):
            raise ValueError(f"{self.id}: label times must increase on the {FRAME_MS} ms grid")
        if self.alert_windows is not None and self.reviewed_until_ms is None:
            raise ValueError("alert scoring requires a reviewed interval")
        previous_end = -1
        for window in self.alert_windows or []:
            if not previous_end < window.start_ms <= window.end_ms <= self.reviewed_until_ms:
                raise ValueError("reviewed alert windows must be ordered and disjoint")
            previous_end = window.end_ms
        return self


class Manifest(Contract):
    name: str
    version: str
    annotation_version: str
    source_url: str
    clips: list[Clip] = Field(min_length=1)

    @model_validator(mode="after")
    def disjoint(self):
        record_splits = {}
        ids = set()
        for clip in self.clips:
            if clip.id in ids:
                raise ValueError("clip IDs must be unique")
            ids.add(clip.id)
            if record_splits.setdefault(clip.recording_group, clip.split) != clip.split:
                raise ValueError("a recording group appears in both splits")
        return self


class SharedObserver:
    """Reuse the stateless first observation so only the strategy changes."""

    def __init__(self, vision):
        self.vision = vision
        self.cached = {}
        self.cache_hits = 0

    async def inspect(self, frames, history, review, budget: Budget):
        if review:
            return await self.vision.inspect(frames, history, True, budget)
        key = tuple(frame.ms for frame in frames)
        if key in self.cached:
            self.cache_hits += 1
        else:
            try:
                self.cached[key] = await self.vision.inspect(frames, [], False, budget)
            except ProviderError as error:
                self.cached[key] = error
        observation = self.cached[key]
        if isinstance(observation, ProviderError):
            raise observation
        return observation


def digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def fixture_manifest() -> Manifest:
    video = ROOT / "demo" / "counter.mp4"
    labels = []
    for at_ms in range(0, 32000, 2000):
        actors, groups = world(at_ms)
        labels.append({
            "at_ms": at_ms, "queue_count": sum(actor.membership == "waiting" for actor in actors),
            "people": [dict(id=actor.id, box=actor.box(), membership=actor.membership) for actor in actors],
            "groups": groups,
        })
    return Manifest.model_validate(dict(
        name="Counter & seating synthetic scenario", version="fixture-v1",
        annotation_version="simulation-v1", source_url="repo:demo/counter.mp4",
        clips=[dict(
            id="counter-demo", path=str(video), sha256=digest(video),
            recording_group="counter-demo", cafe="synthetic", view="overhead",
            split="held_out", references=labels, continuous=True,
            reviewed_until_ms=31999, alert_windows=[dict(start_ms=14000, end_ms=22999)],
        )],
    ))


def iou(a: dict, b: dict) -> float:
    x = max(0, min(a["x2"], b["x2"]) - max(a["x1"], b["x1"]))
    y = max(0, min(a["y2"], b["y2"]) - max(a["y1"], b["y1"]))
    overlap = x * y
    area = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"]) + (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
    return overlap / (area - overlap) if area > overlap else 0.0


def match(pred: list[dict], reference: list[dict]) -> dict[str, str]:
    pairs = sorted(
        ((iou(one["box"], other["box"]), one["id"], other["id"]) for one in pred for other in reference),
        reverse=True,
    )
    mapping, used = {}, set()
    for overlap, pred_id, true_id in pairs:
        if overlap < 0.5:
            break
        if pred_id not in mapping and true_id not in used:
            mapping[pred_id] = true_id
            used.add(true_id)
    return mapping


def pair_set(groups: list[set[str]]) -> set[tuple[str, str]]:
    return {pair for group in groups for pair in itertools.combinations(sorted(group), 2)}


def f1(tp: int, fp: int, fn: int) -> float | None:
    denom = 2 * tp + fp + fn
    return round(2 * tp / denom, 4) if denom else None


def avg(values: list[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def rate(value: float, denom: float) -> float | None:
    return round(value / denom, 4) if denom else None


def summarize(runs: list[tuple[Clip, list[tuple[str, dict]]]]) -> dict:
    counts = Counter()
    tokens = Counter()
    errors = Counter()
    confusion = Counter()
    absolute_errors, latencies, delays, examples = [], [], [], []
    for clip, records in runs:
        decisions = {record["at_ms"]: record for kind, record in records if kind == "decision"}
        observations = {(record["at_ms"], record["phase"]): record
                        for kind, record in records if kind == "observation"}
        for ref in clip.references:
            counts["windows"] += 1
            decision = decisions.get(ref.at_ms)
            scene = None
            if decision:
                phase = "review" if decision["verified"] else "observe"
                scene = observations.get((ref.at_ms, phase))
                if decision["queue_min"] is not None:
                    counts["estimates"] += 1
            scorable = ref.queue_count is not None
            counts["queue_labeled"] += int(scorable)
            predicted = None
            if scorable and decision and decision["queue_min"] is not None:
                lo, hi = decision["queue_min"], decision["queue_max"]
                counts["containing_intervals"] += lo <= ref.queue_count <= hi
                if lo == hi:
                    predicted = lo
                    absolute_errors.append(abs(predicted - ref.queue_count))
            if scorable and predicted != ref.queue_count and len(examples) < 10:
                examples.append(dict(clip=clip.id, at_ms=ref.at_ms, expected=ref.queue_count,
                                     predicted=predicted, note=scene["summary"] if scene else "No observation."))
            if ref.people is not None:
                predicted_people = scene["people"] if scene else []
                reference_people = [person.model_dump() for person in ref.people]
                mapping = match(predicted_people, reference_people)
                counts["matched_people"] += len(mapping)
                counts["reference_people"] += len(reference_people)
                counts["predicted_people"] += len(predicted_people)
                uncertain = {person.id for person in ref.people if person.membership == "uncertain"}
                waiting = {person.id for person in ref.people if person.membership == "waiting"}
                wait_pred = {
                    mapping.get(person["id"], f"prediction:{person['id']}")
                    for person in predicted_people if person["membership"] == "waiting"
                } - uncertain
                if len(uncertain) < len(reference_people):
                    counts["queue_tp"] += len(waiting & wait_pred)
                    counts["queue_fp"] += len(wait_pred - waiting)
                    counts["queue_fn"] += len(waiting - wait_pred)
                if ref.groups is not None:
                    true_groups = [(group.activity, set(group.members)) for group in ref.groups]
                    groups = [
                        (group["activity"], {mapping.get(member, f"prediction:{member}") for member in group["members"]})
                        for group in (scene["groups"] if scene else [])
                    ]
                    true_pairs = pair_set([members for _, members in true_groups])
                    pred_pairs = pair_set([members for _, members in groups])
                    counts["pair_tp"] += len(true_pairs & pred_pairs)
                    counts["pair_fp"] += len(pred_pairs - true_pairs)
                    counts["pair_fn"] += len(true_pairs - pred_pairs)
                    remaining = list(groups)
                    for activity, members in true_groups:
                        # Require the same members to score activity. Missing groups remain visible.
                        found = next((i for i, (_, candidate) in enumerate(remaining) if candidate == members), None)
                        estimate = remaining.pop(found)[0] if found is not None else "missing"
                        confusion[(activity, estimate)] += 1
                    for activity, _ in remaining:
                        confusion[("spurious", activity)] += 1

        if clip.alert_windows is not None:
            used = set()
            counts["reviewed_ms"] += clip.reviewed_until_ms
            counts["target_events"] += len(clip.alert_windows)
            for kind, record in records:
                if kind != "task" or record["action"] != "create":
                    continue
                at_ms = record["created_ms"]
                if at_ms > clip.reviewed_until_ms:
                    continue
                window_index = next((i for i, window in enumerate(clip.alert_windows)
                                     if window.start_ms <= at_ms <= window.end_ms), None)
                if window_index is None:
                    counts["false_alerts"] += 1
                elif window_index in used:
                    counts["duplicate_alerts"] += 1
                else:
                    used.add(window_index)
                    counts["matched_events"] += 1
                    if clip.continuous:
                        delays.append(at_ms - clip.alert_windows[window_index].start_ms)
        for kind, record in records:
            if kind in {"observation", "error"}:
                counts["api_calls"] += record.get("calls", 0)
                counts["sampled_images"] += record.get("frames", 0)
                tokens.update(record.get("tokens", {}))
            if kind == "error":
                errors[record["code"]] += 1
            if kind == "observation" and record["calls"]:
                latencies.append(record["elapsed_ms"])

    successful = counts["matched_events"]
    false = counts["false_alerts"]
    duplicates = counts["duplicate_alerts"]
    return {
        "clips": len(runs), "windows": counts["windows"],
        "queue_count_mae": avg(absolute_errors), "exact_scored": len(absolute_errors),
        "queue_labeled": counts["queue_labeled"], "prediction_coverage": rate(counts["estimates"], counts["windows"]),
        "interval_coverage": rate(counts["containing_intervals"], counts["queue_labeled"]),
        "queue_membership_f1": f1(counts["queue_tp"], counts["queue_fp"], counts["queue_fn"]),
        "group_pair_f1": f1(counts["pair_tp"], counts["pair_fp"], counts["pair_fn"]),
        "actor_recall": rate(counts["matched_people"], counts["reference_people"]),
        "actor_precision": rate(counts["matched_people"], counts["predicted_people"]),
        "alert_precision": rate(successful, successful + false + duplicates),
        "alert_recall": rate(successful, counts["target_events"]),
        "false_alerts": false if counts["reviewed_ms"] else None,
        "duplicate_alerts": duplicates if counts["reviewed_ms"] else None,
        "false_alerts_per_min": rate(false, counts["reviewed_ms"] / 60000),
        "mean_detection_delay_ms": avg(delays),
        "request_p50_ms": statistics.median(latencies) if latencies else None,
        "request_p95_ms": sorted(latencies)[math.ceil(0.95 * len(latencies)) - 1] if latencies else None,
        "api_calls": counts["api_calls"], "sampled_images": counts["sampled_images"],
        "tokens": dict(tokens), "errors": dict(errors), "activity_confusion": [
            {"reference": true, "prediction": pred, "count": number}
            for (true, pred), number in sorted(confusion.items())
        ],
        "errors_to_review": examples,
    }


async def benchmark(manifest: Manifest, base: Path, settings: Settings, provider: str, split: str) -> dict:
    clips = [clip for clip in manifest.clips if clip.split == split]
    if not clips:
        raise ValueError(f"Manifest has no {split} clips.")
    comparisons = {"baseline": [], "agent": []}
    configs = {strategy: run_configuration(settings, provider, strategy, None) for strategy in comparisons}
    cache_hits = 0
    async with httpx.AsyncClient() as client:
        vision = GeminiVision(settings, client) if provider == "gemini" else FixtureVision()
        for clip in clips:
            path = (base / clip.path).resolve()
            if digest(path) != clip.sha256:
                raise ValueError(f"{clip.id}: media checksum mismatch.")
            with tempfile.TemporaryDirectory(prefix="cafe-eval-") as directory:
                media_dir = Path(directory) / "media"
                source = await asyncio.to_thread(prepare, path, media_dir, "eval", "Evaluation video", "upload")
                if (clip.references[-1].at_ms // FRAME_MS >= source.frame_count or
                    (clip.reviewed_until_ms or 0) > source.duration_ms):
                    raise ValueError(f"{clip.id}: reference timeline exceeds decoded video.")
                shared = SharedObserver(vision)
                for strategy, runs in comparisons.items():
                    events = []
                    engine = Analysis(VideoFrames(source, media_dir), shared, configs[strategy])
                    for label in clip.references:
                        await engine.step(label.at_ms, lambda: True, lambda *items: events.extend(items))
                    runs.append((clip, events))
                cache_hits += shared.cache_hits

    return dict(
        dataset=manifest.name, version=manifest.version, annotation_version=manifest.annotation_version,
        split=split, provider=provider, synthetic=manifest.source_url.startswith("repo:demo/"),
        source_url=manifest.source_url, reused_observations=cache_hits,
        actual_remote_attempts=vision.process_budget.used if provider == "gemini" else 0,
        configurations=configs, media_checksums={clip.id: clip.sha256 for clip in clips},
        comparison={strategy: summarize(runs) for strategy, runs in comparisons.items()},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--fixture", action="store_true", help="Use the original synthetic scenario.")
    source_group.add_argument("--manifest", type=Path, help="Reviewed external-footage manifest.")
    parser.add_argument("--gemini", action="store_true", help="Use actual Gemini requests instead of authored fixtures.")
    parser.add_argument("--split", choices=["held_out", "development"], default="held_out")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    try:
        if args.manifest and not args.gemini:
            raise ValueError("External footage requires --gemini.")
        if args.gemini and not settings.api_key:
            raise ValueError("Set GEMINI_API_KEY on the backend environment before running live evaluation.")
        manifest = fixture_manifest() if args.fixture else Manifest.model_validate_json(args.manifest.read_bytes())
        root = ROOT if args.fixture else args.manifest.resolve().parent
        report = asyncio.run(benchmark(manifest, root, settings, "gemini" if args.gemini else "fixture", args.split))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Wrote {args.output} with {report['actual_remote_attempts']} Gemini request attempts.")
        if args.gemini and any(metrics["prediction_coverage"] == 0 for metrics in report["comparison"].values()):
            raise ValueError("No usable Gemini predictions were returned. Open the report to see the errors.")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
