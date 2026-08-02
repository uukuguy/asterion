"""Provider-free command boundary tests for DCI Pathlight recovery."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.applications.dci_agent_lite.cli import main
from asterion.capabilities.dci.implementation.pathlight.conversion import (
    recovered_run_to_evaluation_bundle,
    recovered_run_to_experiment,
)
from asterion.capabilities.dci.implementation.pathlight.recovery import (
    DciRecoveredRun,
    write_recovered_run,
)
from asterion.pathlight.evaluation import write_evaluation_bundle
from asterion.pathlight.experiment import write_experiment_bundle
from tests.test_dci_pathlight_diagnosis import _DATASETS, _run


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


def _write_recovery_triad(root: Path, run: DciRecoveredRun) -> None:
    root.mkdir(mode=0o700)
    experiment = recovered_run_to_experiment(run)
    evaluations = recovered_run_to_evaluation_bundle(run)
    write_recovered_run(run, root / "pathlight-dci-recovery.json")
    write_experiment_bundle(experiment, root / "pathlight-experiment.json")
    write_evaluation_bundle(
        root / "pathlight-evaluations.json",
        evaluations.evaluations,
        evaluations.metric_contracts,
    )


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

    def test_recover_rolls_back_partial_publication_and_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            evidence = _private_fixture(root)
            output = root / "output"
            output.mkdir(mode=0o700)
            arguments = [
                "pathlight", "recover", "--instance", "dci.bright.biology@1.0.0",
                "--evidence-root", str(evidence), "--output-root", str(output),
            ]
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch(
                "asterion.applications.dci_agent_lite.pathlight_cli.write_experiment_bundle",
                side_effect=RuntimeError("SENTINEL_PRIVATE_PATH"),
            ):
                code = main(arguments, stdout=stdout, stderr=stderr)
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "asterion-dci: command failed\n")
            self.assertFalse(any(output.iterdir()))

            self.assertEqual(
                main(arguments, stdout=io.StringIO(), stderr=io.StringIO()), 0
            )

    def test_diagnose_rolls_back_partial_publication_and_can_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            recovery_roots = []
            for index, dataset in enumerate(_DATASETS):
                recovery_root = root / f"recovery-{index}"
                _write_recovery_triad(recovery_root, _run(*dataset))
                recovery_roots.append(recovery_root)
            output = root / "diagnosis"
            output.mkdir(mode=0o700)
            arguments = ["pathlight", "diagnose"]
            for recovery_root in recovery_roots:
                arguments.extend(("--recovery-root", str(recovery_root)))
            arguments.extend(("--output-root", str(output)))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch(
                "asterion.applications.dci_agent_lite.pathlight_cli.write_private_file",
                side_effect=RuntimeError("SENTINEL_PRIVATE_PATH"),
            ):
                code = main(arguments, stdout=stdout, stderr=stderr)
            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "asterion-dci: command failed\n")
            self.assertFalse(any(output.iterdir()))

            self.assertEqual(
                main(arguments, stdout=io.StringIO(), stderr=io.StringIO()), 0
            )


if __name__ == "__main__":
    unittest.main()
