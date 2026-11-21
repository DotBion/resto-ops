import io
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from .contracts import Box, Source

FRAME_MS = 250
MAX_VIDEO_SECONDS = 600
MAX_UPLOAD_BYTES = 150 * 1024 * 1024
MAX_CAMERA_JPEG_BYTES = 640 * 1024
MAX_CAMERA_FRAMES = 1200
DEMUXERS = "mov,matroska,avi,mpegts,mpeg,flv,ogg,asf"


class MediaError(Exception):
    pass


@dataclass(frozen=True)
class Frame:
    ms: int
    path: Path
    crop: Box | None = None

    def jpeg(self) -> bytes:
        if self.crop is None:
            return self.path.read_bytes()
        rect = self.crop
        with Image.open(self.path) as image:
            left, top = int(rect.x1 * image.width), int(rect.y1 * image.height)
            right = min(image.width, max(left + 1, round(rect.x2 * image.width)))
            bottom = min(image.height, max(top + 1, round(rect.y2 * image.height)))
            result = io.BytesIO()
            image.crop((left, top, right, bottom)).save(result, "JPEG", quality=91)
        return result.getvalue()


def command(args: list[str], timeout: int) -> bytes:
    try:
        result = subprocess.run(args, capture_output=True, check=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise MediaError(f"Install {args[0]} and put it on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError("Video preparation exceeded its time limit.") from exc
    except subprocess.CalledProcessError as exc:
        raise MediaError("Unable to decode this video. Try a local MP4 or WebM file.") from exc
    return result.stdout


def probe(path: Path) -> dict:
    data = command(
        ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
         "-format_whitelist", DEMUXERS, "-select_streams", "v:0", "-show_entries",
         "stream=width,height,duration,duration_ts,time_base:format=duration", "-of", "json", str(path)],
        15,
    )
    try:
        info = json.loads(data)
        video = info["streams"][0]
        duration = float(video.get("duration") or info["format"]["duration"])
        if not (0.25 <= duration <= MAX_VIDEO_SECONDS):
            raise MediaError(f"Use a video between 0.25 seconds and {MAX_VIDEO_SECONDS // 60} minutes.")
        if not (1 < video["width"] <= 8192 and 1 < video["height"] <= 8192):
            raise MediaError("Video dimensions must be between 2 and 8192 pixels.")
        return dict(width=video["width"], height=video["height"], duration_ms=round(duration * 1000))
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise MediaError("The file needs a video stream with a readable duration.") from exc


def prepare(path: Path, destination: Path, source_id: str, label: str, kind: str) -> Source:
    probe(path)
    destination.mkdir(parents=True, exist_ok=False)
    try:
        video = destination / "video.mp4"
        frames = destination / "frames"
        frames.mkdir()
        command(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "2",
             "-protocol_whitelist", "file,pipe", "-format_whitelist", DEMUXERS, "-i", str(path),
             "-map", "0:v:0", "-an", "-sn", "-dn", "-t", str(MAX_VIDEO_SECONDS),
             "-filter_threads", "1",
             "-vf", "setpts=PTS-STARTPTS,fps=12:start_time=0:round=up,"
                    "scale=960:640:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
             "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "24",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)],
            210,
        )
        command(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", "2",
             "-i", str(video), "-filter_threads", "1", "-vf", "select=not(mod(n\\,3))",
             "-fps_mode", "vfr", "-q:v", "4", "-threads", "1", str(frames / "%06d.jpg")],
            100,
        )
        count = sum(1 for _ in frames.glob("*.jpg"))
        if count == 0:
            raise MediaError("Could not extract any video frames.")
        return Source(id=source_id, label=label, kind=kind, frame_count=count, **probe(video))
    except BaseException:
        shutil.rmtree(destination)
        raise


class Frames(Protocol):
    def between(self, start_ms: int, end_ms: int, count: int) -> list[Frame]: ...
    def exact(self, at_ms: int) -> Frame | None: ...


def evenly_spaced(frames: list[Frame], count: int) -> list[Frame]:
    if len(frames) <= count:
        return frames
    if count < 2:
        return frames[-1:]
    return [frames[round(i * (len(frames) - 1) / (count - 1))] for i in range(count)]


class VideoFrames:
    def __init__(self, source: Source, directory: Path):
        self.source = source
        self.directory = directory / "frames"

    def exact(self, at_ms: int) -> Frame | None:
        if at_ms < 0 or at_ms % FRAME_MS or at_ms // FRAME_MS >= self.source.frame_count:
            return None
        path = self.directory / f"{at_ms // FRAME_MS + 1:06d}.jpg"
        return Frame(at_ms, path) if path.is_file() else None

    def between(self, start_ms: int, end_ms: int, count: int) -> list[Frame]:
        first = max(0, (start_ms + FRAME_MS - 1) // FRAME_MS)
        last = min(self.source.frame_count - 1, end_ms // FRAME_MS)
        if first > last:
            return []
        frames = [
            Frame(i * FRAME_MS, self.directory / f"{i + 1:06d}.jpg")
            for i in range(first, last + 1)
        ]
        return evenly_spaced(frames, count)


class CameraFrames:
    def __init__(self, directory: Path):
        self.directory = directory
        self.frames: list[Frame] = []

    def add(self, at_ms: int, jpeg: bytes) -> None:
        if len(self.frames) >= MAX_CAMERA_FRAMES:
            raise MediaError("Camera session is full. Start a new session.")
        if self.frames and at_ms - self.frames[-1].ms < FRAME_MS:
            raise MediaError("Camera frames must advance in time and arrive at most four times per second.")
        try:
            with Image.open(io.BytesIO(jpeg)) as image:
                if image.format != "JPEG" or max(image.size) > 1600:
                    raise MediaError("Camera frames must be JPEGs no larger than 1600 pixels.")
                image.verify()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            raise MediaError("The camera frame could not be decoded.") from exc
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{at_ms}.jpg"
        path.write_bytes(jpeg)
        self.frames.append(Frame(at_ms, path))

    def exact(self, at_ms: int) -> Frame | None:
        path = self.directory / f"{at_ms}.jpg"
        return Frame(at_ms, path) if at_ms >= 0 and path.is_file() else None

    def between(self, start_ms: int, end_ms: int, count: int) -> list[Frame]:
        return evenly_spaced([frame for frame in self.frames if start_ms <= frame.ms <= end_ms], count)
