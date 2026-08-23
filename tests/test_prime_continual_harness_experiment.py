from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import tools.prime_continual_harness_experiment as experiment
from tools.prime_continual_harness_experiment import (
    PrimeContinualHarnessExperimentError,
    admit_prime_refinement_result,
    recover_prime_continual_harness_bounded,
    run_prime_continual_harness_bounded_probe,
    write_prime_continual_harness_bounded_receipt,
)


def _provider_report(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "status": "PASS",
        "provider_operations": 1,
        "evidence_ids": [f"evidence-input-{index}" for index in range(7)],
        "proposal_grounded": True,
        "host_admitted": True,
        "snapshot_activated": True,
        "usage": {"aggregate_tokens": 8_203, "cost_micros": 0},
    }
    value.update(overrides)
    return value


class TestPrimeContinualHarnessExperiment(unittest.TestCase):
    def test_native_refinement_is_grounded_and_activated_by_host(self) -> None:
        evidence_ids = tuple(f"evidence-input-{index}" for index in range(7))
        result = {
            "id": "refine_20260823000000000",
            "summary": "Grounded harness improvement",
            "rationale": " ".join(evidence_ids),
            "expectedOutcome": "Preserve the verified operating constraint.",
            "scope": "local",
            "harnessStatePath": "/private/harness_state.json",
            "appliedEdits": [
                {
                    "action": "create",
                    "kind": "memory",
                    "id": "bounded-evidence-memory",
                    "applied": True,
                    "after": {
                        "id": "bounded-evidence-memory",
                        "kind": "memory",
                        "title": "Bounded evidence memory",
                        "content": "SENTINEL_PRIVATE_MODEL_BODY",
                        "path": "project/verification",
                        "scope": "local",
                        "reference": {},
                        "arguments": {},
                        "metadata": {"private": "SENTINEL_PRIVATE_METADATA"},
                        "source": "refine",
                        "created_at": "2026-08-23T00:00:00.000Z",
                        "updated_at": "2026-08-23T00:00:00.000Z",
                        "version": 1,
                    },
                }
            ],
        }

        report = admit_prime_refinement_result(result, evidence_ids=evidence_ids)

        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["host_admitted"])
        self.assertTrue(report["snapshot_activated"])
        self.assertNotIn("SENTINEL_PRIVATE_MODEL_BODY", repr(report))
        self.assertNotIn("SENTINEL_PRIVATE_METADATA", repr(report))

    def test_cli_requires_explicit_bounded_provider_opt_in(self) -> None:
        with TemporaryDirectory() as temporary, mock.patch.object(
            experiment, "run_authorized_bounded"
        ) as run:
            self.assertEqual(
                experiment.main(["--private-evidence-root", temporary]), 1
            )
            run.assert_not_called()

    def test_probe_calls_provider_exactly_once_and_requires_evidence(self) -> None:
        calls = 0

        def provider_probe():
            nonlocal calls
            calls += 1
            return _provider_report()

        receipt = run_prime_continual_harness_bounded_probe(
            provider_probe,
            model_selector_digest="a" * 64,
            aggregate_token_limit=150_000,
            cost_limit_micros=500_000,
            deadline_ms=600_000,
        )

        self.assertEqual(calls, 1)
        self.assertEqual(receipt["provider_operations"], 1)
        self.assertEqual(receipt["model_credential_reads"], 1)
        self.assertEqual(receipt["evidence_input_count"], 7)

    def test_probe_rejects_extra_private_or_over_limit_results(self) -> None:
        invalid = (
            _provider_report(raw_output="SENTINEL_PRIVATE_OUTPUT"),
            _provider_report(provider_operations=2),
            _provider_report(usage={"aggregate_tokens": 150_001, "cost_micros": 0}),
            _provider_report(evidence_ids=[]),
            _provider_report(host_admitted=False),
        )
        for report in invalid:
            with self.subTest(keys=tuple(report)), self.assertRaisesRegex(
                PrimeContinualHarnessExperimentError, "bounded probe is invalid"
            ):
                run_prime_continual_harness_bounded_probe(
                    lambda report=report: report,
                    model_selector_digest="a" * 64,
                    aggregate_token_limit=150_000,
                    cost_limit_micros=500_000,
                    deadline_ms=600_000,
                )

    def test_writer_is_exclusive_mode_0600_and_never_overwrites(self) -> None:
        receipt = run_prime_continual_harness_bounded_probe(
            _provider_report,
            model_selector_digest="a" * 64,
            aggregate_token_limit=150_000,
            cost_limit_micros=500_000,
            deadline_ms=600_000,
        )
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_prime_continual_harness_bounded_receipt(root, receipt)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(PrimeContinualHarnessExperimentError):
                write_prime_continual_harness_bounded_receipt(root, receipt)

    def test_post_provider_receipt_failure_recovers_without_second_call(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "native"
            evidence = root / "evidence"
            native.mkdir()
            evidence.mkdir()
            (native / "prime-continual-harness-native-receipt.json").write_text(
                json.dumps({
                    **_provider_report(),
                    "format": "asterion.prime-continual-harness-native/v1",
                    "failure_stage": "public-receipt-projection",
                }),
                encoding="utf-8",
            )

            receipt = recover_prime_continual_harness_bounded(
                native,
                evidence,
                model_selector_digest="a" * 64,
            )

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["provider_operations"], 1)


if __name__ == "__main__":
    unittest.main()
