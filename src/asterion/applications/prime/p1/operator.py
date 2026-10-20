"""Operator-owned native P1 control reconstruction and resource lifetime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from importlib import resources as importlib_resources
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from types import MappingProxyType

from asterion.agents.prime.backend import (
    PrimeBackendBudgetError,
    PrimePromptRequest,
    PrimeAttachment,
)
from asterion.agents.prime.compaction_budget import (
    ModelPrice,
    quote_compaction_reservation,
)
from asterion.applications.prime.resource_alarms import ResourceAlarmSink, public_resource_alarms
from asterion.agents.prime.execution import AsterionPrimeLimits
from asterion.agents.prime.store import private_root_identity
from asterion.agents.prime.code_summary import (
    CODE_SUMMARY_VERSION,
    CodeSummaryError,
    is_dedicated_code_summary,
    is_native_generic_summary,
)
from asterion.agents.prime.summarization import compaction_custom_instructions
from asterion.applications.prime.p1.code_summary import summarize_worker
from .compaction_policy import (
    P1_COMPACTION_RESERVED_TOKENS, P1_COMPACTION_COST_MICROS, P1_COMPACTION_POLICY,
)
from asterion.agents.prime.tool_registry import CORE_TOOL_REGISTRY
from asterion.applications.first_party_packages import (
    create_prime_ipython_coding_native_package,
)
from asterion.applications.prime import create_prime_ipython_coding_provider
from asterion.applications.provider import compose_installed_provider
from asterion.applications.prime.p1.coordination import (
    P1Coordination,
    P1OwnerCleanup,
    consume_task_result,
    wait_task_until,
)
from asterion.applications.prime.p1.ipython_host import P1WorkerProcess
from asterion.applications.prime.p1.oracle import (
    P1Oracle,
    P1OracleError,
    P1OracleReceipt,
    P1StageOneReceipt,
    P1_ORACLE_REJECT_STEPS,
)
from asterion.applications.prime.p1.receipt import (
    build_native_receipt,
    seal_cleanup_receipt,
)
from asterion.applications.prime.p1.runtime_binding import (
    P1WorkerOwnerAdapter,
    build_p1_runtime_from_host,
)
from asterion.applications.prime.p1.task import P1_TASK_STATEMENT
from asterion.applications.prime.p1.worker import (
    P1CellRequest,
    P1WorkerCheckpoint,
    digest,
)
from asterion.capabilities.prime_ipython_coding_native.host import (
    P1Finalization,
    P1PendingClassification,
    P1RuntimeHostError,
    P1StageMilestone,
    P1StageTwoRelease,
)
from asterion.control.authority import (
    AuthorityEnvelope,
    AuthorityLedger,
    BudgetLimit,
    PortfolioGrant,
)
from asterion.control.factory import (
    ControlPlaneFactoryContext,
    ControlPlaneFactoryRegistry,
)
from asterion.control.host import ControlCommand
from asterion.control.journal import FileCanonicalJournal, JournalCursor
from asterion.control.manager import ControlHost
from asterion.control.providers.asterion_prime import (
    asterion_prime_control_plane_binding,
    build_asterion_prime_control_plane_client,
)
from asterion.control.recovery import recover_control_host_state
from asterion.control.session_context import (
    SessionContextCommand,
    SessionContextReceipt,
)
from asterion.control.system import resolve_agent_system
from asterion.applications.prime.p7 import live
from asterion.runner.application import ApplicationRunResult
from asterion.runner.composed import run_composed_application
from asterion.runtime.factory import RuntimeFactoryRegistry
from asterion.runtime.host import CancellationSignal
from asterion.agents.prime.application import (
    PrimeApplication, PrimeApplicationSpec, PrimeOperatorContext, PrimeBackendSpec,
    PrimeToolModuleArtifact, prepare_prime_application,
)
from asterion.agents.prime.deadline import TaskDeadline
from asterion.agents.prime.tools import PrimeToolResult
from asterion.applications.prime.operator_config import resolve_pi_effort

_CLEANUP_SECONDS = 5.0


class P1OperatorError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P1 operator is unavailable")


@dataclass(frozen=True, slots=True)
class P1PublicResult:
    run_id: str
    status: str
    receipt_sha256: str | None = None
    resource_alarms: tuple[dict[str, object], ...] = ()
    code_summary_kind: str | None = None
    code_summary_sha256: str | None = None
    code_summary_bindings: tuple[str, ...] = ()
    code_summary_text: str | None = None
    code_summary_below_native_threshold: bool = False


_PUBLIC_PROGRESS_STAGES = frozenset(
    {
        "authority.sync",
        "backend.close",
        "backend.open",
        "compact.admit",
        "compact.persist",
        "host1.close",
        "host1.open",
        "host2.close",
        "host2.recover",
        "journal.reopen",
        "oracle.pass",
        "oracle.reject.effect",
        "resume.admit",
        "resume.persist",
        "runner.start",
        "runner.terminal",
        "stage1.complete",
        "stage1.oracle.complete",
        "stage1.oracle.start",
        "stage1.setup.complete",
        "stage1.setup.start",
        "stage1.verify.complete",
        "stage1.verify.start",
        "stage2.complete",
        "stage2.release",
        "worker.close",
    }
) | frozenset(f"oracle.reject.{step}" for step in P1_ORACLE_REJECT_STEPS)

_ORACLE_REJECT_STAGES = {
    step: f"oracle.reject.{step}" for step in P1_ORACLE_REJECT_STEPS
}


def _public_progress(stage: str) -> None:
    if stage not in _PUBLIC_PROGRESS_STAGES:
        raise P1OperatorError()
    print(
        json.dumps({"stage": stage}, separators=(",", ":"), sort_keys=True),
        file=sys.stderr,
        flush=True,
    )


def _public_resource_alarm(alarm: dict[str, object]) -> None:
    print(json.dumps(alarm, allow_nan=False, sort_keys=True, separators=(",", ":")),
          file=sys.stderr, flush=True)


class _NoActions:
    async def execute(self, *args: object, **kwargs: object):
        raise P1OperatorError()


class P1OperatorResources:
    """Concrete runtime service and control owner over one preflighted backend."""

    def __init__(
        self,
        *,
        application: PrimeApplication,
        backend: PrimeAttachment,
        worker: P1WorkerProcess,
        worker_owner: P1WorkerOwnerAdapter,
        private_root: Path,
        journal_root: Path,
        run_id: str,
        deadline: float,
        observe: Callable[[str], None] = lambda _: None,
        cleanup_root: Callable[[], None] | None = None,
        resource_alarm_sink: ResourceAlarmSink | None = None,
    ) -> None:
        identity = backend.snapshot().identity
        if (
            (
                identity.provider_id,
                identity.application_id,
                identity.application_version,
                identity.runtime_id,
            )
            != ("prime-applications", "prime.ipython-coding", "1.0.0", "asterion.prime")
            or identity.worker_identity_sha256 != worker.identity_sha256
            or identity.private_root_identity != private_root_identity(private_root)
            or application._backend_snapshot().identity != identity
        ):
            raise P1OperatorError()
        self.application, self.backend = application, backend
        self.worker, self.worker_owner = worker, worker_owner
        self.private_root, self.journal_root = private_root, journal_root
        self.identity, self.run_id = identity, run_id
        self.coordination = P1Coordination(run_id=run_id, deadline=deadline)
        self.oracle = P1Oracle(worker, kernel_generation=identity.generation)
        self.observe = observe
        self._cleanup_root = cleanup_root
        self.resource_alarm_sink = resource_alarm_sink
        self.active_turn_id = ""
        self._host_number = 0
        self._host_closed = True
        self._cleanup: P1OwnerCleanup | None = None
        self._prime_cleanup = None
        self._stage_one: P1StageOneReceipt | None = None
        self._oracle_result: P1OracleReceipt | None = None
        self._release: P1StageTwoRelease | None = None
        self._consumed = False
        self._code_summary = None
        self.host: ControlHost | None = None
        self._journal: FileCanonicalJournal | None = None
        self.authority = AuthorityEnvelope(
            authority_id="authority-1",
            revision=1,
            allowed_portfolio=(
                PortfolioGrant(
                    "prime-applications",
                    "prime.ipython-coding",
                    "1.0.0",
                    "asterion.prime",
                ),
            ),
            allowed_operations=(
                "session.compact",
                "session.continuation.resume",
                "session.describe",
            ),
            budget_limit=BudgetLimit(64_000, 64_000, 0, 64_000, 500_000),
            expires_at_ms=int(deadline * 1000),
            max_action_deadline_ms=600_000,
            max_recursion_depth=0,
            max_concurrent_children=0,
            execution_domain="restricted",
            host_service_grants=("prime.session-backend",),
        )
        package = create_prime_ipython_coding_native_package()
        # Compose from this application's own record, never by looking itself
        # up in the published provider list. Publication is an advertisement
        # decision that is gated on this application's installed-route witness;
        # if running also depended on it, that witness could only be produced
        # after publication and the application's own route could never be
        # exercised at all.
        provider = compose_installed_provider(
            create_prime_ipython_coding_provider(),
            runtime_factories=RuntimeFactoryRegistry(()),
            installed_packages=(package,),
        )
        assembly = provider.applications[0].assemblies[0]
        self.plan = assembly.plan
        self.implementations = tuple(
            (item.capability_ref, item.implementation)
            for item in package.implementations
        )
        self.host_services = MappingProxyType(
            {
                "prime.ipython": worker,
                "prime.p1-oracle": self.oracle,
                "prime.launch": application,
                "prime.private-trace": application,
                "prime.session-backend": self,
            }
        )
        self.validate_runtime_services(
            ipython=worker, oracle=self.oracle, extension=application, private_trace=application)
        self.runtime = build_p1_runtime_from_host(self)
        binding = asterion_prime_control_plane_binding()
        self._system = resolve_agent_system(
            {
                "protocol": "asterion.agent-system/v1",
                "system_id": "prime.ipython-coding",
                "version": "1.0.0",
                "control_plane": {
                    "control_plane_id": binding.control_plane_id,
                    "version": binding.version,
                },
                "applications": [
                    {
                        "provider_id": "prime-applications",
                        "application_id": "prime.ipython-coding",
                        "version": "1.0.0",
                        "runtime_id": "asterion.prime",
                    }
                ],
                "policies": ["policy.budget"],
                "host_capabilities": ["clock.monotonic", "storage.private"],
                "control_capabilities": list(binding.capabilities),
            },
            application_providers=(provider,),
            control_factories=ControlPlaneFactoryRegistry((binding,)),
            host_capabilities=("clock.monotonic", "storage.private"),
        )

    def __repr__(self) -> str:
        return "<P1OperatorResources>"

    def validate_runtime_services(
        self,
        *,
        ipython: object,
        oracle: object,
        extension: object,
        private_trace: object,
    ) -> None:
        if (
            ipython is not self.worker
            or oracle is not self.oracle
            or extension is not self.application
            or private_trace is not self.application
        ):
            raise P1OperatorError()
        self.worker_owner.validate_lifecycle()
        self.application._validate_backend_resources()

    def _clock_ms(self) -> int:
        return int(time.monotonic() * 1000)

    async def open(self) -> None:
        self.observe("backend.open")
        self.backend.sync_authority_snapshot(
            AuthorityLedger(self.authority).remaining_budget(now_ms=self._clock_ms()),
            authority_revision=1,
        )
        await self._construct_host(recovery=False)
        assert self.host is not None
        await self.host.dispatch(
            ControlCommand(
                "create-1",
                self.identity.session_id,
                1,
                "session.create",
                {
                    "system_id": "prime.ipython-coding",
                    "system_version": "1.0.0",
                    "goal_id": "p1-verification",
                    "goal_ref": "fixed-small-verification",
                },
            )
        )
        await self.host.pump()

    async def _construct_host(self, *, recovery: bool) -> None:
        journal = FileCanonicalJournal.open(self.journal_root, self.identity.session_id)
        self._journal = journal
        if recovery:
            self.observe("journal.reopen")
            recover_control_host_state(
                journal.replay(JournalCursor(0)),
                self.authority,
                expected_session_id=self.identity.session_id,
                expected_generation=self.identity.generation,
            )
        client = build_asterion_prime_control_plane_client(
            ControlPlaneFactoryContext(
                system_id="prime.ipython-coding",
                system_version="1.0.0",
                control_plane_id="asterion.prime-control",
                control_plane_version="1.0.0",
                private_root=self.private_root,
                options={
                    "generation": str(self.identity.generation),
                    "session_id": self.identity.session_id,
                },
                authority=self.authority,
                host_services={"prime.session-backend": self.application},
            )
        )
        try:
            self.host = ControlHost(
                session_id=self.identity.session_id,
                generation=self.identity.generation,
                plan=self._system,
                authority=AuthorityLedger(self.authority),
                journal=journal,
                client=client,
                session_context_client=client,
                action_executor=_NoActions(),
                clock_ms=self._clock_ms,
                cancellation_signal=self.coordination,
            )
        except BaseException:
            await client.close()
            raise
        self._host_number += 1
        self._host_closed = False
        self.observe("host2.recover" if recovery else "host1.open")
        if recovery:
            await self.host.pump()
            # pump invokes the host's authority sink after reconstructing its ledger.
            await self.host._sync_authority_snapshot()
            self.observe("authority.sync")

    async def close_host(self) -> None:
        if self.host is not None and not self._host_closed:
            await self.host.close()
            self._host_closed = True
            self.observe(f"host{self._host_number}.close")
        elif self._journal is not None:
            self._journal.close()

    async def reconstruct(self) -> None:
        await self.close_host()
        self.coordination.check(self.run_id)
        await self._construct_host(recovery=True)

    async def _prompt(self, command_id: str, text: str) -> tuple[int, int]:
        self.coordination.check(self.run_id)
        self.active_turn_id = command_id
        try:
            await self.coordination.effect(
                self.backend.execute_prompt(
                    PrimePromptRequest(
                        command_id,
                        self.identity.session_id,
                        self.identity.generation,
                        text,
                    ),
                    signal=self.coordination,
                ),
                run_id=self.run_id,
            )
        except PrimeBackendBudgetError:
            raise P1RuntimeHostError("budget-limited") from None
        finally:
            self.active_turn_id = ""
        return self.application._backend_prompt_usage(command_id)

    async def execute_stage_one(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P1StageMilestone:
        self.coordination.check(run_id)
        self.observe("stage1.setup.start")
        first = await self._prompt(
            "p1-setup",
            P1_TASK_STATEMENT
            + "\nPerform only the setup cell now. Do not execute verification or continuation yet.",
        )
        self.observe("stage1.setup.complete")
        self.observe("stage1.verify.start")
        second = await self._prompt(
            "p1-verify",
            "Perform only the stage-one verification cell required by task_statement. Preserve the objects and file; do not continue to stage two.",
        )
        self.observe("stage1.verify.complete")
        self.observe("stage1.oracle.start")
        self._stage_one = self.oracle.verify_stage_one(self.worker.snapshot())
        self.observe("stage1.oracle.complete")
        return P1StageMilestone(
            "stage-one",
            self._stage_one.stage_one_effect_sha256,
            first[0] + second[0],
            first[1] + second[1],
        )

    async def execute_stage_two(
        self,
        *,
        run_id: str,
        release: P1StageTwoRelease,
        signal: CancellationSignal | None,
    ) -> P1StageMilestone:
        self.coordination.check(run_id)
        if release is not self._release:
            raise P1OperatorError()
        usage = await self._prompt(
            "p1-continue",
            "Complete only stage two from task_statement using the existing accumulator and unchanged stage-one.json bytes. Do not recreate or rewrite them.",
        )
        cell = self.worker.snapshot().cells[-1]
        return P1StageMilestone("stage-two", cell.sha256(), *usage)

    async def publish_milestone(
        self, *, run_id: str, milestone: P1StageMilestone
    ) -> None:
        self.coordination.publish(run_id, milestone)
        self.observe(
            "stage1.complete" if milestone.stage == "stage-one" else "stage2.complete"
        )

    async def wait_stage_two_release(
        self,
        *,
        run_id: str,
        stage_one: P1StageMilestone,
        signal: CancellationSignal | None,
    ) -> P1StageTwoRelease:
        return await self.coordination.wait_release(run_id, stage_one)

    async def report_execution_stopped(
        self, *, run_id: str, pending_classification: P1PendingClassification
    ) -> None:
        self.coordination.report_stopped(run_id, pending_classification)

    async def wait_finalization(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P1Finalization:
        return await self.coordination.wait_finalization(run_id)

    async def compact(self) -> SessionContextReceipt:
        assert self.host is not None and self.host.session_context_manager is not None
        try:
            summary = summarize_worker(
                self.worker.snapshot(),
                keep_recent_tokens=int(
                    _AGENT_SETTINGS["compaction"]["keepRecentTokens"]
                ),
            )
        except CodeSummaryError:
            raise P1OperatorError() from None
        if (
            summary.kind != CODE_SUMMARY_VERSION
            or not summary.below_native_threshold
            or not is_dedicated_code_summary(summary.text)
            or is_native_generic_summary(summary.text)
        ):
            raise P1OperatorError()
        # The handle stays opaque in the command journal. The text it resolves
        # to is the summary Pi persists, not a side list written afterwards.
        self.backend.bind_compaction_instruction(
            _COMPACTION_INSTRUCTION_REF, summary.text
        )
        command = SessionContextCommand(
            "compact-1",
            self.identity.session_id,
            self.identity.generation,
            1,
            "compact-key-1",
            "session.compact",
            {
                "continuation_id": self.identity.continuation_id,
                "instructions_ref": _COMPACTION_INSTRUCTION_REF,
                "budget": {
                    "controller_tokens": P1_COMPACTION_RESERVED_TOKENS,
                    "application_tokens": 0,
                    "child_tokens": 0,
                    "aggregate_tokens": P1_COMPACTION_RESERVED_TOKENS,
                    "cost_micros": P1_COMPACTION_COST_MICROS,
                    "deadline_ms": max(
                        1,
                        min(
                            600_000,
                            int((self.coordination.deadline - time.monotonic()) * 1000)
                            - 100,
                        ),
                    ),
                },
            },
        )
        self.observe("compact.admit")
        self.coordination.check(self.run_id)
        receipt = await self.coordination.effect(
            self.host.session_context_manager.execute(command), run_id=self.run_id
        )
        if receipt.status != "succeeded":
            raise P1RuntimeHostError("recovery-required")
        fields = receipt.payload["result"]
        if (
            not isinstance(fields, Mapping)
            or fields.get("summary_sha256") != summary.sha256
        ):
            raise P1OperatorError()
        self._code_summary = summary
        self.observe("compact.persist")
        return receipt

    async def resume(self, compact: SessionContextReceipt) -> None:
        assert self.host is not None and self.host.session_context_manager is not None
        self.observe("resume.admit")
        self.coordination.check(self.run_id)
        receipt = await self.coordination.effect(
            self.host.session_context_manager.execute(
                SessionContextCommand(
                    "resume-1",
                    self.identity.session_id,
                    self.identity.generation,
                    1,
                    "resume-key-1",
                    "session.continuation.resume",
                    {"continuation_id": self.identity.continuation_id},
                )
            ),
            run_id=self.run_id,
        )
        if receipt.status != "succeeded":
            raise P1RuntimeHostError("recovery-required")
        self.observe("resume.persist")
        checkpoint = self.application._backend_checkpoint()
        if checkpoint is None or checkpoint.outstanding_effect is not None:
            raise P1OperatorError()
        fields = compact.payload["result"]
        assert isinstance(fields, Mapping)
        before, after = fields["before_context_tokens"], fields["after_context_tokens"]
        assert type(before) is int and type(after) is int
        compact_digest = digest(compact.to_mapping())
        checkpoint_digest = digest(asdict(checkpoint))
        self.worker.mark_compact_checkpoint(
            P1WorkerCheckpoint(
                self.worker.identity_sha256,
                2,
                checkpoint_digest,
                compact_digest,
                self.identity.generation,
                1,
                self._host_number,
                before,
                after,
            )
        )
        self._release = P1StageTwoRelease(
            checkpoint_digest, compact_digest, before, after, self._host_number, P1_COMPACTION_RESERVED_TOKENS
        )
        self.coordination.release_stage_two(self._release)
        self.observe("stage2.release")

    async def verify(self, milestone: P1StageMilestone) -> None:
        assert self._stage_one is not None
        assert self.host is not None
        await self.host.pump()
        try:
            result = self.oracle.verify_stage_two(
                self.worker.snapshot(), self._stage_one
            )
        except P1OracleError as error:
            stage = _ORACLE_REJECT_STAGES.get(error.step or "")
            if stage is not None:
                self.observe(stage)
            raise
        if result.stage_two_effect_sha256 != milestone.effect_sha256:
            self.observe("oracle.reject.effect")
            raise P1OperatorError()
        self._oracle_result = result
        self.observe("oracle.pass")

    async def close_in_owner_order(self) -> P1OwnerCleanup:
        if self._cleanup is not None:
            return self._cleanup
        host_closed = bridge_closed = root_removed = False
        deadline = self.coordination.shutdown_deadline or (
            time.monotonic() + _CLEANUP_SECONDS
        )

        async def bounded(awaitable: Awaitable[object], *, share: int = 1) -> bool:
            task = asyncio.ensure_future(awaitable)
            task.add_done_callback(consume_task_result)
            limit = time.monotonic() + max(0, deadline - time.monotonic()) / share
            if not await wait_task_until(task, limit):
                task.cancel()
                return False
            try:
                task.result()
                return True
            except BaseException:
                return False

        effects_task = asyncio.create_task(self.coordination.abort_effects())
        effects_stopped = await bounded(effects_task, share=8)
        effects_stopped = effects_stopped and effects_task.result()
        try:
            host_closed = await bounded(self.close_host(), share=7)
        except BaseException:
            pass
        # P1 keeps independent access to the domain worker owner; Prime reaps
        # Pi and descriptors independently of the backend effect lock.
        if await bounded(self.worker_owner.close(), share=4):
            self.observe("worker.close")
        owner_task = asyncio.create_task(self.application.close())
        owner_returned = await bounded(owner_task, share=1)
        receipt = owner_task.result() if owner_returned else None
        self._prime_cleanup = receipt
        backend_closed = receipt is not None and receipt.complete
        pi_closed = receipt is not None and receipt.model_closed
        bridge_closed = receipt is not None and receipt.bridge_closed
        extension_closed = receipt is not None and receipt.extension_closed
        if backend_closed:
            self.observe("backend.close")
        if self._journal is not None:
            self._journal.close()
        if (
            self.worker.cleanup_receipt is not None
            and pi_closed
            and extension_closed
        ):
            try:
                if (
                    private_root_identity(self.private_root)
                    != self.identity.private_root_identity
                ):
                    raise P1OperatorError()
                shutil.rmtree(self.private_root)
                if self._cleanup_root is not None:
                    self._cleanup_root()
                root_removed = not self.private_root.exists()
            except Exception:
                pass
        worker_closed = self.worker_owner.cleanup_receipt is not None
        self._cleanup = P1OwnerCleanup(
            host_closed,
            backend_closed and effects_stopped,
            worker_closed,
            bridge_closed,
            root_removed,
        )
        return self._cleanup

    def finalization(self, cleanup: P1OwnerCleanup) -> P1Finalization:
        pending = self.coordination.pending
        if pending != "completed":
            return P1Finalization(pending, None)
        if (
            self._oracle_result is None
            or self.worker_owner.cleanup_receipt is None
            or not cleanup.complete
            or self._prime_cleanup is None
            or not self._prime_cleanup.complete
        ):
            raise P1OperatorError()
        sealed = seal_cleanup_receipt(
            self.oracle,
            self._oracle_result,
            self.worker_owner.cleanup_receipt,
            backend_closed=cleanup.backend_closed,
            pi_reaped=True,
            extension_closed=self._prime_cleanup.extension_closed,
            private_store_removed=cleanup.private_store_removed,
        )
        receipt = build_native_receipt(self.oracle, self._oracle_result, sealed)
        return P1Finalization("completed", receipt.sha256())


async def run_fixed_small_verification(
    resources: P1OperatorResources,
) -> P1PublicResult:
    if resources._consumed:
        raise P1OperatorError()
    resources._consumed = True
    coordination = resources.coordination
    runner: asyncio.Task[ApplicationRunResult] | None = None
    protocol_failure = False
    try:
        await coordination.effect(resources.open(), run_id=resources.run_id)
        resources.observe("runner.start")
        runner = asyncio.create_task(
            run_composed_application(
                resources.plan,
                implementations=resources.implementations,
                runtime=resources.runtime,
                run_id=resources.run_id,
                input_text="fixed-small-verification",
                host_services=resources.host_services,
            )
        )
        runner.add_done_callback(consume_task_result)
        await coordination.wait_milestone("stage-one", runner)
        compact = await resources.compact()
        await coordination.effect(resources.reconstruct(), run_id=resources.run_id)
        await resources.resume(compact)
        stage_two = await coordination.wait_milestone("stage-two", runner)
        await coordination.effect(resources.verify(stage_two), run_id=resources.run_id)
        if not await coordination.wait_stopped(
            runner, timeout=max(0, coordination.deadline - time.monotonic())
        ):
            raise P1OperatorError()
    except BaseException as error:
        coordination.shutdown_deadline = time.monotonic() + _CLEANUP_SECONDS
        classification = (
            "cancelled"
            if isinstance(error, asyncio.CancelledError)
            else (
                error.classification
                if isinstance(error, P1RuntimeHostError)
                else "recovery-required"
            )
        )
        coordination.request_stop(classification)
        if runner is not None:
            if not await coordination.wait_stopped(
                runner, timeout=min(0.25, _CLEANUP_SECONDS / 4)
            ):
                protocol_failure = True
        else:
            protocol_failure = True
    if coordination.shutdown_deadline is None:
        coordination.shutdown_deadline = time.monotonic() + _CLEANUP_SECONDS
    shutdown_deadline = coordination.shutdown_deadline
    cleanup_task = asyncio.create_task(resources.close_in_owner_order())
    cleanup_task.add_done_callback(consume_task_result)
    cleanup = None
    try:
        if not await wait_task_until(cleanup_task, shutdown_deadline):
            raise P1OperatorError()
        cleanup = cleanup_task.result()
    except BaseException:
        protocol_failure = True
        cleanup_task.cancel()
    finalization = None
    if cleanup is None or not cleanup.complete:
        protocol_failure = True
    if not protocol_failure:
        try:
            assert cleanup is not None
            finalization = resources.finalization(cleanup)
            coordination.release_finalization(finalization, cleanup)
        except BaseException:
            protocol_failure = True
    if runner is not None:
        if protocol_failure and not runner.done():
            runner.cancel()
        try:
            if not await wait_task_until(
                runner, shutdown_deadline, cancel=protocol_failure
            ):
                raise P1OperatorError()
            runner.result()
        except BaseException:
            if finalization is None or finalization.classification == "completed":
                protocol_failure = True
            if not runner.done():
                runner.cancel()
    # The temporary backend has been removed; retained public alarms are the
    # external evidence, never a claim that its JSONL file survived cleanup.
    sink = getattr(resources, 'resource_alarm_sink', None)
    alarms = tuple(dict(alarm) for alarm in sink.alarms) if sink is not None else ()
    if protocol_failure:
        return P1PublicResult(resources.run_id, "protocol-failure", resource_alarms=alarms)
    resources.observe("runner.terminal")
    assert finalization is not None
    summary = resources._code_summary
    if finalization.classification == "completed" and (
        summary is None
        or summary.kind != CODE_SUMMARY_VERSION
        or not summary.below_native_threshold
        or not summary.bindings
        or not summary.sha256
        or not summary.text
    ):
        return P1PublicResult(resources.run_id, "protocol-failure", resource_alarms=alarms)
    if summary is None:
        return P1PublicResult(
            resources.run_id, finalization.classification, finalization.receipt_sha256, alarms
        )
    return P1PublicResult(
        resources.run_id,
        finalization.classification,
        finalization.receipt_sha256,
        alarms,
        summary.kind,
        summary.sha256,
        summary.bindings,
        summary.text,
        summary.below_native_threshold,
    )


class _P1Services:
    """Domain execution stays on the worker and coordination's owning loop."""

    def __init__(self, worker, owner):
        self.worker, self.owner = worker, owner
        self.resources = None
        self._loop = asyncio.get_running_loop()
        self._stopping = False

    @property
    def identity_sha256(self):
        return self.owner.identity_sha256

    def validate_lifecycle(self):
        return self.owner.validate_lifecycle()

    async def _on_loop(self, operation):
        if asyncio.get_running_loop() is self._loop:
            return await operation
        try:
            future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        except BaseException:
            operation.close()
            raise
        return await asyncio.wrap_future(future)

    async def execute(self, request_id, code, signal):
        return await self._on_loop(self._execute(request_id, code, signal))

    async def _execute(self, request_id, code, signal):
        resources = self.resources
        if self._stopping or resources is None or signal.cancelled:
            raise P1OperatorError()
        try:
            resources.coordination.check(resources.run_id)
            result = await self.worker.execute_cell(
                P1CellRequest(request_id, resources.active_turn_id, code))
            return PrimeToolResult(result.request_id, result.status,
                                   ({"type": "text", "text": result.output},))
        except BaseException:
            resources.coordination.request_stop("recovery-required")
            raise

    async def call(self, request_id, method, params, signal, **kwargs):
        raise P1OperatorError()

    def request_stop(self):
        self._stopping = True

    async def close(self):
        if self.owner.cleanup_receipt is not None:
            return
        await self._on_loop(self.owner.close())


