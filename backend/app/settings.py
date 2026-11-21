import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def integer(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def model_id(name: str, default: str) -> str:
    value = os.getenv(name, default).removeprefix("models/")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        raise ValueError(f"{name} must hold a Gemini model ID")
    return value


@dataclass(frozen=True)
class Settings:
    home: Path = ROOT / ".cafe-ops"
    api_key: str = field(default="", repr=False)
    observer: str = "gemini-4-hydrogen"
    verifier: str = "gemini-4-hydrogen"
    thinking_level: str = "LOW"
    timeout: int = 20
    max_calls_run: int = 30
    max_calls_process: int = 100
    window_ms: int = 5000
    cadence_ms: int = 2000
    max_lag_ms: int = 20000
    queue_threshold: int = 4
    persistence_ms: int = 2000

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        observer = model_id("CAFE_OBSERVER_MODEL", "gemini-4-hydrogen")
        level = os.getenv("CAFE_THINKING_LEVEL", "LOW").upper()
        if level not in {"LOW", "MEDIUM", "HIGH", "XHIGH", "OFF"}:
            raise ValueError("CAFE_THINKING_LEVEL must be LOW, MEDIUM, HIGH, XHIGH, or OFF")
        return cls(
            home=Path(os.getenv("CAFE_HOME", str(ROOT / ".cafe-ops"))).expanduser().resolve(),
            api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            observer=observer,
            verifier=model_id("CAFE_VERIFIER_MODEL", observer),
            thinking_level=level,
            timeout=integer("CAFE_GEMINI_TIMEOUT_SECONDS", 20, 3, 90),
            max_calls_run=integer("CAFE_MAX_CALLS_PER_RUN", 30, 1, 500),
            max_calls_process=integer("CAFE_MAX_CALLS_PER_PROCESS", 100, 1, 5000),
            window_ms=integer("CAFE_WINDOW_MS", 5000, 2000, 12000),
            cadence_ms=integer("CAFE_CADENCE_MS", 2000, 750, 10000),
            max_lag_ms=integer("CAFE_MAX_OBSERVATION_LAG_MS", 20000, 1000, 30000),
            queue_threshold=integer("CAFE_QUEUE_THRESHOLD", 4, 2, 30),
            persistence_ms=integer("CAFE_PERSISTENCE_MS", 2000, 500, 20000),
        )
