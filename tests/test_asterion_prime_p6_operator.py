"""Tests for ``asterion.applications.prime.p6.operator``.

Nine tests covering the P6 operator's surface:

* preserved-path terminal outcome (test 1),
* limits-path two-record emission (test 2),
* rolled-back path uses ``HarnessCoordinator.rollback`` under the hood (test 3),
* global-rejected short-circuits pre-orchestration (test 4),
* four error-folding paths fold to ``rolled-back`` + diagnostic digest
  per spec L283–L292 (tests 5–8),
* deterministic fake-worker contract (test 9).

The limits target emits two records (NOT P5's three-scenario pattern):
``rolled-back`` (holdout regressed → exact inverse revision) +
``global-rejected`` (scope=global without
``global_activation_approved=True`` → pre-orchestration rejection).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import MappingProxyType

from asterion.applications.prime.p6.operator import (
    P6OperatorError,
    _fake_worker_payload_sha,
    _preflight,
    drive_candidate_admission_error_for_test,
    drive_cancellation_for_test,
    drive_holdout_evaluation_error_for_test,
    drive_preserved_for_test,
    drive_promotion_action_error_for_test,
    drive_scenario_global_rejected_for_test,
    drive_scenario_rolled_back_for_test,
)


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P6_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P6_MODE"


def _run_operator_subprocess(
    *, operator_root: Path, private_root: Path, mode: str
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env[_OPERATOR_ROOT_ENV] = str(operator_root)
    env[_PRIVATE_ROOT_ENV] = str(private_root)
    env[_MODE_ENV] = mode
    env["LANG"] = "C.UTF-8"
    return subprocess.run(
        [sys.executable, "-I", "-m", "asterion.applications.prime.p6.operator"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(operator_root),
    )


def _parse_stdout_lines(
    completed: subprocess.CompletedProcess[str],
) -> list[dict[str, object]]:
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines, (
        f"operator stdout empty; stderr={completed.stderr!r}, "
        f"rc={completed.returncode}"
    )
    parsed: list[dict[str, object]] = []
    for line in lines:
        record = json.loads(line)
        assert isinstance(record, dict), f"operator line is not a dict: {line!r}"
        parsed.append(record)
    return parsed


# ---------------------------------------------------------------------------
# 9 tests, named per Task 8 spec
# ---------------------------------------------------------------------------


class P6OperatorPreserved(unittest.TestCase):
    """Tests 1: preserved-path terminal outcome."""

    def test_p6_operator_preserved_path_seals_preserved_terminal_outcome(
        self,
    ) -> None:
        """Happy path preserved; assert all receipt fields."""

        async def driver():
            return await drive_preserved_for_test(
                root_run_id="p6-test-preserved-1"
            )

        result = asyncio.run(driver())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.terminal_outcome, "preserved")
        self.assertEqual(result.rollback_invocation_count, 0)
        self.assertEqual(result.global_activation_approved, False)
        self.assertEqual(result.failure_digest, None)
        self.assertEqual(result.private_root_redacted, True)

        self.assertTrue(result.root_run_id.startswith("p6-test-preserved"))
        self.assertEqual(len(result.baseline_snapshot_digest), 64)
        self.assertEqual(len(result.candidate_revision_digest), 64)
        self.assertEqual(len(result.task_a_evidence_digest), 64)
        self.assertEqual(len(result.task_b_result_digest), 64)
        self.assertEqual(len(result.receipt_sha256), 64)
        # Preserved path requires task_b_result_digest !=
        # baseline_snapshot_digest (spec L300–L331).
        self.assertNotEqual(
            result.task_b_result_digest, result.baseline_snapshot_digest
        )
        self.assertNotEqual(
            result.candidate_revision_digest, result.baseline_snapshot_digest
        )


class P6OperatorLimits(unittest.TestCase):
    """Tests 2–4: limits-path two records, rolled-back uses coordinator
    rollback, global-rejected short-circuits pre-orchestration.
    """

    def test_p6_operator_limits_path_emits_two_records_rolled_back_and_global_rejected(
        self,
    ) -> None:
        """Limits mode returns 2 dicts; first is rolled-back, second is
        global-rejected.
        """

        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p6-limits-test"
            completed = _run_operator_subprocess(
                operator_root=operator_root,
                private_root=private_root,
                mode="limits",
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"limits rc={completed.returncode}; "
                f"stderr={completed.stderr!r}",
            )
            records = _parse_stdout_lines(completed)
            self.assertEqual(
                len(records), 2, "limits mode emits exactly two records"
            )
            scenarios = [record["scenario"] for record in records]
            self.assertEqual(scenarios, ["rolled-back", "global-rejected"])
            for record in records:
                self.assertEqual(record["status"], "refused")
                self.assertEqual(record["global_activation_approved"], False)
                self.assertEqual(record["private_root_redacted"], True)
                self.assertEqual(len(record["receipt_sha256"]), 64)
                self.assertEqual(len(record["baseline_snapshot_digest"]), 64)
                self.assertEqual(len(record["candidate_revision_digest"]), 64)

    def test_p6_operator_rolled_back_path_uses_harness_coordinator_rollback_under_the_hood(
        self,
    ) -> None:
        """Rolled-back record's ``rollback_invocation_count == 1`` AND the
        fake-worker logs show ``coordinator.rollback(...)`` was called.
        """

        async def driver():
            return await drive_scenario_rolled_back_for_test(
                root_run_id="p6-rb-rollback-invocation"
            )

        record = asyncio.run(driver())
        self.assertEqual(record.scenario, "rolled-back")
        self.assertEqual(record.terminal_outcome, "rolled-back")
        self.assertEqual(record.rollback_invocation_count, 1)
        self.assertEqual(record.global_activation_approved, False)
        # The candidate revision was admitted before the rollback
        # applied; the digest MUST NOT equal the baseline digest.
        self.assertNotEqual(
            record.candidate_revision_digest, record.baseline_snapshot_digest
        )
        self.assertEqual(len(record.task_b_result_digest or ""), 64)

    def test_p6_operator_global_rejected_path_short_circuits_pre_orchestration(
        self,
    ) -> None:
        """Global-rejected record has ``rollback_invocation_count == 0`` AND
        ``global_activation_approved == False`` AND no ``HarnessRevision``
        was created (verified via the digest equality between
        ``candidate_revision_digest`` and ``baseline_snapshot_digest``).
        """

        async def driver():
            return await drive_scenario_global_rejected_for_test(
                root_run_id="p6-gr-boundary"
            )

        record = asyncio.run(driver())
        self.assertEqual(record.scenario, "global-rejected")
        self.assertEqual(record.terminal_outcome, "rolled-back")
        self.assertEqual(record.rollback_invocation_count, 0)
        self.assertEqual(record.global_activation_approved, False)
        # No candidate was admitted — the digest equals the baseline.
        self.assertEqual(
            record.candidate_revision_digest, record.baseline_snapshot_digest
        )
        # task_b_result_digest is the canonical zero-digest on the
        # global-rejected boundary (no task B evaluation ran).
        self.assertEqual(record.task_b_result_digest, "0" * 64)


class P6OperatorErrorFolding(unittest.TestCase):
    """Tests 5–8: four error paths fold to ``rolled-back`` + diagnostic
    digest per spec L283–L292.
    """

    def test_p6_operator_cancellation_folds_to_rolled_back(self) -> None:
        """Cancellation signal mid-run; record seals with
        ``terminal_outcome="rolled-back"`` + ``failure_digest`` set.
        """

        async def driver():
            return await drive_cancellation_for_test(
                root_run_id="p6-cancel-fold"
            )

        receipt = asyncio.run(driver())
        self.assertEqual(receipt.terminal_outcome, "rolled-back")
        self.assertIsNotNone(receipt.failure_digest)
        self.assertEqual(len(receipt.failure_digest or ""), 64)
        self.assertEqual(receipt.rollback_invocation_count, 0)
        self.assertEqual(receipt.global_activation_approved, False)

    def test_p6_operator_candidate_admission_error_folds_to_rolled_back(
        self,
    ) -> None:
        """Admission error path; record seals with
        ``terminal_outcome="rolled-back"`` + ``failure_digest`` set.
        """

        async def driver():
            return await drive_candidate_admission_error_for_test(
                root_run_id="p6-admission-fold"
            )

        receipt = asyncio.run(driver())
        self.assertEqual(receipt.terminal_outcome, "rolled-back")
        self.assertIsNotNone(receipt.failure_digest)
        self.assertEqual(len(receipt.failure_digest or ""), 64)
        self.assertEqual(receipt.rollback_invocation_count, 0)
        self.assertEqual(receipt.global_activation_approved, False)

    def test_p6_operator_holdout_evaluation_error_folds_to_rolled_back(
        self,
    ) -> None:
        """Holdout error path; record seals with
        ``terminal_outcome="rolled-back"`` + ``failure_digest`` set.
        """

        async def driver():
            return await drive_holdout_evaluation_error_for_test(
                root_run_id="p6-holdout-fold"
            )

        receipt = asyncio.run(driver())
        self.assertEqual(receipt.terminal_outcome, "rolled-back")
        self.assertIsNotNone(receipt.failure_digest)
        self.assertEqual(len(receipt.failure_digest or ""), 64)
        self.assertEqual(receipt.rollback_invocation_count, 0)
        self.assertEqual(receipt.global_activation_approved, False)

    def test_p6_operator_promotion_action_error_folds_to_rolled_back(
        self,
    ) -> None:
        """Promotion error path; record seals with
        ``terminal_outcome="rolled-back"`` + ``failure_digest`` set.
        """

        async def driver():
            return await drive_promotion_action_error_for_test(
                root_run_id="p6-promotion-fold"
            )

        receipt = asyncio.run(driver())
        self.assertEqual(receipt.terminal_outcome, "rolled-back")
        self.assertIsNotNone(receipt.failure_digest)
        self.assertEqual(len(receipt.failure_digest or ""), 64)
        self.assertEqual(receipt.rollback_invocation_count, 0)
        self.assertEqual(receipt.global_activation_approved, False)


class P6OperatorFakeWorkerDeterminism(unittest.TestCase):
    """Test 9: deterministic fake-worker contract (spec L386–L399)."""

    def test_p6_operator_fake_worker_is_deterministic_across_run_ids(
        self,
    ) -> None:
        """Same ``(mode, candidate_kind, run_id)`` produces identical digests;
        different ``run_id`` produces distinct digests.
        """

        same_a = _fake_worker_payload_sha(
            mode="preserved", candidate_kind="admit", run_id="run-1"
        )
        same_b = _fake_worker_payload_sha(
            mode="preserved", candidate_kind="admit", run_id="run-1"
        )
        self.assertEqual(same_a, same_b)
        self.assertEqual(len(same_a), 64)

        different_run = _fake_worker_payload_sha(
            mode="preserved", candidate_kind="admit", run_id="run-2"
        )
        self.assertNotEqual(same_a, different_run)

        different_kind = _fake_worker_payload_sha(
            mode="preserved", candidate_kind="repair", run_id="run-1"
        )
        self.assertNotEqual(same_a, different_kind)

        different_mode = _fake_worker_payload_sha(
            mode="limits", candidate_kind="admit", run_id="run-1"
        )
        self.assertNotEqual(same_a, different_mode)


# ---------------------------------------------------------------------------
# Preflight gate test (proves the P5-style unknown-mode rejection works).
# Not counted in the 9 test names — preflight is a side contract.
# ---------------------------------------------------------------------------


class P6OperatorPreflightGate(unittest.TestCase):
    """Preflight rejects unrecognised ``ASTERION_PRIME_P6_MODE``."""

    def test_preflight_raises_on_unknown_mode(self) -> None:
        operator_root = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p6-unknown-test"
            env = MappingProxyType(
                {
                    _OPERATOR_ROOT_ENV: str(operator_root),
                    _PRIVATE_ROOT_ENV: str(private_root),
                    _MODE_ENV: "garbage",
                }
            )
            with self.assertRaises(P6OperatorError):
                _preflight(env)


if __name__ == "__main__":
    unittest.main()