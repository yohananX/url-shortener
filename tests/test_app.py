"""Tests for the URL shortener (Flask test client, stdlib unittest)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

# Make the project root importable no matter how the tests are launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

JSON = {"Accept": "application/json"}


class ShortenerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)  # start from a brand-new database
        self.app = create_app(database=self.db_path)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def shorten(self, payload: dict):
        """POST a JSON payload to the shorten API."""
        return self.client.post("/api/shorten", json=payload, headers=JSON)

    # ------------------------------------------------------------------
    # Phase 1
    # ------------------------------------------------------------------
    def test_shorten_success(self) -> None:
        resp = self.shorten({"url": "https://example.com/some/long/path"})

        self.assertEqual(resp.status_code, 201)
        data = resp.get_json()
        for key in ("code", "short_url", "original_url", "created_at", "clicks"):
            self.assertIn(key, data)
        self.assertEqual(data["original_url"], "https://example.com/some/long/path")
        self.assertTrue(data["short_url"].endswith("/" + data["code"]))
        self.assertEqual(data["clicks"], 0)
        self.assertEqual(len(data["code"]), 6)

    def test_shorten_rejects_non_http_scheme(self) -> None:
        resp = self.shorten({"url": "javascript:alert(1)"})

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_shorten_rejects_missing_url(self) -> None:
        resp = self.shorten({})

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_shorten_rejects_url_without_host(self) -> None:
        resp = self.shorten({"url": "https://"})

        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_custom_code_is_used_verbatim(self) -> None:
        resp = self.shorten({"url": "https://example.com", "custom_code": "my-link_1"})

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["code"], "my-link_1")

    def test_custom_code_conflict_returns_409(self) -> None:
        first = self.shorten({"url": "https://a.example.com", "custom_code": "taken"})
        self.assertEqual(first.status_code, 201)

        second = self.shorten({"url": "https://b.example.com", "custom_code": "taken"})

        self.assertEqual(second.status_code, 409)
        self.assertIn("error", second.get_json())

    def test_invalid_custom_code_returns_400(self) -> None:
        for bad in ("ab", "has space", "bad!", "x" * 21):
            with self.subTest(custom_code=bad):
                resp = self.shorten({"url": "https://example.com", "custom_code": bad})
                self.assertEqual(resp.status_code, 400)
                self.assertIn("error", resp.get_json())

    def test_generated_codes_are_unique(self) -> None:
        codes = set()
        for i in range(30):
            resp = self.shorten({"url": f"https://example.com/{i}"})
            self.assertEqual(resp.status_code, 201)
            codes.add(resp.get_json()["code"])

        self.assertEqual(len(codes), 30)

    def test_redirect_increments_clicks(self) -> None:
        code = self.shorten({"url": "https://example.com/landing"}).get_json()["code"]

        first = self.client.get(f"/{code}")
        second = self.client.get(f"/{code}")

        for resp in (first, second):
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.headers["Location"], "https://example.com/landing")

        links = self.client.get("/api/links", headers=JSON).get_json()["links"]
        self.assertEqual(links[0]["clicks"], 2)

    def test_unknown_code_returns_404_json_for_api_clients(self) -> None:
        resp = self.client.get("/does-not-exist", headers=JSON)

        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.get_json())

    def test_unknown_code_returns_friendly_html_for_browsers(self) -> None:
        resp = self.client.get("/does-not-exist")

        self.assertEqual(resp.status_code, 404)
        self.assertIn(b"404", resp.data)

    def test_homepage_renders_form(self) -> None:
        resp = self.client.get("/")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"<form", resp.data)
        self.assertIn(b'name="url"', resp.data)

    # ------------------------------------------------------------------
    # Phase 2
    # ------------------------------------------------------------------
    def test_form_submission_shows_the_shortened_link(self) -> None:
        resp = self.client.post(
            "/shorten", data={"url": "https://example.com/x"}, follow_redirects=True
        )

        self.assertEqual(resp.status_code, 200)
        code = self.client.get("/api/links", headers=JSON).get_json()["links"][0]["code"]
        self.assertIn(code.encode(), resp.data)

    def test_form_submission_rejects_bad_url(self) -> None:
        resp = self.client.post("/shorten", data={"url": "not-a-url"})

        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"alert", resp.data)

    def test_api_links_returns_recent_links(self) -> None:
        for i in range(3):
            self.shorten({"url": f"https://example.com/{i}"})

        data = self.client.get("/api/links", headers=JSON).get_json()

        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["links"]), 3)
        for link in data["links"]:
            for key in ("code", "original_url", "created_at", "clicks"):
                self.assertIn(key, link)
        # newest first
        self.assertEqual(data["links"][0]["original_url"], "https://example.com/2")

    def test_api_links_respects_limit(self) -> None:
        for i in range(5):
            self.shorten({"url": f"https://example.com/{i}"})

        data = self.client.get("/api/links?limit=2", headers=JSON).get_json()

        self.assertEqual(len(data["links"]), 2)
        self.assertEqual(data["count"], 2)

    def test_api_links_rejects_bad_limit(self) -> None:
        for bad in ("abc", "0", "1000"):
            with self.subTest(limit=bad):
                resp = self.client.get(f"/api/links?limit={bad}", headers=JSON)
                self.assertEqual(resp.status_code, 400)
                self.assertIn("error", resp.get_json())


if __name__ == "__main__":
    unittest.main()
