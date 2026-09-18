"""Tests for the P3 host Protocol + frozen dataclasses (Phase 7, Task 4)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import unittest

from asterion.applications.prime.p3.host import (
    P3AdmissionRefused,
    P3ChildRequest,
    P3Finalization,
    P3RootCall,
    P3RootResult,
    P3RuntimeHost,
)


class TestP3HostProtocol(unittest.TestCase):
    def test_protocol_shape_matches_p4_runtime_host(self) -> None:
        members = {
            name
            for name in dir(P3RuntimeHost)
            if not name.startswith("_")
        }
        # Same four-method shape as P4RuntimeHost, scoped to recursive workflow:
        # validate_runtime_services, run_root, report_admission_refused,
        # wait_finalization.
        self.assertIn("validate_runtime_services", members)
        self.assertIn("run_root", members)
        self.assertIn("report_admission_refused", members)
        self.assertIn("wait_finalization", members)
        # P3 has no recovery surface.
        self.assertNotIn("commit_checkpoint", members)
        self.assertNotIn("wait_recovery", members)
        self.assertNotIn("report_recovery_stopped", members)

    def test_root_call_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P3RootCall)}
        self.assertEqual(
            field_names, {"parent_run_id", "child_request"}
        )

        instance = P3RootCall(parent_run_id="parent-1", child_request=None)
        with self.assertRaises(FrozenInstanceError):
            instance.parent_run_id = "parent-2"  # type: ignore[misc]

    def test_root_result_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P3RootResult)}
        self.assertEqual(
            field_names,
            {
                "root_run_id",
                "root_generation",
                "child_run_id",
                "child_generation",
                "child_result_sha256",
                "joined_result_sha256",
                "depth_reached",
                "refusal_reason",
            },
        )

        instance = P3RootResult(
            root_run_id="root-1",
            root_generation=1,
            child_run_id=None,
            child_generation=None,
            child_result_sha256=None,
            joined_result_sha256="a" * 64,
            depth_reached=1,
            refusal_reason=None,
        )
        with self.assertRaises(FrozenInstanceError):
            instance.root_run_id = "root-2"  # type: ignore[misc]

    def test_child_request_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P3ChildRequest)}
        self.assertEqual(
            field_names,
            {
                "child_run_id",
                "child_identity",
                "parent_run_id",
                "depth",
                "task_kind",
                "payload",
            },
        )

        instance = P3ChildRequest(
            child_run_id="child-1",
            child_identity=None,  # type: ignore[arg-type]
            parent_run_id="parent-1",
            depth=2,
            task_kind="synthetic",
            payload={},
        )
        with self.assertRaises(FrozenInstanceError):
            instance.child_run_id = "child-2"  # type: ignore[misc]

    def test_admission_refused_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P3AdmissionRefused)}
        self.assertEqual(
            field_names,
            {"refusal_reason", "attempted_depth", "attempted_at"},
        )

        for reason in (
            "depth-exceeded",
            "concurrency-exceeded",
            "budget-exceeded",
            "cancelled",
            "session-backend-rejected",
        ):
            with self.subTest(refusal_reason=reason):
                instance = P3AdmissionRefused(
                    refusal_reason=reason,  # type: ignore[arg-type]
                    attempted_depth=3,
                    attempted_at="2026-09-18T00:00:00Z",
                )
                self.assertEqual(instance.refusal_reason, reason)

        instance = P3AdmissionRefused(
            refusal_reason="depth-exceeded",
            attempted_depth=3,
            attempted_at="2026-09-18T00:00:00Z",
        )
        with self.assertRaises(FrozenInstanceError):
            instance.attempted_depth = 4  # type: ignore[misc]

    def test_finalization_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P3Finalization)}
        self.assertEqual(
            field_names, {"terminal_status", "receipt_sha256"}
        )

        for status in ("completed", "refused", "recovery-required"):
            with self.subTest(terminal_status=status):
                instance = P3Finalization(
                    terminal_status=status,  # type: ignore[arg-type]
                    receipt_sha256="a" * 64,
                )
                self.assertEqual(instance.terminal_status, status)

        instance = P3Finalization(
            terminal_status="completed", receipt_sha256=None
        )
        with self.assertRaises(FrozenInstanceError):
            instance.terminal_status = "refused"  # type: ignore[misc]

    def test_finalization_receipt_sha256_optional(self) -> None:
        # Unlike P4, P3 does not require a receipt on completed; the
        # closed set covers "completed" (digest) / "refused" /
        # "recovery-required" (no digest).
        completed = P3Finalization(
            terminal_status="completed", receipt_sha256="a" * 64
        )
        self.assertEqual(completed.receipt_sha256, "a" * 64)

        refused = P3Finalization(terminal_status="refused", receipt_sha256=None)
        self.assertIsNone(refused.receipt_sha256)

        recovery = P3Finalization(
            terminal_status="recovery-required", receipt_sha256=None
        )
        self.assertIsNone(recovery.receipt_sha256)


if __name__ == "__main__":
    unittest.main()
