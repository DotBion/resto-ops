"""Past cases + overnight analysis: storage, floor-run conversion, scheduling, Argon report merge."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from backend.app import cases as case_store
from backend.app.contracts import Source
from backend.app.journal import Journal
from backend.app.main import create_app
from backend.app.overnight import TZ, Overnight, next_run
from backend.app.settings import Settings


def seeded_run(journal: Journal, run_id: str, events: list, status: str = "completed") -> None:
    journal.add_source(Source(id="clip", label="Café clip", kind="cafe", duration_ms=20000,
                              width=64, height=64, frame_count=80))
    journal.start(run_id, "clip", {"observer": "gemini-4-hydrogen", "verifier": "gemini-4-argon"})
    journal.append(run_id, *events)
    journal.finish(run_id, status)


def obs(at, low, high, phase="observe"):
    return ("observation", {"phase": phase, "at_ms": at, "queue_min": low, "queue_max": high,
                            "visibility": "uncertain", "summary": "line", "people": [], "elapsed_ms": 900})


class CaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name) / "j.sqlite3")
        case_store.ensure_schema(self.journal)

    def tearDown(self):
        self.tmp.cleanup()

    def test_floor_run_statuses(self):
        seeded_run(self.journal, "ok1", [obs(5000, 2, 2), obs(11000, 3, 3)])
        seeded_run(self.journal, "dis", [obs(5000, 1, 2), obs(5000, 5, 6, "review")])
        seeded_run(self.journal, "tmo", [obs(5000, 2, 2), ("error", {"code": "timeout", "message": "Gemini did not respond within the configured timeout.", "at_ms": 11000})])
        seeded_run(self.journal, "bad", [("error", {"code": "model", "message": "not found", "at_ms": 0})], "blocked")
        seeded_run(self.journal, "empty", [], "stopped")
        self.assertEqual(case_store.backfill(self.journal), 4)
        self.assertEqual(case_store.backfill(self.journal), 0)
        status = {c["input"]["run_id"]: c["status"] for c in case_store.listing(self.journal)}
        self.assertEqual(status, {"ok1": "ok", "dis": "disagreement", "tmo": "timeout", "bad": "failed"})
        dis = case_store.get(self.journal, "floor-dis")
        self.assertEqual(dis["disagreements"][0]["verifier"], [5, 6])
        self.assertIn("gemini-4-argon", dis["models"])
        self.assertEqual(dis["area"], "front-of-house")
        self.assertNotIn("gemini-4-argon", case_store.get(self.journal, "floor-ok1")["models"])
        self.assertEqual([c["id"] for c in case_store.listing(self.journal, status="timeout")], ["floor-tmo"])

    def test_next_run_is_2am_new_york(self):
        evening = datetime(2026, 11, 21, 18, 41, tzinfo=TZ)
        self.assertEqual(next_run(evening, 2), datetime(2026, 11, 22, 2, 0, tzinfo=TZ))
        early = datetime(2026, 11, 22, 1, 30, tzinfo=TZ)
        self.assertEqual(next_run(early, 2), datetime(2026, 11, 22, 2, 0, tzinfo=TZ))


class OvernightTests(unittest.IsolatedAsyncioTestCase):
    async def test_batches_cap_calls_and_drop_unknown_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / "j.sqlite3")
            case_store.ensure_schema(journal)
            for i in range(12):
                case_store.save(journal, {"id": f"stress-{i}", "source": "stress", "status": "failed" if i < 3 else "ok",
                                          "title": f"Level {i}", "models": {}})
            requests = []

            def respond(request):
                requests.append(json.loads(request.content))
                report = {"summary": "Baseline breaks at 6 speakers.",
                          "groups": [{"cause": "merge of overlapping carts", "severity": "high",
                                      "case_ids": ["stress-0", "stress-1", "made-up"], "suggested_fix": "split by speaker"}],
                          "regression_tests": [{"case_id": "stress-0", "reason": "worst"}, {"case_id": "nope", "reason": "x"}]}
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(report)}]}}]})

            settings = replace(Settings(), api_key="k", analysis_batch=5, analysis_max_calls=2)
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                report = await Overnight(journal, settings, client).run("manual")
            self.assertEqual(len(requests), 2)
            self.assertEqual(report["status"], "partial")
            self.assertEqual(report["cases_analyzed"], 10)
            self.assertEqual(report["groups"][0]["case_ids"], ["stress-0", "stress-1"])
            self.assertEqual({r["case_id"] for r in report["regression_tests"]}, {"stress-0"})
            first_batch = json.loads(requests[0]["contents"][0]["parts"][0]["text"].split("Cases (JSON):\n", 1)[1])
            self.assertEqual([c["status"] for c in first_batch[:3]], ["failed"] * 3)
            self.assertIn("Lines at the frame edge are missed", requests[0]["contents"][0]["parts"][0]["text"])
            self.assertIn("DOMAIN MISS", requests[0]["systemInstruction"]["parts"][0]["text"])
            self.assertEqual(requests[0]["generationConfig"]["thinkingConfig"]["thinkingLevel"], "HIGH")
            latest = Overnight(journal, settings, client).latest()
            self.assertEqual(latest["id"], report["id"])


class ApiTests(unittest.TestCase):
    def test_record_list_filter_and_analysis_status(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(Settings(), home=Path(directory), api_key="")
            with TestClient(create_app(settings)) as client:
                made = client.post("/api/cases", json={"source": "fixit", "status": "timeout", "title": "Mixer clip",
                                                        "models": {"gemini-4-hydrogen": {"error": "timed out"}},
                                                        "latency_ms": 61000, "error": "Diagnosis timed out",
                                                        "area": "kitchen", "domain_miss": True})
                self.assertEqual(made.status_code, 201)
                case_id = made.json()["id"]
                self.assertEqual(client.post("/api/cases", json={"source": "floor", "status": "ok", "title": "x"}).status_code, 422)
                listed = client.get("/api/cases", params={"status": "timeout"}).json()
                self.assertEqual([c["id"] for c in listed["cases"]], [case_id])
                self.assertEqual(listed["counts"]["source"]["fixit"], 1)
                self.assertEqual(listed["counts"]["area"]["kitchen"], 1)
                self.assertEqual(listed["counts"]["domain_miss"], 1)
                self.assertEqual(client.get("/api/cases", params={"area": "inventory"}).json()["cases"], [])
                self.assertEqual(len(client.get("/api/cases", params={"area": "kitchen"}).json()["cases"]), 1)
                self.assertEqual(client.get(f"/api/cases/{case_id}").json()["latency_ms"], 61000)
                self.assertEqual(client.get("/api/cases/nope").status_code, 404)
                self.assertEqual(client.post(f"/api/cases/{case_id}/replay").status_code, 409)
                status = client.get("/api/analysis/latest").json()
                self.assertEqual(status["schedule"]["label"], "Nightly at 2:00 AM ET")
                self.assertEqual(status["model"], "gemini-4-argon")
                self.assertIsNone(status["latest"])
                run = client.post("/api/analysis/run").json()
                self.assertTrue(run["started"])
            with TestClient(create_app(settings)) as client:  # report persisted across restart
                latest = client.get("/api/analysis/latest").json()["latest"]
                self.assertEqual(latest["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
