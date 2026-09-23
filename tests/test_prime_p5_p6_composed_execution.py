"""Prime research applications execute injected work before returning receipts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import unittest

from asterion.applications.provider import compose_installed_provider
from asterion.applications.prime.provider import create_prime_bounded_autonomy_provider
from asterion.applications.prime.p5.host import P5Finalization, P5LoopResult
from asterion.applications.prime.p5.oracle import P5Oracle
from asterion.applications.prime.p5.receipt import seal
from asterion.applications.prime.p5.runtime_binding import (
    build_p5_runtime,
    P5_RUNTIME_OPTIONS,
)
from asterion.capabilities.prime_bounded_autonomy_native.provider import (
    create_prime_bounded_autonomy_native_package,
)
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
from asterion.runner.composed import run_composed_application


class Signal:
    cancelled = False


class RecordingP5Host:
    def __init__(self, reason="success"):
        self.calls = []
        self.reason = reason
        self.receipt = None

    def validate_runtime_services(self, services):
        pass

    async def run_loop(self, *, root_run_id, signal):
        self.calls.append(root_run_id)
        self.receipt = seal(
            root_run_id=root_run_id,
            root_generation=1,
            propose_step_count=1,
            verify_step_count=2,
            repair_step_count=1,
            failed_verify_count=1,
            terminal_reason=self.reason,
            joined_workspace_digest="a" * 64,
        )
        return P5LoopResult(**asdict(self.receipt))

    def report_loop_stopped(self, *, terminal_reason, root_run_id):
        pass

    async def wait_finalization(self, *, signal):
        return P5Finalization("completed", self.receipt.receipt_sha256)


class PrimeP5ComposedExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def run_p5(self, host, signal=None):
        package = create_prime_bounded_autonomy_native_package()
        provider = compose_installed_provider(
            create_prime_bounded_autonomy_provider(),
            runtime_factories=RuntimeFactoryRegistry(()),
            installed_packages=(package,),
        )
        plan = provider.applications[0].assemblies[0].plan
        services = {name: object() for name in plan.host_capabilities}
        services.update(
            {
                "prime.session-backend": host,
                "prime.p5-oracle": P5Oracle(),
                "prime.private-trace": None,
            }
        )
        runtime = build_p5_runtime(
            RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.bounded-autonomy",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=Path("/dev/null"),
                options=P5_RUNTIME_OPTIONS,
                host_services=services,
            )
        )
        return await run_composed_application(
            plan,
            implementations=tuple(
                (b.capability_ref, b.implementation) for b in package.implementations
            ),
            runtime=runtime,
            run_id="p5-composed-test",
            input_text="fixed-bounded-autonomy",
            host_services=services,
            signal=signal,
        )

    async def test_success_invokes_host_and_returns_one_receipt(self):
        host = RecordingP5Host()
        result = await self.run_p5(host)
        self.assertEqual(len(host.calls), 1)
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(
            result.artifacts[0]["value"]["receipt_sha256"], host.receipt.receipt_sha256
        )

    async def test_stopped_host_cannot_return_successful_receipt(self):
        with self.assertRaises(Exception):
            await self.run_p5(RecordingP5Host("no-progress"))

    async def test_pre_cancelled_has_no_host_call(self):
        host = RecordingP5Host()
        signal = Signal()
        signal.cancelled = True
        with self.assertRaisesRegex(Exception, "cancelled"):
            await self.run_p5(host, signal)
        self.assertEqual(host.calls, [])


class RecordingP6Host:
    def __init__(self):
        self.calls = []
        self.receipt = None

    def validate_runtime_services(self, services):
        pass

    async def run_candidate(self, *, root_run_id, signal):
        from asterion.applications.prime.p6.receipt import (
            P6NativeReceipt,
            seal_p6_native_receipt,
        )

        self.calls.append(root_run_id)
        self.receipt = seal_p6_native_receipt(
            P6NativeReceipt(
                root_run_id,
                "a" * 64,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                "preserved",
                False,
                0,
                "0" * 64,
                None,
            )
        )
        return self.receipt


class PrimeP6ComposedExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_invokes_host_and_returns_receipt(self):
        from asterion.applications.prime.provider import (
            create_prime_continual_improvement_provider,
        )
        from asterion.applications.prime.p6.oracle import P6Oracle
        from asterion.applications.prime.p6.runtime_binding import (
            build_p6_runtime,
            P6_RUNTIME_OPTIONS,
        )
        from asterion.capabilities.prime_continual_improvement_native.provider import (
            create_prime_continual_improvement_native_package,
        )
        from tests.test_asterion_prime_p6_runtime_binding import _stub_candidate_store

        host = RecordingP6Host()
        package = create_prime_continual_improvement_native_package()
        provider = compose_installed_provider(
            create_prime_continual_improvement_provider(),
            runtime_factories=RuntimeFactoryRegistry(()),
            installed_packages=(package,),
        )
        plan = provider.applications[0].assemblies[0].plan
        services = {name: object() for name in plan.host_capabilities}
        services.update(
            {
                "prime.session-backend": host,
                "prime.p6-oracle": P6Oracle(),
                "prime.private-trace": None,
                "prime.candidate-store": _stub_candidate_store(),
            }
        )
        runtime = build_p6_runtime(
            RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.continual-improvement",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=Path("/dev/null"),
                options=P6_RUNTIME_OPTIONS,
                host_services=services,
            )
        )
        result = await run_composed_application(
            plan,
            implementations=tuple(
                (b.capability_ref, b.implementation) for b in package.implementations
            ),
            runtime=runtime,
            run_id="p6-composed-test",
            input_text="fixed-continual-improvement",
            host_services=services,
        )
        self.assertEqual(len(host.calls), 1)
        self.assertEqual(
            result.artifacts[0]["value"]["receipt_sha256"], host.receipt.receipt_sha256
        )

    async def test_real_candidate_workflow_oracle_and_rollback_control_result(self):
        from unittest.mock import patch
        from dataclasses import replace
        from asterion.applications.prime.p6 import operator
        from asterion.applications.prime.p6.oracle import P6Oracle
        from asterion.applications.prime.p6.runtime_binding import _P6RuntimeSession
        from asterion.control.harness import (
            HarnessScope,
            MemoryHarnessPrivateRevisionStore,
        )
        from asterion.runtime.host import RunRequest

        for outcome in ("preserved", "regressed", "oracle-refused"):
            with self.subTest(outcome=outcome):
                oracle = P6Oracle()
                resources = operator._OperatorResources(
                    "preserved",
                    Path("/unused"),
                    "p6-workflow",
                    HarnessScope.project("prime.continual-improvement"),
                    False,
                    oracle,
                )
                loop, coordinator = await operator._open_candidate_store_for_run(
                    scope=resources.scope,
                    global_activation_approved=False,
                    private_store=MemoryHarnessPrivateRevisionStore(),
                )
                host = operator._ComposedCandidateHost(
                    resources, loop, coordinator, non_regressing=outcome != "regressed"
                )
                session = _P6RuntimeSession(
                    session_backend=host,
                    candidate_store=loop,
                    oracle=oracle,
                    private_trace=None,
                )
                request = RunRequest(
                    run_id="p6-workflow",
                    input_text="fixed-continual-improvement",
                    requested_capabilities=(),
                    deadline_ms=120_000,
                )
                events = []
                original_check = oracle.check

                def check(**kwargs):
                    result = original_check(**kwargs)
                    return (
                        replace(result, verdict="rolled-back")
                        if outcome == "oracle-refused"
                        else result
                    )

                with patch.object(oracle, "check", side_effect=check) as checked:
                    if outcome == "preserved":
                        async for event in session.run(request):
                            events.append(event)
                        self.assertEqual(events[-1].payload, {"status": "completed"})
                    else:
                        async for event in session.run(request):
                            events.append(event)
                        self.assertEqual(events[-1].type, "run.failed")
                        self.assertNotIn(
                            "artifact.created", [event.type for event in events]
                        )
                    self.assertEqual(checked.call_count, 1)
                if outcome == "regressed":
                    self.assertEqual(loop.rollback_invocation_count, 1)
                    self.assertEqual(coordinator.snapshot().entries, ())
                if outcome == "oracle-refused":
                    self.assertEqual(host.effects_state, "recovery-required")
                    self.assertEqual(loop.rollback_invocation_count, 0)
                    self.assertIsNone(host.receipt)

    async def test_operator_uses_public_composed_runner(self):
        from unittest.mock import patch
        from asterion.applications.prime.p6.operator import drive_preserved_for_test
        from asterion.runner.composed import run_composed_application

        with patch(
            "asterion.runner.composed.run_composed_application",
            wraps=run_composed_application,
        ) as composed:
            result = await drive_preserved_for_test(root_run_id="p6-composed-operator")
        self.assertEqual(composed.call_count, 1)
        self.assertEqual(result.terminal_outcome, "preserved")

    async def test_cancelled_admitted_candidate_is_reversed_or_requires_recovery(self):
        from unittest.mock import patch
        from asterion.applications.prime.p6 import operator
        from asterion.applications.prime.p6.oracle import P6Oracle
        from asterion.applications.prime.p6.runtime_binding import _P6RuntimeSession
        from asterion.control.harness import (
            HarnessScope,
            MemoryHarnessPrivateRevisionStore,
            HarnessError,
        )
        from asterion.runtime.host import RunRequest

        for rollback_fails in (False, True):
            with self.subTest(rollback_fails=rollback_fails):
                signal = Signal()
                resources = operator._OperatorResources(
                    "preserved",
                    Path("/unused"),
                    "p6-cancelled",
                    HarnessScope.project("prime.continual-improvement"),
                    False,
                    P6Oracle(),
                )
                loop, coordinator = await operator._open_candidate_store_for_run(
                    scope=resources.scope,
                    global_activation_approved=False,
                    private_store=MemoryHarnessPrivateRevisionStore(),
                )
                host = operator._ComposedCandidateHost(resources, loop, coordinator)
                session = _P6RuntimeSession(
                    session_backend=host,
                    candidate_store=loop,
                    oracle=resources.p6_oracle,
                    private_trace=None,
                )
                original_admit = loop.admit_candidate

                def admit_then_cancel(**kwargs):
                    revision = original_admit(**kwargs)
                    signal.cancelled = True
                    return revision

                original_rollback = coordinator.rollback

                def rollback(**kwargs):
                    if rollback_fails:
                        raise HarnessError("PRIVATE-ROLLBACK-FAILURE")
                    return original_rollback(**kwargs)

                with (
                    patch.object(
                        loop, "admit_candidate", side_effect=admit_then_cancel
                    ),
                    patch.object(
                        coordinator, "rollback", side_effect=rollback
                    ) as reversed_revision,
                ):
                    events = [
                        event
                        async for event in session.run(
                            RunRequest(
                                run_id="p6-cancelled",
                                input_text="fixed-continual-improvement",
                                requested_capabilities=(),
                                deadline_ms=120_000,
                            ),
                            signal=signal,
                        )
                    ]
                self.assertEqual(reversed_revision.call_count, 1)
                self.assertIsNone(host.receipt)
                self.assertNotIn("artifact.created", [event.type for event in events])
                self.assertNotIn("PRIVATE-ROLLBACK-FAILURE", repr(events))
                if rollback_fails:
                    self.assertEqual(host.effects_state, "recovery-required")
                    self.assertEqual(len(coordinator.snapshot().entries), 1)
                    self.assertEqual(loop.rollback_invocation_count, 0)
                else:
                    self.assertEqual(host.effects_state, "rolled-back")
                    self.assertEqual(coordinator.snapshot().entries, ())
                    self.assertEqual(loop.rollback_invocation_count, 1)
                from asterion.applications.prime.services import (
                    CandidateStoreServiceError,
                )

                with patch.object(
                    coordinator, "rollback", wraps=coordinator.rollback
                ) as duplicate:
                    with self.assertRaises(CandidateStoreServiceError):
                        loop.rollback_admitted_candidate(
                            proposal_id="must-not-repeat",
                            authority_id="prime.candidate-store",
                            authority_revision=1,
                            rationale_ref="private:rationale-rb",
                            rationale_digest="f" * 64,
                            expected_outcome_digest="1" * 64,
                        )
                    duplicate.assert_not_called()
