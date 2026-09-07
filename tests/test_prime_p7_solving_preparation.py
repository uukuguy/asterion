"""Independent preparation lock for the bounded P7 solving route."""

from __future__ import annotations

from importlib import resources
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace

from asterion.applications.prime_agent.operator import p7_solving_preparation


class TestPrimeP7SolvingPreparation(unittest.TestCase):
    def test_missing_locked_image_is_built_then_reinspected(self) -> None:
        image = p7_solving_preparation.p7_solving_preparation_lock()["image"]
        calls: list[list[str]] = []

        def runner(argv, **_kwargs):
            calls.append(argv)
            if len(calls) == 1:
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"missing")
            return SimpleNamespace(returncode=0, stdout=(image["digest"] + "\n").encode(), stderr=b"")

        self.assertIsInstance(
            p7_solving_preparation._prepare_image(Path.cwd(), image, runner), str
        )
        self.assertEqual(calls[1][1:3], ["--host", "unix:///var/run/docker.sock"])
        self.assertIn("build", calls[1])
    def test_packaged_lock_has_closed_sorted_resource_sets(self) -> None:
        lock = p7_solving_preparation.p7_solving_preparation_lock()
        self.assertEqual(lock["format"], "asterion.prime-p7-solving-preparation-lock/v1")
        self.assertEqual(lock["gateway_outputs"], sorted(set(lock["gateway_outputs"])))
        self.assertEqual(lock["source_inputs"], sorted(set(lock["source_inputs"])))

    def test_solving_lock_has_no_runtime_authority_values(self) -> None:
        raw = resources.files(
            "asterion.applications.prime_agent.operator.resources"
        ).joinpath("prime-p7-solving-preparation-lock.json").read_text()
        self.assertEqual(json.loads(raw), p7_solving_preparation.p7_solving_preparation_lock())
        self.assertFalse(any(term in raw.lower() for term in (
            "credential", "command", "executable", "environment", "prompt\"",
        )))

    def test_wheel_contains_outputs_and_clean_install_discovers_provider(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temporary:
            dist = Path(temporary) / "dist"
            subprocess.run(
                ("uv", "build", "--wheel", "--out-dir", str(dist), "."),
                cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            import zipfile
            with zipfile.ZipFile(next(dist.glob("*.whl"))) as wheel:
                names = set(wheel.namelist())
            expected = {
                "asterion/applications/prime_agent/operator/resources/p7-solving/" + name
                for name in ("p7-solving-session.js", "p7-solving-session.d.ts", "p7-solving-bridge.js", "p7-solving-bridge.d.ts", "p7-solving-main.js", "p7-solving-main.d.ts")
            }
            self.assertTrue(expected <= names)
            venv = Path(temporary) / "venv"
            subprocess.run(("uv", "venv", str(venv)), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            python = venv / "bin" / "python"
            subprocess.run(
                ("uv", "pip", "install", "--python", str(python), str(next(dist.glob("*.whl")))),
                check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            probe = (
                "from importlib import resources; "
                "from asterion.applications.discovery import load_application_provider; "
                "assert resources.files('asterion.applications.prime_agent.operator.resources').joinpath('p7-solving/p7-solving-main.js').is_file(); "
                "assert load_application_provider('prime-agent').provider_id == 'prime-agent'"
            )
            subprocess.run(
                (str(python), "-c", probe), cwd=Path(temporary), check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )


if __name__ == "__main__":
    unittest.main()
