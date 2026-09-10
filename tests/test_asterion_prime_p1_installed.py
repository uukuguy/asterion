"""Installed-wheel metadata and selected-only proof for native P1."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RESOURCES = {
    "asterion/applications/prime/assemblies/prime-ipython-coding.json",
    "asterion/capabilities/prime_ipython_coding_native/payload/capability-package.json",
    "asterion/capabilities/prime_ipython_coding_native/payload/capabilities/prime-ipython-coding.json",
}


def _run(command: tuple[str, ...], *, cwd: Path, environment: dict[str, str]):
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


class TestAsterionPrimeP1Installed(unittest.TestCase):
    def test_wheel_contains_resources_and_selects_only_native_provider(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-p1-task7-", dir="/tmp"
        ) as temporary:
            root = Path(temporary).resolve()
            dist = root / "dist"
            dist.mkdir()
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            built = _run(
                ("uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            wheel = next(dist.glob("asterion-*.whl"))
            with zipfile.ZipFile(wheel) as archive:
                names = set(archive.namelist())
                self.assertTrue(RESOURCES <= names)
                entry_points = archive.read(
                    next(
                        name
                        for name in names
                        if name.endswith(".dist-info/entry_points.txt")
                    )
                ).decode("utf-8")
                self.assertIn(
                    "prime.ipython-coding__1.0.0 = asterion.applications.prime:create_provider",
                    entry_points,
                )

            virtual = root / "venv"
            created = _run(
                ("uv", "venv", "--seed", str(virtual)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            python = virtual / "bin" / "python"
            installed = _run(
                (
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--no-deps",
                    str(wheel),
                ),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            script = root / "probe.py"
            script.write_text(
                """
import json
import sys
from importlib import metadata, resources
from asterion.applications.discovery import select_application_provider_id

selected = select_application_provider_id("prime.ipython-coding@1.0.0")
assert selected == "prime-applications"
entry = next(
    item for item in metadata.entry_points(group="asterion.applications")
    if item.name == selected
)
provider = entry.load()()
application = next(
    item for item in provider.applications
    if item.application_id == "prime.ipython-coding"
)
assert application.runtime_ids == ("asterion.prime",)
assert not any(name.startswith("asterion.applications.prime_agent") for name in sys.modules)
root = resources.files("asterion")
paths = (
    root.joinpath("applications/prime/assemblies/prime-ipython-coding.json"),
    root.joinpath("capabilities/prime_ipython_coding_native/payload/capability-package.json"),
    root.joinpath("capabilities/prime_ipython_coding_native/payload/capabilities/prime-ipython-coding.json"),
)
assert all(path.is_file() for path in paths)
print(json.dumps({"application": application.application_id, "provider": selected}, sort_keys=True))
""".strip()
                + "\n",
                encoding="utf-8",
            )
            probed = _run(
                (str(python), "-I", str(script)), cwd=root, environment=environment
            )
            self.assertEqual(probed.returncode, 0, probed.stderr)
            self.assertEqual(
                json.loads(probed.stdout),
                {
                    "application": "prime.ipython-coding",
                    "provider": "prime-applications",
                },
            )


if __name__ == "__main__":
    unittest.main()
