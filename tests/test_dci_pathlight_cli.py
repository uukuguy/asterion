"""Provider-free command boundary tests for DCI Pathlight recovery."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from asterion.applications.dci_agent_lite.cli import main


_FIXTURE = Path(__file__).parent / "fixtures" / "dci" / "pathlight-recovery"
_SOURCE_FILES = ("config.json", "batch-state.json", "summary.json", "analysis.json", "results.jsonl")


def _private_fixture(root: Path) -> Path:
    evidence = root / "evidence"
    shutil.copytree(_FIXTURE, evidence)
    evidence.chmod(0o700)
    for name in _SOURCE_FILES:
        (evidence / name).chmod(0o600)
    config_path = evidence / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    for name in ("summary.json", "results.jsonl"):
        config["artifact_digests"][name] = hashlib.sha256(
            (evidence / name).read_bytes()
        ).hexdigest()
    config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    config_path.chmod(0o600)
    return evidence


class TestDciPathlightCli(unittest.TestCase):
    def test_recover_is_provider_free_and_emits_one_safe_json_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            evidence = _private_fixture(root)
            output = root / "output"
            output.mkdir(mode=0o700)
            stdout, stderr = io.StringIO(), io.StringIO()

            def provider_path_must_not_run(*_args: object, **_kwargs: object) -> int:
                raise AssertionError("provider path was used")

            code = main(
                [
                    "pathlight", "recover", "--instance", "dci.bright.biology@1.0.0",
                    "--evidence-root", str(evidence.absolute()),
                    "--output-root", str(output.absolute()),
                ],
                application_main=provider_path_must_not_run,
                stdout=stdout,
                stderr=stderr,
            )

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertNotIn(str(evidence), stdout.getvalue())
            self.assertEqual(len(stdout.getvalue().splitlines()), 1)
            self.assertEqual(
                set(json.loads(stdout.getvalue())),
                {"case_count", "dataset_digest", "output_bundle_digest"},
            )
            for name in (
                "pathlight-dci-recovery.json",
                "pathlight-experiment.json",
                "pathlight-evaluations.json",
            ):
                path = output / name
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_diagnose_rejects_non_six_recovery_roots_without_path_leak(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            one_root = root / "one"
            one_root.mkdir(mode=0o700)
            stdout, stderr = io.StringIO(), io.StringIO()
            code = main(
                ["pathlight", "diagnose", "--recovery-root", str(one_root)],
                stdout=stdout,
                stderr=stderr,
            )
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "asterion-dci: command failed\n")
            self.assertNotIn(str(one_root), stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
