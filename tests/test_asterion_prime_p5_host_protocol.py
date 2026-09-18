"""Tests for the P5 host Protocol + frozen dataclasses (Phase 8, Task 4)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import typing
import unittest

from asterion.applications.prime.p5.host import (
    P5Finalization,
    P5LoopCall,
    P5LoopResult,
    P5RuntimeHost,
    P5StoppedResult,
    P5TerminalReason,
)


class TestP5HostProtocol(unittest.TestCase):
    def test_protocol_shape_matches_p3_p4_runtime_host(self) -> None:
        members = {
            name
            for name in dir(P5RuntimeHost)
            if not name.startswith("_")
        }
        # Same four-method shape as P3 / P4's RuntimeHost, scoped to the
        # propose/verify/repair loop: validate_runtime_services, run_loop,
        # report_loop_stopped, wait_finalization.
        self.assertIn("validate_runtime_services", members)
        self.assertIn("run_loop", members)
        self.assertIn("report_loop_stopped", members)
        self.assertIn("wait_finalization", members)
        # P5 has no recovery surface — neither P3's run_root nor
        # P4's commit_checkpoint / wait_recovery belong here.
        self.assertNotIn("run_root", members)
        self.assertNotIn("commit_checkpoint", members)
        self.assertNotIn("wait_recovery", members)
        self.assertNotIn("report_admission_refused", members)
        self.assertNotIn("report_recovery_stopped", members)
        # P5's report_loop_stopped is the analog of P3's
        # report_admission_refused; verify it's present.
        self.assertEqual(
            members.intersection(
                {"report_loop_stopped", "report_admission_refused"}
            ),
            {"report_loop_stopped"},
        )

    def test_terminal_reason_is_closed_five_element_enum(self) -> None:
        # P5TerminalReason is a Literal[...] type alias; resolve its
        # __args__ at runtime to enumerate the closed 5-element set.
        args = set(typing.get_args(P5TerminalReason))
        self.assertEqual(
            args,
            {
                "success",
                "iteration-cap-exceeded",
                "duration-cap-exceeded",
                "no-progress",
                "cancelled",
            },
        )
        self.assertEqual(len(args), 5)

    def test_p5_loop_call_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P5LoopCall)}
        self.assertEqual(field_names, {"root_run_id"})

        instance = P5LoopCall(root_run_id="root-1")
        with self.assertRaises(FrozenInstanceError):
            instance.root_run_id = "root-2"  # type: ignore[misc]

    def test_p5_loop_result_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P5LoopResult)}
        self.assertEqual(
            field_names,
            {
                "root_run_id",
                "root_generation",
                "propose_step_count",
                "verify_step_count",
                "repair_step_count",
                "failed_verify_count",
                "terminal_reason",
                "joined_workspace_digest",
                "receipt_sha256",
            },
        )
        self.assertEqual(len(field_names), 9)

        instance = P5LoopResult(
            root_run_id="root-1",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=1,
            repair_step_count=0,
            failed_verify_count=1,
            terminal_reason="success",
            joined_workspace_digest="a" * 64,
            receipt_sha256="b" * 64,
        )
        with self.assertRaises(FrozenInstanceError):
            instance.root_run_id = "root-2"  # type: ignore[misc]

    def test_p5_stopped_result_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P5StoppedResult)}
        self.assertEqual(
            field_names,
            {
                "terminal_reason",
                "root_run_id",
                "elapsed_ms",
                "last_step_timed_out",
            },
        )
        self.assertEqual(len(field_names), 4)

        instance = P5StoppedResult(
            terminal_reason="iteration-cap-exceeded",
            root_run_id="root-1",
            elapsed_ms=0,
            last_step_timed_out=False,
        )
        with self.assertRaises(FrozenInstanceError):
            instance.elapsed_ms = 1  # type: ignore[misc]

    def test_p5_finalization_is_frozen_with_expected_fields(self) -> None:
        field_names = {f.name for f in fields(P5Finalization)}
        self.assertEqual(
            field_names, {"terminal_status", "receipt_sha256"}
        )
        self.assertEqual(len(field_names), 2)

        for status in ("completed", "stopped", "recovery-required"):
            with self.subTest(terminal_status=status):
                instance = P5Finalization(
                    terminal_status=status,  # type: ignore[arg-type]
                    receipt_sha256="a" * 64,
                )
                self.assertEqual(instance.terminal_status, status)

        instance = P5Finalization(
            terminal_status="completed", receipt_sha256="a" * 64
        )
        with self.assertRaises(FrozenInstanceError):
            instance.terminal_status = "stopped"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()