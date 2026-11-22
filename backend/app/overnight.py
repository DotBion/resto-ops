"""Overnight analysis: the biggest model in the stack reviews the last 24 h of past cases.

A scheduler inside the backend process fires every night at CAFE_ANALYSIS_HOUR (default 02:00)
America/New_York. "Run analysis now" calls the same job. Cases are sent in batches of
CAFE_ANALYSIS_BATCH; at most CAFE_ANALYSIS_MAX_CALLS Gemini calls per analysis. Reports are stored
in the journal so the latest one survives restarts.
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import cases as case_store
from .journal import Journal, now_ms
from .models import GEMINI_ENDPOINT
from .settings import Settings

logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/New_York")
DAY_MS = 24 * 60 * 60 * 1000

PROMPT = """You are the overnight reliability reviewer for a restaurant operations app used by restaurant
staff during service: in the kitchen (commercial cooking and refrigeration equipment, mixers, slicers,
fryers, dish machines, smallwares), front-of-house (dining-room furniture, lighting, POS, counters,
service line), inventory/stockroom (shelving, storage, supplies), plumbing and the building.
Three features produce cases:
- fixit: Fix-It Cam. Staff film a broken item; Gemini diagnoses the part, Shop catalog search, a
  Decisions API fit check, and a ranking model pick the top 3 replacement parts.
- floor: Floor Monitor. An observer model counts people waiting in line in café/restaurant video every
  few seconds; a verifier model re-checks when the line reaches the alert threshold.
- stress: Stress Lab. Overlapping multi-language voice orders at escalation levels 1-3; a single-model
  baseline vs. the orchestrated multi-model stack, with recall and latency.
