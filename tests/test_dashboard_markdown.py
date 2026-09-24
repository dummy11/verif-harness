"""Markdown source identity, asset boundaries and renderer security contracts."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import urllib.error
import urllib.request

from tests import test_dashboard as fixtures


ROOT = Path(__file__).resolve().parents[1]


class MarkdownRendererTest(unittest.TestCase):
    def test_bundled_parser_identity(self) -> None:
        root = ROOT / "verif_harness/vendor/markdown-it"
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertEqual(
            hashlib.sha256((root / manifest["file"]).read_bytes()).hexdigest(),
            manifest["sha256"],
        )

    @unittest.skipUnless(shutil.which("node"), "Node.js required for renderer contracts")
    def test_rendering_and_untrusted_markdown(self) -> None:
        result = subprocess.run(
            ["node", str(ROOT / "tests/dashboard_markdown_unit.cjs")],
            text=True, capture_output=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class MarkdownHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.DashboardTest()
        self.fixture.setUp()

    def tearDown(self) -> None:
        self.fixture.tearDown()

    def test_local_assets_are_authorized_and_allowlisted(self) -> None:
        f = self.fixture
        for path in ("/assets/markdown-it.min.js", "/assets/dashboard-markdown.js"):
            with f.get(path) as response:
                self.assertIn("text/javascript", response.headers["Content-Type"])
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertTrue(response.read())
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(f.url + path.lstrip("/"), timeout=3)
            self.assertEqual(error.exception.code, 403)
        for path in ("/assets/../store.py", "/assets/LICENSE", "/assets/unknown.js"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                f.get(path)
            self.assertEqual(error.exception.code, 404)
        with f.get("/") as response:
            self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
            response.read()

    def test_reading_keeps_markdown_authority_and_rejects_stale_review(self) -> None:
        f = self.fixture
        f.design_minimal_vdoc()
        plan = next(n for w in f.store.dashboard_snapshot()["workstreams"]
                    if w["workstream"] == "VDOC" for n in w["nodes"] if n["plan_review"])
        f.store.complete_node_plan_review(
            plan["id"], plan["plan_review"]["definition_digest"], "test-reviewer", "确认测试文档方案",
        )
        document = f.store.documents("verification_plan.md")[0]
        path = f.root / document["path"]
        content = (ROOT / "tests/dashboard_markdown_fixture.md").read_text(encoding="utf-8")
        path.write_text(content, encoding="utf-8")
        f.store.sync_documents([document["id"]])
        f.register_minimal_vdoc_delivery()
        before = f.store.documents(document["id"])[0]
        delivery = next(n for w in f.store.dashboard_snapshot()["workstreams"]
                        if w["workstream"] == "VDOC" for n in w["nodes"] if n["delivery_review"])
        with f.get("/api/document?selector=" + document["id"]) as response:
            body = json.loads(response.read())
        self.assertEqual(body["content"], content)
        self.assertNotIn("html", body)
        self.assertEqual(before, f.store.documents(document["id"])[0])
        self.assertEqual(path.read_text(encoding="utf-8"), content)
        self.assertEqual(list(path.parent.glob("*.html")), [])
        path.write_text(content + "\n新增的正文内容。\n", encoding="utf-8")
        with f.get("/api/document?selector=" + document["id"]) as response:
            changed = json.loads(response.read())
        self.assertTrue(changed["document"]["content_changed"])
        with self.assertRaises(urllib.error.HTTPError) as error:
            f.post("/api/reviews/document-delivery", {
                "node": delivery["id"],
                "definition_digest": delivery["delivery_review"]["definition_digest"],
                "document_digest": body["document"]["digest"],
                "verdict": "approve", "reviewer": "test-reviewer", "notes": "旧正文审批",
            }, f.server.write_token)
        self.assertEqual(error.exception.code, 400)
        self.assertIn("文档正文已变化", error.exception.read().decode())
        self.assertEqual(f.store.document_delivery_review_state(delivery["id"])["reviews"], [])
        path.unlink()
        with self.assertRaises(urllib.error.HTTPError) as error:
            f.get("/api/document?selector=" + document["id"])
        self.assertEqual(error.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as error:
            f.get("/api/document?selector=../../outside.md")
        self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
