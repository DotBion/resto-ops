import asyncio
import base64
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.analysis import Analysis, run_configuration
from backend.app.contracts import NewRun, Scene, Source
from backend.app.journal import Journal
from backend.app.main import DEMO_ID, create_app
from backend.app.media import Frame, VideoFrames
from backend.app.models import Budget, FixtureVision, GeminiVision, ProviderError, parse_scene
from backend.app.runs import RunConflict, Runs
from backend.app.settings import Settings
from eval.benchmark import fixture_manifest, iou, match, summarize
from eval.import_cafe import import_clip


def fake_media(root: Path, source: Source) -> VideoFrames:
    directory = root / "media" / source.id
    frames = directory / "frames"
    frames.mkdir(parents=True)
    for i in range(min(source.frame_count, 12)):
        Image.new("RGB", (32, 32), (i * 8, 60, 140)).save(frames / f"{i + 1:06d}.jpg")
    return VideoFrames(source, directory)


class VisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_request_contains_only_supplied_frames_and_budget_counts_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = Source(id="local", label="Frames", kind="upload", duration_ms=3000,
                            width=32, height=32, frame_count=12)
            stream = fake_media(root, source)
            frames = stream.between(500, 1115, 6)
            fixture = (await FixtureVision().inspect(frames, [], False, Budget(2))).scene
            self.assertEqual([frame.ms for frame in frames], [500, 750, 1000])
            requests = []

            def respond(request):
                requests.append(request)
                if len(requests) == 1:
                    return httpx.Response(429)
                return httpx.Response(200, json={
                    "candidates": [{"content": {"parts": [{"text": fixture.model_dump_json()}]}}],
                    "usageMetadata": {"promptTokenCount": 17, "totalTokenCount": 23},
                })

            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                settings = replace(Settings(), api_key="test-key", max_calls_process=2)
                adapter = GeminiVision(settings, client)
                budget = Budget(2)
                result = await adapter.inspect(frames, [], False, budget)
                with self.assertRaises(ProviderError) as error:
                    await adapter.inspect(frames, [], False, budget)
                self.assertEqual(error.exception.code, "budget")

            self.assertEqual(result.calls, 2)
            self.assertEqual(result.tokens["promptTokenCount"], 17)
            self.assertEqual(len(requests), 2)
            sent = json.loads(requests[-1].content)
            self.assertEqual(requests[-1].headers["x-goog-api-key"], "test-key")
            self.assertEqual(sent["generationConfig"]["responseMimeType"], "application/json")
            parts = sent["contents"][0]["parts"]
            payloads = [base64.b64decode(part["inlineData"]["data"]) for part in parts if "inlineData" in part]
            self.assertEqual(payloads, [frame.path.read_bytes() for frame in frames])

    async def test_slow_results_do_not_act_and_pending_windows_coalesce(self):
        class HeldObserver(FixtureVision):
            def __init__(self):
                self.entered = asyncio.Event()
                self.release = asyncio.Event()
                self.targets = []

            async def inspect(self, frames, history, review, budget):
                if not review:
                    self.targets.append(frames[-1].ms)
                    if len(self.targets) == 1:
                        self.entered.set()
                        await self.release.wait()
                return await super().inspect(frames, history, review, budget)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = replace(Settings(), home=root, max_lag_ms=1000)
            source = Source(id="synthetic", label="Demo", kind="synthetic", width=32, height=32,
                            frame_count=128, duration_ms=32000)
            fake_media(root, source)
            journal = Journal(root / "test.sqlite3")
            journal.add_source(source)
            async with httpx.AsyncClient() as client:
                manager = Runs(journal, settings, GeminiVision(settings, client))
                run = manager.start(NewRun(source_id=source.id, provider="fixture", strategy="baseline"))
                runner = manager.active[run["id"]]
                observer = HeldObserver()
                runner.analysis.vision = observer
                runner.advance(6000, False)
                await observer.entered.wait()
                runner.advance(8000, False)
                runner.advance(12000, False)
                with self.assertRaises(RunConflict):
                    runner.advance(10000, False)
                observer.release.set()
                await runner.worker
                self.assertEqual(observer.targets, [6000, 12000])
                events = journal.events(run["id"])
                states = [event["data"]["current"] for event in events if event["type"] == "observation"]
                self.assertEqual(states, [False, True])
                self.assertFalse(any(event["type"] == "task" for event in events))

    async def test_investigation_prevents_one_false_alert_and_resolves_the_sustained_queue(self):
        config = run_configuration(Settings(), "fixture", "agent", None)
        clip = fixture_manifest().clips[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = Source(id="fixture", label="Demo", kind="synthetic", width=960,
                            height=600, frame_count=128, duration_ms=32000)
            stream = fake_media(root, source)
            engine = Analysis(stream, FixtureVision(), config)
            events = []
            for reference in clip.references:
                await engine.step(reference.at_ms, lambda: True, lambda *items: events.extend(items))
            tasks = [record for kind, record in events if kind == "task"]
            self.assertEqual([task["action"] for task in tasks], ["create", "update", "resolve"])
            self.assertEqual(len({task["id"] for task in tasks}), 1)
            self.assertEqual(tasks[0]["created_ms"], 16000)
            self.assertEqual(tasks[-1]["updated_ms"], 30000)
            self.assertTrue(any(record.get("outcome") == "hold" for kind, record in events if kind == "review_completed"))
            summary = summarize([(clip, events)])
            self.assertEqual(summary["false_alerts"], 0)
            self.assertEqual(summary["alert_recall"], 1)
            self.assertAlmostEqual(summary["mean_detection_delay_ms"], 2000)


class MediaTests(unittest.TestCase):
    def test_upload_uses_valid_media_and_cannot_claim_fixture_results(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(Settings(), home=Path(directory), api_key="")
            with TestClient(create_app(settings)) as client:
                config = client.get("/api/config").json()
                self.assertFalse(config["gemini_ready"])
                self.assertEqual(config["demo_id"], DEMO_ID)
                range_response = client.get(f"/api/sources/{DEMO_ID}/video", headers={"Range": "bytes=0-15"})
                self.assertEqual(range_response.status_code, 206)
                self.assertEqual(len(range_response.content), 16)
                self.assertEqual(client.get(f"/api/sources/{DEMO_ID}/frames/101").status_code, 404)
                bad = client.post("/api/sources", files={"video": ("wrong.mp4", b"not video")})
                self.assertEqual(bad.status_code, 422)
                with open(fixture_manifest().clips[0].path, "rb") as file:
                    response = client.post("/api/sources", files={"video": ("clip.mp4", file)},
                                           data={"kind": "cafe"})
                self.assertEqual(response.status_code, 201, response.text)
                upload = response.json()
                self.assertEqual(upload["kind"], "cafe")
                response = client.post("/api/runs", json={"source_id": upload["id"], "provider": "fixture"})
                self.assertEqual(response.status_code, 409)
                response = client.post("/api/runs", json={"source_id": upload["id"], "provider": "gemini"})
                self.assertEqual(response.status_code, 409)

    def test_import_preserves_annotated_group_and_leaves_queue_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "test-source" / "9"
            images = folder / "images"
            images.mkdir(parents=True)
            for i, color in zip([0, 3, 6, 9, 12, 15], ["red", "green", "blue", "yellow", "cyan", "white"]):
                Image.new("RGB", (64, 48), color).save(images / f"frames_{i}.jpg")
            people = [
                dict(id=i, label=label, shapes=[dict(frame=3, coordinates=[[x, 8], [x + 8, 24]])],
                     attributes=[dict(value=dict(key="Queueing"))] if i == 1 else [])
                for i, label, x in [(1, "group 1", 15), (2, "group 1", 25), (3, "individual", 35)]
            ]
            (folder / "ann.json").write_text(json.dumps({"framesEach": 3, "figures": people}))
            result = import_clip(folder, root / "out", 30, "held_out", "one", "left", "source")
            label = result.references[0]
            self.assertEqual(label.at_ms, 250)
            self.assertEqual(label.groups[0].members, ["1", "2"])
            self.assertEqual(label.groups[0].activity, "queueing")
            self.assertIsNone(label.queue_count)
            self.assertTrue(all(actor.membership == "uncertain" for actor in label.people))


class MetricTests(unittest.TestCase):
    def test_invalid_model_evidence_turns_clear_result_into_uncertain(self):
        scene, notes = parse_scene(json.dumps(dict(
            queue_min=4, queue_max=4, visibility="clear", summary="Possibly four.",
            people=[dict(id="invalid", box=dict(x1=0, y1=0, x2=850, y2=500), membership="waiting")],
            groups=[], evidence_frames=[6, 1], inspection=None,
        )), frame_count=4)
        self.assertEqual(scene.visibility, "uncertain")
        self.assertEqual(scene.people, [])
        self.assertEqual(scene.evidence_frames, [1])
        self.assertTrue(notes)

    def test_identity_matching_uses_geometry_and_rejects_duplicate_matches(self):
        box = dict(x1=0.0, y1=0.0, x2=0.5, y2=0.5)
        other = dict(x1=0.6, y1=0.6, x2=1.0, y2=1.0)
        self.assertEqual(iou(box, other), 0)
        self.assertEqual(len(match([dict(id="a", box=box), dict(id="b", box=box)],
                                   [dict(id="reference", box=box), dict(id="elsewhere", box=other)])), 1)

    def test_unknown_cannot_carry_an_exact_clear_estimate(self):
        scene = dict(queue_min=None, queue_max=None, visibility="clear", summary="Occluded",
                     people=[], groups=[], evidence_frames=[], inspection=None)
        with self.assertRaises(ValueError):
            Scene.model_validate(scene)
