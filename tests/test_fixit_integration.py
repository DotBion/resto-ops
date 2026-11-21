"""Fix-It Cam mounted inside the restaurant-ops app: routes, page, and shared journal timeline.
No network or Gemini calls: only health, static, the buy-click beacon, and the event sink."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.settings import Settings
from fixit.app import server as fixit_server


class FixItIntegration(unittest.TestCase):
    def test_routes_page_and_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(Settings(), home=Path(directory), api_key="")
            with TestClient(create_app(settings)) as client:
                self.assertEqual(client.get("/api/fixit/health").json()["ok"], True)
                page = client.get("/fixit/")
                self.assertEqual(page.status_code, 200)
                self.assertIn("/api/fixit", page.text)
                self.assertEqual(client.get("/fixit/static/upload.js").status_code, 200)
                self.assertEqual(client.get("/fixit", follow_redirects=False).status_code, 307)
                click = {"path": "checkout_url", "title": "Faucet aerator", "shop": "example.myshopify.com",
                         "price_minor": 499, "currency": "USD", "fit": 0.9}
                self.assertEqual(client.post("/api/fixit/buy-click", json=click).json(), {"ok": True})
                fixit_server.emit("fixit.diagnosis", {"diagnosis": {"item": "faucet", "confidence": 0.8}})
                timeline = client.get("/api/timeline").json()
                kinds = [item["type"] for item in timeline]
                self.assertIn("fixit.buy_click", kinds)
                self.assertIn("fixit.diagnosis", kinds)
                self.assertTrue(all(item["module"] in {"fixit", "queue"} for item in timeline))
            self.assertEqual(fixit_server.EVENT_SINKS, [])

    def test_standalone_fixit_app_keeps_old_paths(self):
        client = TestClient(fixit_server.app)
        self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/static/upload.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
