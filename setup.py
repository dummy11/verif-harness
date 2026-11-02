"""Keep the reviewed runtime resources in the wheel, without optional sources."""
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).parent
RESOURCE_DIRS = ("skills", "scripts", "deps", "templates", "filelists", ".codex", ".kimi-code")


class Build(build_py):
    def run(self):
        super().run()
        bundle = Path(self.build_lib) / "verif_harness" / "_bundle"
        if bundle.exists():
            shutil.rmtree(bundle)
        bundle.mkdir(parents=True)
        for name in RESOURCE_DIRS:
            shutil.copytree(ROOT / name, bundle / name, symlinks=False,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "skills", "local.toml", "mcp.json")
                            if name.startswith(".") else shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("release.json", "LICENSE", "THIRD_PARTY_NOTICES.md"):
            if (ROOT / name).is_file():
                shutil.copy2(ROOT / name, bundle / name)


setup(cmdclass={"build_py": Build})
