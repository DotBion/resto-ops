"""Past cases: one durable record per Fix-It diagnosis, Floor Monitor run, or Stress Lab run.

Cases live in the same SQLite journal as runs and the ops timeline (``$CAFE_HOME/operations.sqlite3``),
so they survive restarts and feed the nightly Gemini review (``overnight.py``). Only references to the
input are stored (source id, clip name, scenario), never the media itself.
"""
import json
import re
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .journal import Journal, now_ms

CaseSource = Literal["fixit", "floor", "stress"]
CaseStatus = Literal["ok", "failed", "timeout", "disagreement"]
CaseArea = Literal["kitchen", "front-of-house", "inventory", "other"]
AREAS = ("kitchen", "front-of-house", "inventory", "other")
STATUSES = ("ok", "failed", "timeout", "disagreement")
SOURCES = ("fixit", "floor", "stress")
TIMEOUT_WORDS = re.compile(r"time(d)?\s?out|deadline|did not respond", re.IGNORECASE)


class NewCase(BaseModel):
    """A case reported by a client (VoicePizza server: Fix-It and Stress Lab)."""
    model_config = ConfigDict(extra="forbid")

    source: Literal["fixit", "stress"]
    status: CaseStatus
    title: Annotated[str, Field(min_length=1, max_length=160)]
    # Where in the restaurant the case comes from (Fix-It is used across kitchen, dining room, stockroom).
    area: CaseArea = "other"
    # True when the diagnosis or Shop match is not restaurant/commercial-kitchen relevant.
    domain_miss: bool = False
    input: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, Any] = Field(default_factory=dict)
    latency_ms: Annotated[int, Field(ge=0, le=3_600_000)] | None = None
    error: Annotated[str, Field(max_length=2000)] | None = None
    replay_of: Annotated[str, Field(max_length=100)] | None = None