# The one fixed model host this preset runs against. Provider, model, deadline,
# budget and price are preset values rather than invocation knobs: a user-facing
# small verification must not ask for provider, model, cost or deadline
# selection, so the integration fixes them here and exposes only public status.
_PROVIDER = "deepseek"
_MODEL = "deepseek-flash"
_DEADLINE_SECONDS = 600.0
_AGGREGATE_TOKENS = 64_000
_COST_MICROS = 500_000
_LIMITS = AsterionPrimeLimits(8, 4, 600_000)
# Exact deepseek/deepseek-flash rates from the approved shipped Pi metadata:
# USD 0.30 input / 1.20 output per million; cached input is charged in full.
_PRICE = ModelPrice(300_000, 1_200_000)
# Supplied branch estimates for preflight arithmetic; these are not native
# input/output caps. The legacy output quote remains an inherited estimate.
_COMPACTION_INPUT_CAPS = (4096, 4096)
_COMPACTION_OUTPUT_CAPS = (3276, 3276)
# The one private instruction this application sends with a compaction. Pi owns
# the summary and its prompt, so what has to reach the model is the note that
# keeps the live IPython kernel names in it -- the reason a persistent-kernel
# application exists at all. The protocol carries only the handle below, so the
# text stays out of the canonical control journal, and the text itself is owned
# by ``agents/prime/summarization.py`` rather than restated here.
_COMPACTION_INSTRUCTION_REF = "prime-kernel-note-v1"
_COMPACTION_INSTRUCTIONS = {
    _COMPACTION_INSTRUCTION_REF: compaction_custom_instructions()
}
# The installed Pi distribution names its agent directory through this variable
# and reads its settings from ``settings.json`` inside it.
_AGENT_DIR_ENV = "PI_CODING_AGENT_DIR"
_AGENT_SETTINGS = {
    "compaction": {"enabled": False, "reserveTokens": 16384, "keepRecentTokens": 256},
    "retry": {"enabled": False},
}
_IPYTHON_VERSION = "8.39.0" if sys.version_info[:2] == (3, 10) else "9.17.1"


