from __future__ import annotations

import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import tools.prime_long_running_experiment as experiment
from asterion.control.providers.prime.parity_testing import (
    PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS,
)
from tools.prime_long_running_experiment import (
    PrimeLongRunningExperimentError,
    recover_prime_long_running_bounded,
    run_prime_long_running_bounded_probe,
    write_prime_long_running_bounded_receipt,
)


class TestPrimeLongRunningExperiment(unittest.TestCase):
    def test_receipt_stage_failure_recovers_without_another_provider_call(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_root = root / "native-run"
            evidence_root = root / "evidence"
            run_root.mkdir()
            evidence_root.mkdir()
            values = {
                "native-rlm-experiment-receipt.json": {
                    "format": "asterion.prime-native-rlm-receipt/v1",
                    "authority_id": "authority-1",
                    "authority_revision": 1,
                    "configuration_digest": "b" * 64,
                    "terminal": "completed",
                    "child_started": True,
                    "message_delivered": True,
                    "child_deleted": True,
                    "checkpoint_recovered": True,
                    "detach_attached": True,
                    "cancelled": True,
                    "budget_limited": True,
                    "usage": {
                        "controller_tokens": 8_203,
                        "application_tokens": 0,
                        "child_tokens": 0,
                        "aggregate_tokens": 8_203,
                        "cost_micros": 0,
                    },
                    "status": "PASS",
                },
                "native-rlm-model-evidence.json": {
                    "format": "asterion.prime-native-rlm-model-evidence/v1",
                    "configuration_digest": "b" * 64,
                    "status": "PASS",
                    "child_model_selected": True,
                    "generated_program_admitted": True,
                    "recursion_depth_limited": True,
                },
                "bounded-loop-receipt.json": {
                    "status": "PASS",
                    "terminal": "completed",
                    "usage": {"aggregate_tokens": 8_203},
                    "causal_digests": {
                        name: "c" * 64
                        for name in (
                            "application.invoke",
                            "budget.probe",
                            "checkpoint.create",
                            "child.spawn",
                            "session.cancel",
                        )
                    },
                },
                "native-rlm-external-limit.json": {
                    "format": "asterion.prime-native-rlm-external-limit/v1",
                    "stage": "receipt",
                    "status": "External-limited",
                    "failure_class": "observation_unclassified",
                },
            }
            for name, value in values.items():
                (run_root / name).write_text(
                    json.dumps(value),
                    encoding="utf-8",
                )

            report = recover_prime_long_running_bounded(
                run_root,
                evidence_root,
                model_selector_digest="a" * 64,
            )

            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["provider_operations"], 1)
            self.assertEqual(report["usage"]["aggregate_tokens"], 8_203)
            self.assertTrue(
                (evidence_root / "prime-long-running-bounded-receipt.json").is_file()
            )

    def test_cli_requires_exact_provider_opt_in_before_execution(self) -> None:
        with TemporaryDirectory() as temporary, mock.patch.object(
            experiment,
            "run_authorized_prime_long_running_bounded",
        ) as run:
            root = Path(temporary)
            without_opt_in = experiment.main(
                [
                    "--source-root",
                    str(root / "prime"),
                    "--private-evidence-root",
                    str(root / "evidence"),
                ]
            )
            self.assertEqual(without_opt_in, 1)
            run.assert_not_called()

            run.return_value = {
                "status": "PASS",
                "evidence_id": "evidence.long-running." + "a" * 64,
                "provider_operations": 1,
                "model_credential_reads": 1,
                "usage": {"aggregate_tokens": 9_000, "cost_micros": 0},
            }
            with_opt_in = experiment.main(
                [
                    "--authorized-bounded-provider",
                    "--source-root",
                    str(root / "prime"),
                    "--private-evidence-root",
                    str(root / "evidence"),
                ]
            )
            self.assertEqual(with_opt_in, 0)
            run.assert_called_once_with(root / "prime", root / "evidence")

    def test_receipt_writer_persists_only_the_closed_safe_schema(self) -> None:
        receipt = run_prime_long_running_bounded_probe(
            lambda: {
                "status": "PASS",
                "terminal": "completed",
                "provider_operations": 1,
                "usage": {"aggregate_tokens": 9_000, "cost_micros": 0},
            },
            model_selector_digest="a" * 64,
            aggregate_token_limit=150_000,
            cost_limit_micros=500_000,
            deadline_ms=600_000,
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)

            path = write_prime_long_running_bounded_receipt(root, receipt)

            self.assertEqual(path.name, "prime-long-running-bounded-receipt.json")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            serialized = path.read_text(encoding="utf-8")
            self.assertNotIn("SENTINEL", serialized)
            self.assertNotIn("raw_output", serialized)

    def test_probe_calls_provider_once_and_reduces_host_quiescence(self) -> None:
        calls = 0

        def provider_probe():
            nonlocal calls
            calls += 1
            return {
                "status": "PASS",
                "terminal": "completed",
                "provider_operations": 1,
                "usage": {"aggregate_tokens": 9_000, "cost_micros": 0},
            }

        receipt = run_prime_long_running_bounded_probe(
            provider_probe,
            model_selector_digest="a" * 64,
            aggregate_token_limit=150_000,
            cost_limit_micros=500_000,
            deadline_ms=600_000,
        )

        self.assertEqual(calls, 1)
        self.assertEqual(
            receipt["checks"],
            list(PRIME_LONG_RUNNING_BOUNDED_PASS_CHECK_IDS),
        )
        self.assertEqual(receipt["provider_operations"], 1)
        self.assertEqual(receipt["model_credential_reads"], 1)
        self.assertEqual(receipt["usage"]["aggregate_tokens"], 9_000)

    def test_probe_rejects_non_single_or_unbounded_provider_result(self) -> None:
        invalid = (
            {
                "status": "PASS",
                "terminal": "completed",
                "provider_operations": 0,
                "usage": {"aggregate_tokens": 9_000, "cost_micros": 0},
            },
            {
                "status": "PASS",
                "terminal": "completed",
                "provider_operations": 1,
                "usage": {"aggregate_tokens": 150_001, "cost_micros": 0},
            },
            {
                "status": "PASS",
                "terminal": "completed",
                "provider_operations": 1,
                "usage": {"aggregate_tokens": 9_000, "cost_micros": 0},
                "raw_output": "SENTINEL_PRIVATE_OUTPUT",
            },
        )

        for report in invalid:
            with self.subTest(report=report), self.assertRaisesRegex(
                PrimeLongRunningExperimentError,
                "bounded probe is invalid",
            ):
                run_prime_long_running_bounded_probe(
                    lambda report=report: report,
                    model_selector_digest="a" * 64,
                    aggregate_token_limit=150_000,
                    cost_limit_micros=500_000,
                    deadline_ms=600_000,
                )


if __name__ == "__main__":
    unittest.main()
