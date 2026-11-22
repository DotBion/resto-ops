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
    verifier: str = "gemini-4-argon"
    thinking_level: str = "LOW"
    timeout: int = 20
    max_calls_run: int = 30
    max_calls_process: int = 100
    window_ms: int = 5000
    cadence_ms: int = 6000
    max_lag_ms: int = 30000
    queue_threshold: int = 4
    persistence_ms: int = 2000
    # Overnight analysis of past cases (see overnight.py). Its calls are capped separately so the
    # nightly review can never use up the queue monitor's per-process budget.
    analysis_enabled: bool = True
    analysis_hour: int = 2
    analysis_model: str = "gemini-4-argon"
    analysis_thinking: str = "HIGH"
    analysis_batch: int = 40
    analysis_max_calls: int = 6
    analysis_timeout: int = 180
    # Host header allow-list. Defaults cover local use plus a cloudflared quick tunnel.
    allowed_hosts: list = field(default_factory=lambda: ["localhost", "127.0.0.1", "testserver", "*.trycloudflare.com"])

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(ROOT / ".env")
        observer = model_id("CAFE_OBSERVER_MODEL", "gemini-4-hydrogen")
        level = os.getenv("CAFE_THINKING_LEVEL", "LOW").upper()
        if level not in {"LOW", "MEDIUM", "HIGH", "XHIGH", "OFF"}:
            raise ValueError("CAFE_THINKING_LEVEL must be LOW, MEDIUM, HIGH, XHIGH, or OFF")
        analysis_level = os.getenv("CAFE_ANALYSIS_THINKING_LEVEL", "HIGH").upper()
        if analysis_level not in {"LOW", "MEDIUM", "HIGH", "XHIGH", "OFF"}:
            raise ValueError("CAFE_ANALYSIS_THINKING_LEVEL must be LOW, MEDIUM, HIGH, XHIGH, or OFF")
        return cls(
            home=Path(os.getenv("CAFE_HOME", str(ROOT / ".cafe-ops"))).expanduser().resolve(),
            api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            observer=observer,
            verifier=model_id("CAFE_VERIFIER_MODEL", "gemini-4-argon"),
            thinking_level=level,
            timeout=integer("CAFE_GEMINI_TIMEOUT_SECONDS", 20, 3, 90),
            max_calls_run=integer("CAFE_MAX_CALLS_PER_RUN", 30, 1, 500),
            max_calls_process=integer("CAFE_MAX_CALLS_PER_PROCESS", 100, 1, 5000),
            window_ms=integer("CAFE_WINDOW_MS", 5000, 2000, 12000),
            cadence_ms=integer("CAFE_CADENCE_MS", 6000, 750, 10000),
            max_lag_ms=integer("CAFE_MAX_OBSERVATION_LAG_MS", 30000, 1000, 60000),
            queue_threshold=integer("CAFE_QUEUE_THRESHOLD", 4, 2, 30),
            persistence_ms=integer("CAFE_PERSISTENCE_MS", 2000, 500, 20000),
            analysis_enabled=os.getenv("CAFE_ANALYSIS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
            analysis_hour=integer("CAFE_ANALYSIS_HOUR", 2, 0, 23),
            analysis_model=model_id("CAFE_ANALYSIS_MODEL", os.getenv("CAFE_VERIFIER_MODEL", "gemini-4-argon")),
            analysis_thinking=analysis_level,
            analysis_batch=integer("CAFE_ANALYSIS_BATCH", 40, 5, 200),
            analysis_max_calls=integer("CAFE_ANALYSIS_MAX_CALLS", 6, 1, 50),
            analysis_timeout=integer("CAFE_ANALYSIS_TIMEOUT_SECONDS", 180, 10, 600),
            allowed_hosts=[h.strip() for h in os.getenv(
                "ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,*.trycloudflare.com").split(",") if h.strip()],
        )