@dataclass(frozen=True, slots=True)
class _Preflight:
    """Every operator-owned value one P1 preset invocation resolves to."""

    operator_root: Path
    environment: Mapping[str, str]
    worker_python: Path
    executable: Path
    entry: Path | None
    effort: str
    extension_path: Path


def _extension_path() -> Path:
    """Resolve P1's core-only artifact from the installed wheel."""
    resource = importlib_resources.files("asterion.applications.prime").joinpath(
        "resources/ipython-extension.mjs"
    )
    path = Path(str(resource))
    if not path.is_file():
        raise P1OperatorError()
    return path.resolve(strict=True)


def _preflight(environment: Mapping[str, str]) -> _Preflight:
    """Refuse source execution, then resolve every operator-owned input.

    Mirrors the P7 operator contract: the operator root is the mounted
    checkout, and the running distribution must be installed outside it so a
    source tree can never be executed in its place. The node executable, Pi
    entry and extension are operator-owned values the preset exports, so
    nothing here derives a path from a sibling checkout layout, and no module
    inside a checkout supplies compaction semantics.
    """
    import asterion

    configured = environment.get(live.OPERATOR_ROOT_ENV, "").strip()
    if not configured:
        raise P1OperatorError()
    try:
        root = Path(configured).resolve(strict=True)
    except OSError:
        raise P1OperatorError() from None
    package = Path(str(asterion.__file__)).resolve(strict=True)
    if package.is_relative_to(root) or "site-packages" not in package.parts:
        raise P1OperatorError()
    if not root.is_dir():
        raise P1OperatorError()
    # Preserve the isolated environment's interpreter path. Resolving its
    # symlink would escape the environment and lose the installed extras.
    worker = Path(sys.executable).absolute()
    if not worker.is_file():
        raise P1OperatorError()
    # A probe imports IPython but starts no worker and no Pi session.
    try:
        probe = subprocess.run(
            (
                str(worker),
                "-I",
                "-c",
                f"import IPython,sys; assert IPython.__version__ == {_IPYTHON_VERSION!r}",
            ),
            check=True,
            capture_output=True,
            timeout=10,
            env={"LANG": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        raise P1OperatorError() from None
    if probe.stdout or probe.stderr:
        raise P1OperatorError()
    try:
        resolved = live.load_operator_environment(root)
        if not resolved.get('DEEPSEEK_API_KEY', '').strip():
            raise P1OperatorError()
        executable, entry = live.resolve_node(resolved), live.resolve_pi_entry(resolved)
        effort = resolve_pi_effort(resolved, default='medium')
        extension = _extension_path()
    except live.P7LiveSolveError:
        raise P1OperatorError() from None
    # Check supplied branch estimates under the injected application policy.
    try:
        quote_compaction_reservation(
            branch_input_caps=_COMPACTION_INPUT_CAPS,
            branch_output_caps=_COMPACTION_OUTPUT_CAPS,
            price=_PRICE, policy=P1_COMPACTION_POLICY, config_source="application",
        )
    except (TypeError, ValueError):
        raise P1OperatorError() from None
    return _Preflight(root, resolved, worker, executable, entry, effort, extension)


async def _build_resources(preflight: _Preflight) -> P1OperatorResources:
    """Provide domain executor and operator data to the Prime resource owner."""
    temporary = tempfile.TemporaryDirectory(prefix="asterion-native-p1-")
    root = Path(temporary.name).resolve()
    application = worker = None
    try:
        # This configuration directory belongs to this operator invocation.
        # No caller profile, auth or catalog file is copied or changed.
        agent_root = root / "agent"
        agent_root.mkdir(mode=0o700)
        (agent_root / "settings.json").write_text(json.dumps(_AGENT_SETTINGS), encoding="utf-8")
        environment = dict(preflight.environment)
        environment[_AGENT_DIR_ENV] = str(agent_root)
        deadline = time.monotonic() + _DEADLINE_SECONDS
        task_deadline = TaskDeadline(deadline_monotonic=deadline,
                                     deadline_epoch=time.time() + _DEADLINE_SECONDS)
        private = root / "backend"
        private.mkdir(mode=0o700)
        run_id = "p1-" + secrets.token_hex(12)
        backend_spec = PrimeBackendSpec(
            run_id, 1, private, "p1-continuation", _LIMITS, _AGGREGATE_TOKENS,
            _COST_MICROS, _PRICE, "authority-1", _COMPACTION_INSTRUCTIONS,
            compat_provider_id="prime-applications",
            compaction_policy=P1_COMPACTION_POLICY, compaction_policy_source="application")
        alarm_sink = ResourceAlarmSink(root / 'resource-alarms.jsonl', emit=_public_resource_alarm)
        application = prepare_prime_application(
            PrimeApplicationSpec("prime.ipython-coding", "1.0.0", "persistent-code-tools",
                tools=PrimeToolModuleArtifact(preflight.extension_path, CORE_TOOL_REGISTRY)),
            PrimeOperatorContext(preflight.executable, preflight.entry, root, _PROVIDER, _MODEL,
                preflight.effort, environment, task_deadline, diagnostics=alarm_sink), authorization=backend_spec)
        worker = P1WorkerProcess(deadline=deadline, interpreter=str(preflight.worker_python))
        await worker.start()
        owner = P1WorkerOwnerAdapter(worker)
        services = _P1Services(worker, owner)
        attachment = await application.open_backend(spec=backend_spec, services=services)
        resources = P1OperatorResources(
            application=application, backend=attachment, worker=worker, worker_owner=owner,
            private_root=private, journal_root=root / "journal", run_id=run_id,
            deadline=deadline, cleanup_root=temporary.cleanup, resource_alarm_sink=alarm_sink)
        services.resources = resources
        return resources
    except BaseException:
        if worker is not None:
            await worker.close()
        if application is not None:
            await application.close()
        temporary.cleanup()
    raise P1OperatorError()


def _run_operator(invoke: Callable[[], Awaitable[P1PublicResult]]) -> P1PublicResult:
    """Own loop shutdown without asyncio.run's unbounded cancellation gather."""
    loop = asyncio.new_event_loop()
    # All public diagnostics pass through the fixed result projector. Unfinished
    # task destruction must not print coroutine paths or private exceptions.
    loop.set_exception_handler(lambda _loop, _context: None)

    async def supervise() -> P1PublicResult:
        task = asyncio.ensure_future(invoke())
        result = P1PublicResult("p1-unavailable", "protocol-failure")
        if await wait_task_until(task, time.monotonic() + 600 + _CLEANUP_SECONDS):
            try:
                result = task.result()
            except BaseException:
                pass
        shutdown_deadline = time.monotonic() + _CLEANUP_SECONDS
        current = asyncio.current_task()
        pending = tuple(
            item
            for item in asyncio.all_tasks()
            if item is not current and not item.done()
        )
        for item in pending:
            item.cancel()
        for item in pending:
            if not await wait_task_until(item, shutdown_deadline, cancel=True):
                result = P1PublicResult(result.run_id, "protocol-failure", resource_alarms=result.resource_alarms)
        finalizer = asyncio.create_task(loop.shutdown_asyncgens())
        if not await wait_task_until(finalizer, shutdown_deadline):
            result = P1PublicResult(result.run_id, "protocol-failure", resource_alarms=result.resource_alarms)
        # loop.close uses shutdown(wait=False); a default-executor join is never
        # allowed to undo the bounded coroutine/resource shutdown above.
        return result

    try:
        return loop.run_until_complete(supervise())
    finally:
        loop.close()


def main(argv: list[str] | None = None) -> int:
    """The only external input is the literal Make preset invocation."""
    result = None
    try:
        if sys.argv[1:] if argv is None else argv:
            raise P1OperatorError()
        preflight = _preflight(os.environ)

        async def invoke() -> P1PublicResult:
            resources = await _build_resources(preflight)
            resources.observe = _public_progress
            return await run_fixed_small_verification(resources)

        result = _run_operator(invoke)
    except BaseException:
        pass
    if result is None:
        print('{"status":"preflight-rejected"}')
        return 2
    public = asdict(result)
    public["resource_alarms"] = public_resource_alarms(result.resource_alarms)
    print(json.dumps(public, sort_keys=True, separators=(",", ":")))
    return 0 if result.status == "completed" else 1


def _entrypoint() -> None:
    status = main()
    sys.stdout.flush()
    sys.stderr.flush()
    if status == 1:
        # Python joins default-executor threads again during interpreter exit.
        # A failed owner cannot regain an unbounded wait after public failure.
        os._exit(status)
    raise SystemExit(status)


if __name__ == "__main__":
    _entrypoint()
