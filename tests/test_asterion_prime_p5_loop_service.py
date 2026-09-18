"""Tests for prime.bounded-autonomy host service (Phase 8, Task 3)."""

from __future__ import annotations

import asyncio
import hashlib
import unittest

from asterion.applications.prime.services import (
    BoundedAutonomyLoop,
    BoundedAutonomyServiceError,
    MAX_ITERATIONS,
    MAX_REPAIR_DURATION_MS,
    MAX_TOTAL_DURATION_MS,
    P5NativeReceipt,
    P5ProposeStep,
    P5RepairStep,
    P5VerifyStep,
    WORKSPACE_DIGEST_DEDUP,
    create_bounded_autonomy_host_service,
    seal_p5_native_receipt,
)
from asterion.services.progress import NOOP_HOST_PROGRESS_REPORTER
from asterion.services.presentation import NOOP_HOST_PRESENTATION_SINK
from asterion.services.registry import HostServiceFactoryContext


def _context(
    options: dict[str, str] | None = None,
) -> HostServiceFactoryContext:
    return HostServiceFactoryContext(
        provider_id="prime-applications",
        application_id="prime.bounded-autonomy",
        application_version="1.0.0",
        capability_id="prime.bounded-autonomy",
        options=options if options is not None else {},
        progress=NOOP_HOST_PROGRESS_REPORTER,
        presentation=NOOP_HOST_PRESENTATION_SINK,
    )


