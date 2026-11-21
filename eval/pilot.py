"""Run two Gemini vision calls on a bounded clip and record the returned results."""

import argparse
import asyncio
import json
import tempfile
from dataclasses import replace
from pathlib import Path

import httpx

from backend.app.contracts import Box
from backend.app.media import Frame, VideoFrames, prepare
from backend.app.models import Budget, GeminiVision, ProviderError
from backend.app.settings import ROOT, Settings


async def pilot(video: Path, at_ms: int, settings: Settings) -> dict:
    result = {"observer": settings.observer, "verifier": settings.verifier, "clip": video.name, "stages": []}
    with tempfile.TemporaryDirectory(prefix="cafe-pilot-") as directory:
        media = Path(directory) / "media"
        source = await asyncio.to_thread(prepare, video, media, "pilot", "Pilot", "upload")
        if not 0 <= at_ms < source.duration_ms:
            raise ValueError("The pilot timestamp must fall inside the video.")
        frames = VideoFrames(source, media)
        async with httpx.AsyncClient() as client:
            vision = GeminiVision(replace(settings, max_calls_process=2), client)
            budget = Budget(2)
            history: list[dict] = []
            for phase, count in [("observe", 4), ("verify", 6)]:
                samples = frames.between(max(0, at_ms - 4000), at_ms, count)
                if phase == "verify" and video.resolve() == ROOT / "demo" / "counter.mp4":
                    center = samples[-1]
                    samples.insert(-1, Frame(center.ms, center.path, Box(x1=0.56, y1=0.23, x2=0.89, y2=0.66)))
                if not samples:
                    raise ValueError("No frame available at pilot time.")
                try:
                    checked = await vision.inspect(samples, history, phase == "verify", budget)
                except ProviderError as error:
                    result["stages"].append(dict(phase=phase, code=error.code, error=str(error),
                                                 calls=error.calls, elapsed_ms=error.elapsed_ms,
                                                 tokens=error.tokens, diagnostic=error.diagnostic))
                    break
                result["stages"].append(dict(
                    phase=phase, sampled_ms=[frame.ms for frame in samples], calls=checked.calls,
                    elapsed_ms=checked.elapsed_ms, observation=checked.scene.model_dump(), tokens=checked.tokens,
                    normalization_notes=list(checked.normalizations),
                ))
                history.append(dict(at_ms=samples[-1].ms, queue_min=checked.scene.queue_min,
                                    queue_max=checked.scene.queue_max, summary=checked.scene.summary))
            result["requests"] = budget.used
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=ROOT / "demo" / "counter.mp4")
    parser.add_argument("--at-ms", type=int, default=8000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    if not settings.api_key:
        parser.exit(2, "GitHub Actions or the local backend needs a GEMINI_API_KEY secret.\n")
    try:
        result = asyncio.run(pilot(args.video.resolve(), args.at_ms, settings))
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for stage in result["stages"]:
        if "error" in stage:
            parser.exit(1, f"{stage['phase']}: {stage['error']}\n")
        print(f"{stage['phase']}: valid response in {stage['elapsed_ms']} ms.")
    print(f"Gemini request attempts: {result['requests']}")


if __name__ == "__main__":
    main()
