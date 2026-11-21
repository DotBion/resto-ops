"""Import selected Café clip folders and their key-frame group labels."""

import argparse
import bisect
import json
import math
import re
from collections import defaultdict
from pathlib import Path

from PIL import Image

from backend.app.media import FRAME_MS, command
from .benchmark import Clip, Manifest, digest

ACTIVITY = {
    "Queueing": "queueing", "Ordering": "ordering", "Eating/Drinking": "eating",
    "Working/Studying": "working", "Fighting": "fighting", "TakingSelfie": "selfie",
}
IMAGE_NAME = re.compile(r"frames_(\d+)\.jpg$")
ENCODER_FPS = 12
SOURCE_URL = "https://dk-kim.github.io/CAFE/"


def load_images(clip_path: Path) -> list[tuple[int, Path]]:
    frames = []
    for path in (clip_path / "images").glob("frames_*.jpg"):
        if match := IMAGE_NAME.fullmatch(path.name):
            frames.append((int(match[1]), path))
    if not frames:
        raise ValueError("Clip must contain images/frames_<number>.jpg.")
    return sorted(frames)


def reference(annotation: dict, key_index: int, source_size: tuple[int, int], at_ms: int) -> dict:
    width, height = source_size
    people = []
    group_members = defaultdict(list)
    group_activity = {}
    for index, actor in enumerate(annotation["figures"], 1):
        shape = next((item for item in actor["shapes"] if int(item["frame"]) == key_index), None)
        if shape is None:
            continue
        (x1, y1), (x2, y2) = shape["coordinates"]
        left, right = sorted(max(0.0, min(1.0, float(x) / width)) for x in [x1, x2])
        top, bottom = sorted(max(0.0, min(1.0, float(y) / height)) for y in [y1, y2])
        if left == right or top == bottom:
            continue
        actor_id = str(actor.get("id") or index)
        people.append(dict(id=actor_id, box=dict(x1=left, y1=top, x2=right, y2=bottom), membership="uncertain"))
        group = actor["label"]
        if group == "individual":
            continue
        group_members[group].append(actor_id)
        for attribute in actor.get("attributes", []):
            value = attribute.get("value")
            activity = ACTIVITY.get(value.get("key")) if isinstance(value, dict) else None
            if activity:
                if group in group_activity and group_activity[group] != activity:
                    raise ValueError(f"Conflicting activity labels in group {group}.")
                group_activity[group] = activity
    groups = [
        dict(id=group, members=members, activity=group_activity.get(group, "unknown"))
        for group, members in sorted(group_members.items()) if len(members) >= 2
    ]
    return dict(at_ms=at_ms, queue_count=None, people=people, groups=groups)


def import_clip(clip_path: Path, output_dir: Path, fps: float, split: str, cafe: str,
                view: str, recording_group: str) -> Clip:
    ann = json.loads((clip_path / "ann.json").read_bytes())
    images = load_images(clip_path)
    indices = [index for index, _ in images]
    key_index = int(ann["figures"][0]["shapes"][0]["frame"])
    if key_index not in indices:
        raise ValueError("The annotated key frame is missing from the selected clip.")
    start, end = indices[0], indices[-1]
    key_time_ms = (key_index - start) * 1000 / fps
    aligned_ms = math.ceil(key_time_ms / FRAME_MS) * FRAME_MS
    frame_interval = int(ann.get("framesEach") or 1)
    duration = max((end - start + frame_interval) / fps, (aligned_ms + 250) / 1000)
    if not 0.25 <= duration <= 30:
        raise ValueError("Select a single Café clip with the correct source FPS.")
    key_path = images[indices.index(key_index)][1]
    with Image.open(key_path) as key:
        source_size = key.size

    clip_id = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{clip_path.parent.name}_{clip_path.name}")
    video = output_dir / f"{clip_id}.mp4"
    if video.exists():
        raise ValueError(f"{video} already exists.")
    output_dir.mkdir(parents=True, exist_ok=True)

    import tempfile

    with tempfile.TemporaryDirectory(prefix="cafe-import-") as directory:
        stage = Path(directory)
        for n in range(math.ceil(duration * ENCODER_FPS)):
            at_ms = n * 1000 / ENCODER_FPS
            intended_index = start + math.floor(at_ms * fps / 1000 + 1e-7)
            if key_time_ms <= at_ms <= aligned_ms:
                intended_index = key_index
            chosen = max(0, bisect.bisect_right(indices, intended_index) - 1)
            (stage / f"{n:05d}.jpg").symlink_to(images[chosen][1].resolve())
        try:
            command([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "1",
                "-framerate", str(ENCODER_FPS), "-i", str(stage / "%05d.jpg"), "-an",
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1", "-c:v", "libx264",
                "-threads", "2", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video),
            ], 60)
        except BaseException:
            video.unlink(missing_ok=True)
            raise

    return Clip.model_validate(dict(
        id=clip_id, path=video.name, sha256=digest(video), recording_group=recording_group,
        cafe=cafe, view=view, split=split, references=[reference(ann, key_index, source_size, aligned_ms)],
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("clip", type=Path, help="Directory containing ann.json and images/.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--fps", required=True, type=float, help="Original recording FPS for the frame numbers.")
    parser.add_argument("--cafe", required=True)
    parser.add_argument("--view", required=True)
    parser.add_argument("--recording-group", required=True)
    parser.add_argument("--split", choices=["development", "held_out"], required=True)
    args = parser.parse_args()
    if not math.isfinite(args.fps) or not 1 <= args.fps <= 120:
        parser.error("Enter the source camera FPS between 1 and 120.")

    try:
        manifest_path = args.manifest.resolve()
        if manifest_path.exists():
            existing = Manifest.model_validate_json(manifest_path.read_bytes()).model_dump()
            for clip in existing["clips"]:
                if clip["recording_group"] == args.recording_group and clip["split"] != args.split:
                    raise ValueError("The recording group is already in the other split.")
        else:
            existing = dict(name="Café selected clips", version="custom-subset-v1",
                            annotation_version="cafe-keyframes-v1", source_url=SOURCE_URL, clips=[])
        imported = import_clip(args.clip.resolve(), manifest_path.parent, args.fps, args.split,
                               args.cafe, args.view, args.recording_group)
        existing["clips"].append(imported.model_dump())
        result = Manifest.model_validate(existing)
        temp_path = manifest_path.with_suffix(".tmp")
        temp_path.write_text(result.model_dump_json(indent=2) + "\n")
        temp_path.replace(manifest_path)
        print(f"Imported {imported.id} at {imported.references[0].at_ms} ms into {manifest_path}.")
        print("Review operational queue membership and count before queue scoring.")
    except (KeyError, IndexError, OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