def ensure_schema(journal: Journal) -> None:
    with journal.connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, status TEXT NOT NULL,
                created_ms INTEGER NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS cases_by_time ON cases(created_ms);
            """
        )


def _small(value: Any, limit: int = 6000) -> Any:
    """Keep stored payloads bounded (model outputs can be long)."""
    text = json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    return {"truncated": True, "preview": text[:limit]}


def save(journal: Journal, case: dict, replace: bool = False) -> dict:
    case = {**case}
    case.setdefault("id", f"{case['source']}-{uuid.uuid4().hex[:16]}")
    case.setdefault("created_ms", now_ms())
    case["models"] = {name: _small(output) for name, output in (case.get("models") or {}).items()}
    verb = "INSERT OR REPLACE" if replace else "INSERT OR IGNORE"
    with journal.connection() as db:
        db.execute(f"{verb} INTO cases(id,source,status,created_ms,payload) VALUES (?,?,?,?,?)",
                   (case["id"], case["source"], case["status"], case["created_ms"], json.dumps(case, default=str)))
    return case


def record(journal: Journal, new: NewCase) -> dict:
    return save(journal, new.model_dump())


def get(journal: Journal, case_id: str) -> dict | None:
    with journal.connection() as db:
        row = db.execute("SELECT payload FROM cases WHERE id=?", (case_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


def listing(journal: Journal, status: str | None = None, source: str | None = None,
            since_ms: int | None = None, limit: int = 100, area: str | None = None) -> list[dict]:
    query, args = "SELECT payload FROM cases WHERE 1=1", []
    if area:
        query += " AND json_extract(payload, '$.area')=?"
        args.append(area)
    if status:
        query += " AND status=?"
        args.append(status)
    if source:
        query += " AND source=?"
        args.append(source)
    if since_ms is not None:
        query += " AND created_ms>=?"
        args.append(since_ms)
    query += " ORDER BY created_ms DESC LIMIT ?"
    args.append(limit)
    with journal.connection() as db:
        rows = db.execute(query, args).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def counts(journal: Journal) -> dict:
    with journal.connection() as db:
        rows = db.execute("SELECT status, source, COUNT(*) AS n FROM cases GROUP BY status, source").fetchall()
        areas = db.execute("SELECT COALESCE(json_extract(payload, '$.area'), 'other') AS a, COUNT(*) AS n "
                           "FROM cases GROUP BY a").fetchall()
        misses = db.execute("SELECT COUNT(*) AS n FROM cases WHERE json_extract(payload, '$.domain_miss')").fetchone()
    out = {"total": 0, "status": {s: 0 for s in STATUSES}, "source": {s: 0 for s in SOURCES},
           "area": {a: 0 for a in AREAS}, "domain_miss": misses["n"]}
    for row in areas:
        out["area"][row["a"]] = out["area"].get(row["a"], 0) + row["n"]
    for row in rows:
        out["total"] += row["n"]
        out["status"][row["status"]] = out["status"].get(row["status"], 0) + row["n"]
        out["source"][row["source"]] = out["source"].get(row["source"], 0) + row["n"]
    return out


# ---- Floor Monitor runs -> cases ------------------------------------------------------------

def _ranges_disagree(a: dict, b: dict) -> bool:
    if a.get("queue_min") is None or b.get("queue_min") is None:
        return False
    return a["queue_max"] < b["queue_min"] or b["queue_max"] < a["queue_min"]


def case_from_run(journal: Journal, run_id: str, replay_of: str | None = None) -> dict | None:
    run = journal.run(run_id)
    if run is None or run["status"] == "running":
        return None
    source = journal.source(run["source_id"])
    events = journal.events(run_id, limit=5000)
    observe = [e["data"] for e in events if e["type"] == "observation" and e["data"].get("phase") == "observe"]
    review = [e["data"] for e in events if e["type"] == "observation" and e["data"].get("phase") == "review"]
    errors = [e["data"] for e in events if e["type"] == "error"]
    tasks = [e["data"] for e in events if e["type"] == "task"]
    reviews = [e["data"] for e in events if e["type"] == "review_completed"]
    if not observe and not errors:
        return None  # stopped before Gemini was asked anything: nothing to learn from

    disagreements = []
    for checked in review:
        before = next((o for o in reversed(observe) if o.get("at_ms") == checked.get("at_ms")), None)
        if before and _ranges_disagree(before, checked):
            disagreements.append({"at_ms": checked["at_ms"],
                                  "observer": [before["queue_min"], before["queue_max"]],
                                  "verifier": [checked["queue_min"], checked["queue_max"]]})
    timeouts = [e for e in errors if e.get("code") == "timeout" or TIMEOUT_WORDS.search(str(e.get("message", "")))]
    if run["status"] in {"failed", "blocked"} or (errors and not observe):
        status = "timeout" if timeouts and len(timeouts) == len(errors) else "failed"
    elif timeouts:
        status = "timeout"
    elif errors:
        status = "failed"
    elif disagreements:
        status = "disagreement"
    else:
        status = "ok"

    def brief(o: dict) -> dict:
        return {"at_ms": o.get("at_ms"), "queue": [o.get("queue_min"), o.get("queue_max")],
                "visibility": o.get("visibility"), "summary": o.get("summary"),
                "people": len(o.get("people") or []), "elapsed_ms": o.get("elapsed_ms")}

    config = run["config"]
    latencies = [o.get("elapsed_ms") or 0 for o in observe + review]
    first_error = errors[0] if errors else None
    peak = max((o.get("queue_max") or 0 for o in observe), default=None)
    label = source.label if source else run["source_id"]
    observer = config.get("observer") or "observer"
    verifier = config.get("verifier") or "verifier"
    if verifier == observer:
        observer, verifier = f"{observer} (observer)", f"{verifier} (verifier)"
    models = {observer: {"role": "line count (observer)", "calls": len(observe),
                         "windows": [brief(o) for o in observe[-12:]]}}
    if review or reviews:
        models[verifier] = {"role": "queue alert verification", "calls": len(review),
                            "reviews": [brief(o) for o in review[-12:]],
                            "outcomes": [r.get("outcome") for r in reviews[-12:]]}
    return {
        "id": f"floor-{run_id}",
        "source": "floor",
        "area": "front-of-house",
        "domain_miss": False,
        "status": status,
        "created_ms": run["created_ms"],
        "title": f"{label} · {len(observe)} windows" + (f" · peak line {peak}" if peak is not None else ""),
        "input": {"run_id": run_id, "source_id": run["source_id"], "label": label,
                  "kind": source.kind if source else None,
                  "duration_ms": source.duration_ms if source else None,
                  "replayable": bool(source and source.kind != "camera")},
        "models": models,
        "tasks": [{"id": t.get("id"), "status": t.get("status"), "action": t.get("action")} for t in tasks[-6:]],
        "disagreements": disagreements[:12],
        "errors": [{"code": e.get("code"), "message": e.get("message"), "at_ms": e.get("at_ms"),
                    "phase": e.get("phase")} for e in errors[:12]],
        "error": f"{first_error.get('code')}: {first_error.get('message')}" if first_error else None,
        "latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        "run_status": run["status"],
        "replay_of": replay_of,
    }


def record_run(journal: Journal, run_id: str, replay_of: str | None = None) -> dict | None:
    case = case_from_run(journal, run_id, replay_of)
    return save(journal, case, replace=True) if case else None


def backfill(journal: Journal, limit: int = 200) -> int:
    """Turn finished runs that predate the cases table into cases (idempotent)."""
    with journal.connection() as db:
        rows = db.execute(
            "SELECT r.id FROM runs r LEFT JOIN cases c ON c.id = 'floor-' || r.id "
            "WHERE r.status != 'running' AND c.id IS NULL ORDER BY r.created_ms DESC LIMIT ?", (limit,),
        ).fetchall()
    made = 0
    for row in rows:
        case = case_from_run(journal, row["id"])
        if case:
            save(journal, case)
            made += 1
    return made
