import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .contracts import Source


def now_ms() -> int:
    return time.time_ns() // 1_000_000


class Journal:
    def __init__(self, path: Path):
        self.path = path
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY, metadata TEXT NOT NULL, created_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
                    config TEXT NOT NULL, status TEXT NOT NULL, created_ms INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                    kind TEXT NOT NULL, payload TEXT NOT NULL, created_ms INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_by_run ON events(run_id, seq);
                """
            )

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def add_source(self, source: Source) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT OR IGNORE INTO sources VALUES (?, ?, ?)",
                (source.id, source.model_dump_json(), now_ms()),
            )

    def source(self, source_id: str) -> Source | None:
        with self.connection() as db:
            row = db.execute("SELECT metadata FROM sources WHERE id=?", (source_id,)).fetchone()
        return Source.model_validate_json(row["metadata"]) if row else None

    def sources(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT metadata FROM sources ORDER BY created_ms DESC").fetchall()
        return [json.loads(row["metadata"]) for row in rows]

    def start(self, run_id: str, source_id: str, config: dict) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO runs VALUES (?, ?, ?, 'running', ?)",
                (run_id, source_id, json.dumps(config), now_ms()),
            )

    def finish(self, run_id: str, status: str) -> None:
        with self.connection() as db:
            db.execute("UPDATE runs SET status=? WHERE id=? AND status='running'", (status, run_id))

    def interrupt_runs(self) -> None:
        with self.connection() as db:
            db.execute("UPDATE runs SET status='interrupted' WHERE status='running'")

    @staticmethod
    def run_row(row: sqlite3.Row) -> dict:
        return {**dict(row), "config": json.loads(row["config"])}

    def run(self, run_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return self.run_row(row) if row else None

    def runs(self, limit: int = 15) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM runs ORDER BY created_ms DESC LIMIT ?", (limit,)).fetchall()
        return [self.run_row(row) for row in rows]

    def append(self, run_id: str, *events: tuple[str, dict]) -> None:
        with self.connection() as db:
            db.executemany(
                "INSERT INTO events(run_id,kind,payload,created_ms) VALUES (?, ?, ?, ?)",
                [(run_id, kind, json.dumps(payload), now_ms()) for kind, payload in events],
            )

    def events(self, run_id: str, after: int = 0, limit: int = 200) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT seq,kind,payload,created_ms FROM events WHERE run_id=? AND seq>? "
                "ORDER BY seq LIMIT ?", (run_id, after, limit),
            ).fetchall()
        return [
            {"id": row["seq"], "type": row["kind"], "data": json.loads(row["payload"]),
             "created_ms": row["created_ms"]}
            for row in rows
        ]
