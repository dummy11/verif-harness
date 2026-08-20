from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "scripts/setup_xverif.py"


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments], cwd=root, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


class SetupXverifTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.assertEqual(git(self.upstream, "init").returncode, 0)
        self.assertEqual(git(self.upstream, "config", "user.name", "Fixture").returncode, 0)
        self.assertEqual(
            git(self.upstream, "config", "user.email", "fixture@example.invalid").returncode, 0
        )
        tools = self.upstream / "tools"
        tools.mkdir()
        managed_tools = [
            "xbit", "xentry", "xloc", "xsva", "xcov", "xdebug", "xwaveform",
        ]
        for tool in managed_tools:
            wrapper = tools / tool
            wrapper.write_text(
                "#!/usr/bin/env sh\nprintf '%s\\n' fixture\n", encoding="utf-8"
            )
            wrapper.chmod(0o755)
        mcp_package = self.upstream / "xverif_mcp/src/xverif_mcp"
        mcp_package.mkdir(parents=True)
        (mcp_package / "__init__.py").write_text("", encoding="utf-8")
        launcher = tools / "xverif-mcp"
        launcher.write_text("#!/usr/bin/env sh\nprintf '%s\\n' fixture-mcp\n", encoding="utf-8")
        launcher.chmod(0o755)
        license_text = "MIT License\n\nfixture\n"
        (self.upstream / "LICENSE").write_text(license_text, encoding="utf-8")
        self.assertEqual(git(self.upstream, "add", "LICENSE", "tools", "xverif_mcp").returncode, 0)
        self.assertEqual(git(self.upstream, "commit", "-m", "fixture").returncode, 0)
        self.commit = git(self.upstream, "rev-parse", "HEAD").stdout.strip()
        self.project = self.root / "project"
        (self.project / "deps").mkdir(parents=True)
        lock = {
            "schema_version": 2,
            "name": "xverif",
            "repository": str(self.upstream),
            "commit": self.commit,
            "license": "MIT",
            "license_file_sha256": hashlib.sha256(license_text.encode()).hexdigest(),
            "tools": managed_tools,
            "mcp": {
                "source_root": "xverif_mcp",
                "python_source_root": "xverif_mcp/src",
                "package": "xverif_mcp",
                "entrypoint": "xverif_mcp.server:main",
                "launcher": "tools/xverif-mcp",
                "requires_python": ">=3.11",
                "dependency": "mcp[cli]",
            },
        }
        (self.project / "deps/xverif.lock.json").write_text(
            json.dumps(lock), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_setup(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(SETUP), "--project-root", str(self.project),
                "--json", *arguments,
            ],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def test_installs_pinned_clean_checkout_and_rechecks(self) -> None:
        installed = self.run_setup()
        self.assertEqual(installed.returncode, 0, installed.stderr)
        payload = json.loads(installed.stdout)
        self.assertEqual(payload["state"], "INSTALLED")
        checkout = self.project / ".deps/xverif"
        self.assertEqual(git(checkout, "rev-parse", "HEAD").stdout.strip(), self.commit)
        checked = self.run_setup("--check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["state"], "READY")

    def test_dirty_checkout_fails_closed(self) -> None:
        self.assertEqual(self.run_setup().returncode, 0)
        (self.project / ".deps/xverif/local.txt").write_text("dirty\n", encoding="utf-8")
        checked = self.run_setup("--check")
        self.assertEqual(checked.returncode, 1)
        payload = json.loads(checked.stdout)
        self.assertEqual(payload["state"], "BLOCKED")
        self.assertIn("managed checkout is dirty or unreadable", payload["blockers"])

    def test_existing_unmanaged_directory_is_not_overwritten(self) -> None:
        destination = self.project / ".deps/xverif"
        destination.mkdir(parents=True)
        marker = destination / "human.txt"
        marker.write_text("preserve\n", encoding="utf-8")
        result = self.run_setup()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve\n")


if __name__ == "__main__":
    unittest.main()