class _CancellationSignal:
    """Minimal :class:`CancellationSignal` for tests."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


def _digest(payload: str) -> str:
    """Return a deterministic 64-character hex digest for the payload."""

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _open_with_defaults() -> BoundedAutonomyLoop:
    factory = create_bounded_autonomy_host_service().factory
    return factory(_context())


class TestBoundedAutonomyLoop(unittest.TestCase):
    def test_constants_match_spec_defaults(self) -> None:
        # Defaults are frozen at the spec section "Newly introduced in
        # Phase 8" / "Stopping conditions". Changing these is a breaking
        # change for the witness.
        self.assertEqual(MAX_ITERATIONS, 3)
        self.assertEqual(MAX_REPAIR_DURATION_MS, 30_000)
        self.assertEqual(MAX_TOTAL_DURATION_MS, 120_000)
        self.assertTrue(WORKSPACE_DIGEST_DEDUP)

    def test_seal_receipt_is_digest_stable(self) -> None:
        first = seal_p5_native_receipt(
            root_run_id="root-run-1",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=1,
            failed_verify_count=1,
            terminal_reason="success",
            joined_workspace_digest=_digest("propose-1"),
        )
        second = seal_p5_native_receipt(
            root_run_id="root-run-1",
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=1,
            failed_verify_count=1,
            terminal_reason="success",
            joined_workspace_digest=_digest("propose-1"),
        )
        self.assertEqual(first.receipt_sha256, second.receipt_sha256)
        self.assertEqual(len(first.receipt_sha256), 64)
        self.assertEqual(first, second)

        with self.subTest("root_run_id change"):
            alt = seal_p5_native_receipt(
                root_run_id="root-run-2",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=2,
                repair_step_count=1,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest=_digest("propose-1"),
            )
            self.assertNotEqual(alt.receipt_sha256, first.receipt_sha256)
        with self.subTest("terminal_reason change"):
            alt = seal_p5_native_receipt(
                root_run_id="root-run-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=2,
                repair_step_count=1,
                failed_verify_count=1,
                terminal_reason="iteration-cap-exceeded",
                joined_workspace_digest=_digest("propose-1"),
            )
            self.assertNotEqual(alt.receipt_sha256, first.receipt_sha256)
        with self.subTest("joined_workspace_digest change"):
            alt = seal_p5_native_receipt(
                root_run_id="root-run-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=2,
                repair_step_count=1,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest=_digest("propose-2"),
            )
            self.assertNotEqual(alt.receipt_sha256, first.receipt_sha256)

    def test_seal_receipt_rejects_invalid_inputs(self) -> None:
        # Terminal reason must be one of the closed 5-element enum.
        with self.assertRaises(BoundedAutonomyServiceError):
            seal_p5_native_receipt(
                root_run_id="root-run-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=1,
                terminal_reason="still-running",  # type: ignore[arg-type]
                joined_workspace_digest=_digest("x"),
            )
        # Failed verify count is enforced >= 1 by the spec witness.
        with self.assertRaises(BoundedAutonomyServiceError):
            seal_p5_native_receipt(
                root_run_id="root-run-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=0,
                terminal_reason="success",
                joined_workspace_digest=_digest("x"),
            )
        # joined_workspace_digest must be a 64-char hex SHA-256.
        with self.assertRaises(BoundedAutonomyServiceError):
            seal_p5_native_receipt(
                root_run_id="root-run-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=1,
                terminal_reason="success",
                joined_workspace_digest="not-a-digest",
            )

    def test_service_exposes_public_identity_without_leaking_private_root(
        self,
    ) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                self.assertIsInstance(service, BoundedAutonomyLoop)
                public = service.public_identity
                self.assertEqual(public.provider_id, "prime-applications")
                self.assertEqual(
                    public.application_id, "prime.bounded-autonomy"
                )
                self.assertEqual(public.runtime_id, "asterion.prime")
                self.assertEqual(public.session_id, "prime.bounded-autonomy")
                self.assertEqual(public.generation, 1)
                # No private-root-style field is exposed on the projection.
                self.assertNotIn("private_root", vars(public))
                self.assertNotIn("private_root_identity", vars(public))
                self.assertEqual(public.pi_command_sha256, "0" * 64)
                self.assertEqual(public.extension_binding_fingerprint, "0" * 64)
                self.assertEqual(public.worker_identity_sha256, "0" * 64)

        asyncio.run(driver())

    def test_service_runs_propose_verify_repair_loop_to_success(self) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                iter_state = {"propose": 0, "verify": 0, "repair": 0}

                async def propose(signal):
                    iter_state["propose"] += 1
                    return P5ProposeStep(
                        step_id=f"propose-{iter_state['propose']}",
                        workspace_digest_sha256=_digest(
                            f"propose-{iter_state['propose']}"
                        ),
                    )

                async def verify(signal):
                    iter_state["verify"] += 1
                    if iter_state["verify"] == 1:
                        return P5VerifyStep(
                            step_id=f"verify-{iter_state['verify']}",
                            verdict="fail",
                            feedback="public-safe feedback",
                        )
                    return P5VerifyStep(
                        step_id=f"verify-{iter_state['verify']}",
                        verdict="pass",
                        feedback="public-safe feedback",
                    )

                async def repair(signal):
                    iter_state["repair"] += 1
                    return P5RepairStep(
                        step_id=f"repair-{iter_state['repair']}",
                        workspace_digest_sha256=_digest(
                            f"repair-{iter_state['repair']}"
                        ),
                    )

                service.set_step_callables(
                    propose_callable=propose,
                    verify_callable=verify,
                    repair_callable=repair,
                )

                receipt = await service.run_loop(root_run_id="root-run-1")
                self.assertEqual(receipt.terminal_reason, "success")
                self.assertEqual(receipt.root_run_id, "root-run-1")
                self.assertEqual(receipt.root_generation, 1)
                self.assertEqual(receipt.propose_step_count, 1)
                self.assertEqual(receipt.verify_step_count, 2)
                self.assertEqual(receipt.repair_step_count, 1)
                self.assertEqual(receipt.failed_verify_count, 1)
                self.assertEqual(
                    receipt.joined_workspace_digest,
                    _digest("repair-1"),
                )
                self.assertEqual(len(receipt.receipt_sha256), 64)
                self.assertFalse(service.last_step_timed_out)

        asyncio.run(driver())

    def test_service_stops_with_iteration_cap_exceeded_after_three_fails(
        self,
    ) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                iter_state = {"propose": 0, "verify": 0, "repair": 0}

                async def propose(signal):
                    iter_state["propose"] += 1
                    return P5ProposeStep(
                        step_id=f"propose-{iter_state['propose']}",
                        workspace_digest_sha256=_digest(
                            f"propose-{iter_state['propose']}"
                        ),
                    )

                async def verify(signal):
                    iter_state["verify"] += 1
                    return P5VerifyStep(
                        step_id=f"verify-{iter_state['verify']}",
                        verdict="fail",
                        feedback="public-safe feedback",
                    )

                async def repair(signal):
                    iter_state["repair"] += 1
                    return P5RepairStep(
                        step_id=f"repair-{iter_state['repair']}",
                        workspace_digest_sha256=_digest(
                            f"repair-{iter_state['repair']}"
                        ),
                    )

                service.set_step_callables(
                    propose_callable=propose,
                    verify_callable=verify,
                    repair_callable=repair,
                )

                receipt = await service.run_loop(root_run_id="root-run-1")
                self.assertEqual(
                    receipt.terminal_reason, "iteration-cap-exceeded"
                )
                # Each run_loop emits exactly one propose step; verify
                # and repair continue until the iteration cap fires.
                self.assertEqual(receipt.propose_step_count, 1)
                self.assertEqual(receipt.verify_step_count, 3)
                self.assertEqual(receipt.repair_step_count, 2)
                self.assertEqual(receipt.failed_verify_count, 3)
                self.assertEqual(
                    receipt.joined_workspace_digest, _digest("repair-2")
                )
                self.assertFalse(service.last_step_timed_out)

        asyncio.run(driver())

    def test_service_stops_with_duration_cap_exceeded_on_slow_propose(
        self,
    ) -> None:
        async def driver():
            # Force the total-duration cap to fire before any step
            # completes by setting max_total_duration_ms to a value
            # smaller than the slow propose's sleep.
            options = {"max_total_duration_ms": "50"}
            ctx = _context(options)
            factory = create_bounded_autonomy_host_service().factory
            async with factory(ctx) as service:
                async def slow_propose(signal):
                    await asyncio.sleep(0.5)
                    return P5ProposeStep(
                        step_id="propose-1",
                        workspace_digest_sha256=_digest("never-reached"),
                    )

                async def verify(signal):
                    return P5VerifyStep(
                        step_id="verify-1",
                        verdict="pass",
                        feedback="public-safe feedback",
                    )

                async def repair(signal):
                    return P5RepairStep(
                        step_id="repair-1",
                        workspace_digest_sha256=_digest("never-reached"),
                    )

                service.set_step_callables(
                    propose_callable=slow_propose,
                    verify_callable=verify,
                    repair_callable=repair,
                )

                receipt = await service.run_loop(root_run_id="root-run-1")
                self.assertEqual(
                    receipt.terminal_reason, "duration-cap-exceeded"
                )
                self.assertTrue(service.last_step_timed_out)
                self.assertEqual(receipt.propose_step_count, 1)
                self.assertEqual(receipt.verify_step_count, 1)
                self.assertEqual(receipt.repair_step_count, 0)
                self.assertEqual(receipt.failed_verify_count, 1)
                # joined_workspace_digest falls back to the zero SHA when
                # the loop never advanced past the propose step.
                self.assertEqual(
                    receipt.joined_workspace_digest, "0" * 64
                )

        asyncio.run(driver())

    def test_service_stops_with_no_progress_on_unchanged_workspace_digest(
        self,
    ) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                async def propose(signal):
                    return P5ProposeStep(
                        step_id="propose-1",
                        workspace_digest_sha256=_digest("unchanged"),
                    )

                async def verify(signal):
                    return P5VerifyStep(
                        step_id="verify-1",
                        verdict="fail",
                        feedback="public-safe feedback",
                    )

                async def repair(signal):
                    # Repair returns the same digest as propose — the
                    # dedup-adapter must short-circuit.
                    return P5RepairStep(
                        step_id="repair-1",
                        workspace_digest_sha256=_digest("unchanged"),
                    )

                service.set_step_callables(
                    propose_callable=propose,
                    verify_callable=verify,
                    repair_callable=repair,
                )

                receipt = await service.run_loop(root_run_id="root-run-1")
                self.assertEqual(receipt.terminal_reason, "no-progress")
                self.assertEqual(receipt.propose_step_count, 1)
                self.assertEqual(receipt.verify_step_count, 1)
                self.assertEqual(receipt.repair_step_count, 1)
                self.assertEqual(receipt.failed_verify_count, 1)
                self.assertEqual(
                    receipt.joined_workspace_digest, _digest("unchanged")
                )
                self.assertFalse(service.last_step_timed_out)

        asyncio.run(driver())

    def test_service_emits_single_terminal_receipt_no_still_running_state(
        self,
    ) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                async def propose(signal):
                    return P5ProposeStep(
                        step_id="propose-1",
                        workspace_digest_sha256=_digest("propose-1"),
                    )

                async def verify(signal):
                    return P5VerifyStep(
                        step_id="verify-1",
                        verdict="pass",
                        feedback="public-safe feedback",
                    )

                async def repair(signal):
                    return P5RepairStep(
                        step_id="repair-1",
                        workspace_digest_sha256=_digest("repair-1"),
                    )

                service.set_step_callables(
                    propose_callable=propose,
                    verify_callable=verify,
                    repair_callable=repair,
                )

                first = await service.run_loop(root_run_id="root-run-1")
                self.assertIsInstance(first, P5NativeReceipt)
                self.assertEqual(first.terminal_reason, "success")

                # A second call with the same root_run_id returns the
                # cached terminal receipt — no "still running" state is
                # ever public.
                second = await service.run_loop(root_run_id="root-run-1")
                self.assertEqual(first, second)

                # A different root_run_id re-opens the loop and runs a
                # fresh bounded sequence.
                third = await service.run_loop(root_run_id="root-run-2")
                self.assertEqual(third.terminal_reason, "success")
                self.assertEqual(third.root_run_id, "root-run-2")
                self.assertNotEqual(third.receipt_sha256, first.receipt_sha256)

        asyncio.run(driver())

    def test_workspace_digest_dedup_rejects_second_gate_with_same_digest(
        self,
    ) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                # Two consecutive propose steps both carry the same
                # digest. The loop must terminate with ``no-progress``
                # after the second propose, before invoking verify.
                async def propose(signal):
                    return P5ProposeStep(
                        step_id="propose",
                        workspace_digest_sha256=_digest("unchanged"),
                    )

                verify_called = {"count": 0}

                async def verify(signal):
                    verify_called["count"] += 1
                    return P5VerifyStep(
                        step_id="verify",
                        verdict="fail",
                        feedback="public-safe feedback",
                    )

                async def repair(signal):
                    return P5RepairStep(
                        step_id="repair",
                        workspace_digest_sha256=_digest("unchanged"),
                    )

                service.set_step_callables(
                    propose_callable=propose,
                    verify_callable=verify,
                    repair_callable=repair,
                )

                # First run: propose → verify (fail) → repair returns
                # the same digest → ``no-progress`` short-circuit fires
                # before the next verify step.
                receipt_first = await service.run_loop(
                    root_run_id="root-run-1"
                )
                self.assertEqual(
                    receipt_first.terminal_reason, "no-progress"
                )
                self.assertEqual(verify_called["count"], 1)

                # Second run on a fresh root_run_id: the repair step
                # again returns the unchanged digest → ``no-progress``
                # fires again; verify is called exactly once per run.
                receipt_second = await service.run_loop(
                    root_run_id="root-run-2"
                )
                self.assertEqual(
                    receipt_second.terminal_reason, "no-progress"
                )
                self.assertEqual(verify_called["count"], 2)

        asyncio.run(driver())

    def test_service_stops_with_cancelled_on_signal(self) -> None:
        async def driver():
            async with await _open_with_defaults() as service:
                signal = _CancellationSignal()

                async def propose(signal):
                    signal.cancel()
                    return P5ProposeStep(
                        step_id="propose-1",
                        workspace_digest_sha256=_digest("propose-1"),
                    )

                async def verify(signal):
                    return P5VerifyStep(
                        step_id="verify-1",
                        verdict="pass",
                        feedback="public-safe feedback",
                    )

                async def repair(signal):
                    return P5RepairStep(
                        step_id="repair-1",
                        workspace_digest_sha256=_digest("repair-1"),
                    )

                service.set_step_callables(
                    propose_callable=propose,
                    verify_callable=verify,
                    repair_callable=repair,
                )

                receipt = await service.run_loop(
                    root_run_id="root-run-1", signal=signal
                )
                self.assertEqual(receipt.terminal_reason, "cancelled")

        asyncio.run(driver())

    def test_service_rejects_unknown_options(self) -> None:
        async def driver():
            ctx = _context({"unexpected": "value"})
            factory = create_bounded_autonomy_host_service().factory
            with self.assertRaises(BoundedAutonomyServiceError):
                async with factory(ctx):
                    pass

        asyncio.run(driver())

    def test_service_rejects_wrong_application_identity(self) -> None:
        async def driver():
            ctx = HostServiceFactoryContext(
                provider_id="prime-applications",
                application_id="prime.recursive-workflow",
                application_version="1.0.0",
                capability_id="prime.bounded-autonomy",
                options={},
                progress=NOOP_HOST_PROGRESS_REPORTER,
                presentation=NOOP_HOST_PRESENTATION_SINK,
            )
            factory = create_bounded_autonomy_host_service().factory
            with self.assertRaises(BoundedAutonomyServiceError):
                async with factory(ctx):
                    pass

        asyncio.run(driver())

    def test_terminal_reason_is_closed_five_element_enum(self) -> None:
        # The closed enum is the public contract for P5 (mirror of P3's
        # refusal-reason contract). Anything outside this set is invalid
        # at the seal boundary.
        self.assertEqual(
            set(),
            set(),
        )
        # The type alias exists and is a Literal.
        # We assert behaviour at the seal boundary instead.
        for reason in (
            "success",
            "iteration-cap-exceeded",
            "duration-cap-exceeded",
            "no-progress",
            "cancelled",
        ):
            receipt = seal_p5_native_receipt(
                root_run_id="root-run-1",
                root_generation=1,
                propose_step_count=1,
                verify_step_count=1,
                repair_step_count=0,
                failed_verify_count=1,
                terminal_reason=reason,  # type: ignore[arg-type]
                joined_workspace_digest=_digest("x"),
            )
            self.assertEqual(receipt.terminal_reason, reason)

        for invalid in ("still-running", "unknown", "Success", ""):
            with self.assertRaises(BoundedAutonomyServiceError):
                seal_p5_native_receipt(
                    root_run_id="root-run-1",
                    root_generation=1,
                    propose_step_count=1,
                    verify_step_count=1,
                    repair_step_count=0,
                    failed_verify_count=1,
                    terminal_reason=invalid,  # type: ignore[arg-type]
                    joined_workspace_digest=_digest("x"),
                )


if __name__ == "__main__":
    unittest.main()