Each case has a status (ok, failed, timeout, disagreement), an area (kitchen, front-of-house,
inventory, other) and domain_miss (flagged by a keyword check).
Judge every Fix-It case for restaurant / commercial-kitchen relevance, including ones marked ok: a
diagnosis or Shop match that is consumer or off-domain (boat or car parts, power-tool or bicycle parts,
household gadgets when a commercial unit was filmed) is a DOMAIN MISS even if the pipeline succeeded;
group domain misses together with a cause that starts with "Domain miss:".
Group the problem cases by root cause (be specific, e.g. "observer timeout on 6-frame windows",
"line at the frame edge counted as 0", "whole light fixture matched instead of the bulb").
Where a group matches one of the KNOWN ISSUES below, name it in the cause and build on it; do not invent
cases for known issues that have no case in this batch.
For each group give a concrete, actionable suggested fix (prompt, threshold, timeout, model, capture
guidance, or code change) and a severity (high, medium, low). Only cite case ids you were given.
Recommend the cases that should become permanent regression tests, preferring restaurant-relevant
ones (commercial kitchen equipment, smallwares, dining-room fixtures, real service lines): the most
representative or costly failures, plus at most two ok cases that guard a fixed behaviour, with a
reason. If every case is ok and in-domain, return no groups and say so in the summary. Be concise."""

# Findings from the Nov 21 2026 failure test (real CAFE and Fix-It clips). Given to the reviewer as context
# and shown in Stress Lab so the provision for them is visible.
KNOWN_ISSUES = [
    {"source": "floor", "issue": "Lines at the frame edge are missed (CAFE 8_187 and 8_27 counted 0)."},
    {"source": "floor", "issue": "Clips shorter than 6 s get a single look (one window at the 6 s cadence)."},
    {"source": "floor", "issue": "Gemini calls time out at the 20 s per-call limit on busy windows."},
    {"source": "fixit", "issue": "Ranking returns an empty top 3 even when offers passed search."},
    {"source": "fixit", "issue": "Tight crops get the wrong parent object (the part's host item is misnamed)."},
    {"source": "fixit", "issue": "Whole light fixtures are matched instead of the bulb."},
    {"source": "fixit", "issue": "A clip with several broken items gets a single diagnosis."},
    {"source": "fixit", "issue": "The 150 MiB ops upload cap overrides Fix-It's own 200 MB limit."},
]

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "groups": {"type": "array", "items": {"type": "object", "properties": {
            "cause": {"type": "string"},
            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
            "sources": {"type": "array", "items": {"type": "string"}},
            "case_ids": {"type": "array", "items": {"type": "string"}},
            "suggested_fix": {"type": "string"},
        }, "required": ["cause", "severity", "case_ids", "suggested_fix"]}},
        "regression_tests": {"type": "array", "items": {"type": "object", "properties": {
            "case_id": {"type": "string"},
            "reason": {"type": "string"},
        }, "required": ["case_id", "reason"]}},
    },
    "required": ["summary", "groups", "regression_tests"],
}


def ensure_schema(journal: Journal) -> None:
    with journal.connection() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS analysis_reports (id TEXT PRIMARY KEY, created_ms INTEGER NOT NULL, "
            "status TEXT NOT NULL, payload TEXT NOT NULL)"
        )


def next_run(now: datetime, hour: int) -> datetime:
    local = now.astimezone(TZ)
    target = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= local:
        target = (local + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return target


def compact(case: dict) -> dict:
    """What the reviewer sees for one case: outcome, model outputs, errors; no media."""
    keep = ("id", "source", "status", "area", "domain_miss", "title", "input", "models", "latency_ms", "error", "errors",
            "disagreements", "replay_of")
    out = {k: case.get(k) for k in keep if case.get(k) not in (None, [], {})}
    out["when"] = datetime.fromtimestamp(case["created_ms"] / 1000, TZ).strftime("%Y-%m-%d %H:%M %Z")
    text = json.dumps(out, default=str)
    if len(text) > 3500:
        out["models"] = {"truncated": text[:2500]}
    return out


class Overnight:
    def __init__(self, journal: Journal, settings: Settings, client: httpx.AsyncClient):
        self.journal, self.settings, self.client = journal, settings, client
        ensure_schema(journal)
        self.running: asyncio.Task | None = None
        self.started_ms: int | None = None
        self.calls_used = 0  # process lifetime, informational

    # ---- status --------------------------------------------------------------------------
    def latest(self) -> dict | None:
        with self.journal.connection() as db:
            row = db.execute("SELECT payload FROM analysis_reports ORDER BY created_ms DESC LIMIT 1").fetchone()
        return json.loads(row["payload"]) if row else None

    def status(self) -> dict:
        s = self.settings
        upcoming = next_run(datetime.now(TZ), s.analysis_hour)
        return {
            "schedule": {"enabled": s.analysis_enabled, "hour": s.analysis_hour, "timezone": "America/New_York",
                         "label": f"Nightly at {s.analysis_hour % 12 or 12}:00 {'AM' if s.analysis_hour < 12 else 'PM'} ET",
                         "next_run_ms": int(upcoming.timestamp() * 1000) if s.analysis_enabled else None},
            "model": s.analysis_model, "thinking_level": s.analysis_thinking, "window_hours": 24,
            "batch_size": s.analysis_batch, "max_calls": s.analysis_max_calls,
            "gemini_ready": bool(s.api_key),
            "running": bool(self.running and not self.running.done()), "started_ms": self.started_ms,
            "cases": case_store.counts(self.journal),
            "known_issues": KNOWN_ISSUES,
            "cases_last_24h": len(case_store.listing(self.journal, since_ms=now_ms() - DAY_MS, limit=5000)),
            "latest": self.latest(),
        }

    # ---- running -------------------------------------------------------------------------
    def trigger(self, trigger: str) -> bool:
        if self.running and not self.running.done():
            return False
        self.started_ms = now_ms()
        self.running = asyncio.create_task(self._guarded(trigger))
        return True

    async def _guarded(self, trigger: str) -> None:
        try:
            await self.run(trigger)
        except Exception:  # never let the scheduler die
            logger.exception("Overnight analysis failed")

    async def scheduler(self) -> None:
        while True:
            target = next_run(datetime.now(TZ), self.settings.analysis_hour)
            await asyncio.sleep(max(1.0, (target - datetime.now(TZ)).total_seconds()))
            if self.settings.analysis_enabled:
                self.trigger("scheduled")
                if self.running:
                    await asyncio.shield(self.running)
            await asyncio.sleep(61)  # never fire twice in the same minute

    async def run(self, trigger: str) -> dict:
        s = self.settings
        started = now_ms()
        since = started - DAY_MS
        window = case_store.listing(self.journal, since_ms=since, limit=5000)
        report = {"id": uuid.uuid4().hex, "created_ms": started, "trigger": trigger, "model": s.analysis_model,
                  "thinking_level": s.analysis_thinking, "window": {"from_ms": since, "to_ms": started},
                  "cases_total": len(window), "cases_analyzed": 0, "calls": 0, "batches": 0,
                  "summary": "", "groups": [], "regression_tests": [], "errors": []}
        if not window:
            report.update(status="empty", summary="No cases were recorded in the last 24 hours.")
        elif not s.api_key:
            report.update(status="skipped", summary="GEMINI_API_KEY is not set on the backend.")
        else:
            # Failures first so a capped run still covers what matters.
            order = {"failed": 0, "timeout": 1, "disagreement": 2, "ok": 3}
            ranked = sorted(window, key=lambda c: (min(order.get(c["status"], 4), 2 if c.get("domain_miss") else 4),
                                                   -c["created_ms"]))
            batches = [ranked[i:i + s.analysis_batch] for i in range(0, len(ranked), s.analysis_batch)]
            batches = batches[:s.analysis_max_calls]
            known = {c["id"]: c for c in window}
            summaries = []
            for batch in batches:
                try:
                    part = await self.ask(batch)
                except Exception as exc:  # noqa: BLE001 - recorded in the report
                    report["errors"].append(str(exc)[:300])
                    continue
                finally:
                    report["calls"] += 1
                    self.calls_used += 1
                report["batches"] += 1
                report["cases_analyzed"] += len(batch)
                summaries.append(part.get("summary", ""))
                for group in part.get("groups", []):
                    ids = [i for i in group.get("case_ids", []) if i in known]
                    if not ids:
                        continue
                    group["case_ids"] = ids
                    group["sources"] = sorted({known[i]["source"] for i in ids})
                    group["count"] = len(ids)
                    report["groups"].append(group)
                for rec in part.get("regression_tests", []):
                    if rec.get("case_id") in known:
                        rec["title"] = known[rec["case_id"]].get("title")
                        rec["source"] = known[rec["case_id"]]["source"]
                        report["regression_tests"].append(rec)
            rank = {"high": 0, "medium": 1, "low": 2}
            report["groups"].sort(key=lambda g: (rank.get(g.get("severity"), 3), -g["count"]))
            report["summary"] = " ".join(x for x in summaries if x).strip()
            if report["batches"] == 0:
                report["status"] = "failed"
                report["summary"] = report["summary"] or "Gemini could not complete the analysis."
            elif report["cases_analyzed"] < len(window) or report["errors"]:
                report["status"] = "partial"
            else:
                report["status"] = "ok"
        report["finished_ms"] = now_ms()
        report["duration_ms"] = report["finished_ms"] - started
        with self.journal.connection() as db:
            db.execute("INSERT INTO analysis_reports VALUES (?,?,?,?)",
                       (report["id"], started, report["status"], json.dumps(report, default=str)))
        self.journal.log("analysis", "analysis.report", {
            "status": report["status"], "cases": report["cases_analyzed"], "groups": len(report["groups"])})
        return report

    async def ask(self, batch: list[dict]) -> dict:
        s = self.settings
        config = {"responseMimeType": "application/json", "responseJsonSchema": REPORT_SCHEMA,
                  "maxOutputTokens": 8192}
        if s.analysis_thinking != "OFF":
            config["thinkingConfig"] = {"thinkingLevel": s.analysis_thinking}
        body = {"systemInstruction": {"parts": [{"text": PROMPT}]},
                "contents": [{"role": "user", "parts": [{"text": "KNOWN ISSUES:\n" + "\n".join(
                    f"- [{k['source']}] {k['issue']}" for k in KNOWN_ISSUES) + "\n\nCases (JSON):\n" + json.dumps(
                    [compact(c) for c in batch], default=str, ensure_ascii=False)}]}],
                "generationConfig": config}
        started = time.monotonic()
        try:
            response = await self.client.post(f"{GEMINI_ENDPOINT}/{s.analysis_model}:generateContent",
                                              headers={"x-goog-api-key": s.api_key}, json=body,
                                              timeout=s.analysis_timeout)
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"{s.analysis_model} did not respond within {s.analysis_timeout} s.") from exc
        except httpx.RequestError as exc:
            raise RuntimeError("Could not connect to the Gemini API.") from exc
        if response.status_code != 200:
            raise RuntimeError(f"{s.analysis_model} returned HTTP {response.status_code}.")
        document = response.json()
        candidates = document.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini returned no report.")
        text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", [])
                       if not p.get("thought"))
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise RuntimeError("Gemini returned an unreadable report.") from exc
        logger.info("overnight batch of %d analysed in %.1f s", len(batch), time.monotonic() - started)
        return value if isinstance(value, dict) else {}
