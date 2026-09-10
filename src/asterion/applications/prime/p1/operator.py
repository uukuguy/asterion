"""Operator-owned native P1 control reconstruction and resource lifetime."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, replace
from importlib import resources as package_resources
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import MappingProxyType

from asterion.agents.prime.backend import (
    PrimeBackendBudgetError,
    PrimePromptRequest,
    PrimeSessionBackend,
)
from asterion.agents.prime.compaction_budget import (
    ModelPrice,
    quote_compaction_reservation,
)
from asterion.agents.prime.context import PrimeContextWitnessSession
from asterion.agents.prime.session import AsterionPrimeLimits
from asterion.agents.prime.state import PrimeBackendIdentity
from asterion.agents.prime.store import FilePrimeSessionStore, private_root_identity
from asterion.applications.first_party_packages import (
    create_prime_ipython_coding_native_package,
)
from asterion.applications.prime import create_provider
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
    P1OracleReceipt,
    P1StageOneReceipt,
)
from asterion.applications.prime.p1.receipt import (
    build_native_receipt,
    seal_cleanup_receipt,
)
from asterion.applications.prime.p1.runtime_binding import (
    P1_RUNTIME_OPTIONS,
    P1WorkerOwnerAdapter,
    build_p1_runtime,
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
from asterion.runner.application import ApplicationRunResult
from asterion.runner.composed import run_composed_application
from asterion.runtime.factory import RuntimeFactoryContext, RuntimeFactoryRegistry
from asterion.runtime.host import CancellationSignal
from asterion.runtimes.pi_extensions import (
    PiExtensionBinding,
    PiExtensionDependencies,
    PiExtensionLease,
)
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession, normalize_pi_usage

_CLEANUP_SECONDS = 5.0


class P1OperatorError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("P1 operator is unavailable")


@dataclass(frozen=True, slots=True)
class P1PublicResult:
    run_id: str
    status: str
    receipt_sha256: str | None = None


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
        "resume.admit",
        "resume.persist",
        "runner.start",
        "runner.terminal",
        "stage1.complete",
        "stage2.complete",
        "stage2.release",
        "worker.close",
    }
)


def _public_progress(stage: str) -> None:
    if stage not in _PUBLIC_PROGRESS_STAGES:
        raise P1OperatorError()
    print(
        json.dumps({"stage": stage}, separators=(",", ":"), sort_keys=True),
        file=sys.stderr,
        flush=True,
    )


class _NoActions:
    async def execute(self, *args: object, **kwargs: object):
        raise P1OperatorError()


class P1OperatorResources:
    """Concrete runtime service and control owner over one preflighted backend."""

    def __init__(
        self,
        *,
        backend: PrimeSessionBackend,
        store: FilePrimeSessionStore,
        worker: P1WorkerProcess,
        worker_owner: P1WorkerOwnerAdapter,
        extension_lease: PiExtensionLease,
        private_root: Path,
        journal_root: Path,
        run_id: str,
        deadline: float,
        observe: Callable[[str], None] = lambda _: None,
        close_bridge: Callable[[], Awaitable[None]] | None = None,
        cleanup_root: Callable[[], None] | None = None,
        close_pi: Callable[[], Awaitable[None]] | None = None,
        close_witness: Callable[[], None] | None = None,
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
        ):
            raise P1OperatorError()
        self.backend, self.store, self.worker, self.worker_owner = (
            backend,
            store,
            worker,
            worker_owner,
        )
        self.extension_lease = extension_lease
        self.private_root, self.journal_root = private_root, journal_root
        self.identity, self.run_id = identity, run_id
        self.coordination = P1Coordination(run_id=run_id, deadline=deadline)
        self.oracle = P1Oracle(worker, kernel_generation=identity.generation)
        self.observe, self._close_bridge = observe, close_bridge
        self._cleanup_root = cleanup_root
        self._close_pi, self._close_witness = close_pi, close_witness
        self.active_turn_id = ""
        self._host_number = 0
        self._host_closed = True
        self._cleanup: P1OwnerCleanup | None = None
        self._stage_one: P1StageOneReceipt | None = None
        self._oracle_result: P1OracleReceipt | None = None
        self._release: P1StageTwoRelease | None = None
        self._consumed = False
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
        provider = create_provider()
        # Resolve only the selected application's exact package closure.
        provider = replace(
            provider,
            applications=tuple(
                app
                for app in provider.applications
                if app.application_id == "prime.ipython-coding"
            ),
        )
        provider = compose_installed_provider(
            provider,
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
                "prime.pi-extension": extension_lease,
                "prime.private-trace": store,
                "prime.session-backend": self,
            }
        )
        self.runtime = build_p1_runtime(
            RuntimeFactoryContext(
                "prime-applications",
                "prime.ipython-coding",
                "1.0.0",
                "asterion.prime",
                assembly.path,
                P1_RUNTIME_OPTIONS,
                self.host_services,
            )
        )
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
        pi_extension: object,
        private_trace: object,
    ) -> None:
        if (
            ipython is not self.worker
            or oracle is not self.oracle
            or pi_extension is not self.extension_lease
            or private_trace is not self.store
        ):
            raise P1OperatorError()
        self.worker_owner.validate_lifecycle()
        self.extension_lease.validate_launch()

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
                host_services={"prime.session-backend": self.backend},
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
        recovered = self.store.recover_checkpoint()
        if recovered is None:
            raise P1OperatorError()
        incoming = outgoing = 0
        for turn in json.loads(recovered.transcript):
            if turn["command_id"] == command_id:
                for event in turn["events"]:
                    if event["type"] == "message_end":
                        usage = normalize_pi_usage(event["payload"])
                        if usage is not None:
                            incoming += usage["input_tokens"]
                            outgoing += usage["output_tokens"]
        return incoming, outgoing

    async def execute_stage_one(
        self, *, run_id: str, signal: CancellationSignal | None
    ) -> P1StageMilestone:
        self.coordination.check(run_id)
        first = await self._prompt(
            "p1-setup",
            P1_TASK_STATEMENT
            + "\nPerform only the setup cell now. Do not execute verification or continuation yet.",
        )
        second = await self._prompt(
            "p1-verify",
            "Perform only the stage-one verification cell required by task_statement. Preserve the objects and file; do not continue to stage two.",
        )
        self._stage_one = self.oracle.verify_stage_one(self.worker.snapshot())
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
        command = SessionContextCommand(
            "compact-1",
            self.identity.session_id,
            self.identity.generation,
            1,
            "compact-key-1",
            "session.compact",
            {
                "continuation_id": self.identity.continuation_id,
                "instructions_ref": None,
                "budget": {
                    "controller_tokens": 16_000,
                    "application_tokens": 0,
                    "child_tokens": 0,
                    "aggregate_tokens": 16_000,
                    "cost_micros": 125_000,
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
        checkpoint = self.store.recover_checkpoint()
        if checkpoint is None or checkpoint.checkpoint.outstanding_effect is not None:
            raise P1OperatorError()
        fields = compact.payload["result"]
        assert isinstance(fields, Mapping)
        before, after = fields["before_context_tokens"], fields["after_context_tokens"]
        assert type(before) is int and type(after) is int
        compact_digest = digest(compact.to_mapping())
        checkpoint_digest = digest(asdict(checkpoint.checkpoint))
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
            checkpoint_digest, compact_digest, before, after, self._host_number, 16_000
        )
        self.coordination.release_stage_two(self._release)
        self.observe("stage2.release")

    async def verify(self, milestone: P1StageMilestone) -> None:
        assert self._stage_one is not None
        assert self.host is not None
        await self.host.pump()
        result = self.oracle.verify_stage_two(self.worker.snapshot(), self._stage_one)
        if result.stage_two_effect_sha256 != milestone.effect_sha256:
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
        try:
            if self._close_bridge is not None:
                bridge_closed = await bounded(self._close_bridge(), share=6)
            else:
                bridge_closed = True
        except BaseException:
            pass
        # Backend close aborts/settles active effects, then closes worker, Pi,
        # witness, extension and store exactly once in that owner order.
        # The worker handle is independent of a stuck host/effect/backend lock.
        if await bounded(self.worker_owner.close(), share=4):
            self.observe("worker.close")
        backend_task = asyncio.create_task(self.backend.close())
        backend_returned = await bounded(backend_task, share=3)
        backend_closed = backend_returned and backend_task.result().complete
        pi_closed = backend_returned and backend_task.result().pi_closed
        if backend_closed:
            self.observe("backend.close")
        elif not backend_returned or not pi_closed:
            # Do not trust an unresponsive backend to reach its child owners.
            if self._close_pi is not None:
                pi_closed = await bounded(self._close_pi(), share=2)
            if self._close_witness is not None:
                self._close_witness()
            self.extension_lease.close()
            self.store.close()
        if self._journal is not None:
            self._journal.close()
        if (
            self.worker.cleanup_receipt is not None
            and pi_closed
            and self.extension_lease.closed
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
        ):
            raise P1OperatorError()
        sealed = seal_cleanup_receipt(
            self.oracle,
            self._oracle_result,
            self.worker_owner.cleanup_receipt,
            backend_closed=cleanup.backend_closed,
            pi_reaped=True,
            extension_closed=self.extension_lease.closed,
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
    if protocol_failure:
        return P1PublicResult(resources.run_id, "protocol-failure")
    resources.observe("runner.terminal")
    assert finalization is not None
    return P1PublicResult(
        resources.run_id, finalization.classification, finalization.receipt_sha256
    )


class _P1Bridge:
    """One bounded private socket server on the worker's owning event loop."""

    def __init__(self, channel: socket.socket, resources: P1OperatorResources) -> None:
        self._channel, self._resources = channel, resources
        channel.setblocking(False)
        self._task = asyncio.create_task(self._serve())
        self._task.add_done_callback(consume_task_result)
        self._closed = False

    async def _serve(self) -> None:
        pending = bytearray()
        loop = asyncio.get_running_loop()
        try:
            while True:
                chunk = await loop.sock_recv(self._channel, 4096)
                if not chunk:
                    return
                pending.extend(chunk)
                if len(pending) > 131_072:
                    raise P1OperatorError()
                if b"\n" not in pending:
                    continue
                raw, _, trailing = pending.partition(b"\n")
                if trailing:
                    raise P1OperatorError()
                pending.clear()
                request = json.loads(raw)
                if (
                    type(request) is not dict
                    or set(request) != {"protocol", "request_id", "type", "code"}
                    or request["protocol"] != "asterion.prime-ipython/v1"
                    or request["type"] != "execute"
                ):
                    raise P1OperatorError()
                self._resources.coordination.check(self._resources.run_id)
                result = await self._resources.worker.execute_cell(
                    P1CellRequest(
                        request["request_id"],
                        self._resources.active_turn_id,
                        request["code"],
                    )
                )
                response = {
                    "protocol": "asterion.prime-ipython/v1",
                    "request_id": result.request_id,
                    "type": "result",
                    "status": result.status,
                    "output": result.output,
                }
                await loop.sock_sendall(
                    self._channel,
                    json.dumps(response, separators=(",", ":")).encode() + b"\n",
                )
        except asyncio.CancelledError:
            return
        except Exception:
            self._resources.coordination.request_stop("recovery-required")

    async def close(self) -> None:
        if self._closed:
            return
        self._task.cancel()
        deadline = self._resources.coordination.shutdown_deadline or (
            time.monotonic() + _CLEANUP_SECONDS
        )
        closed = await wait_task_until(self._task, deadline, cancel=True)
        self._channel.close()
        self._closed = closed
        if not closed:
            raise P1OperatorError()


@dataclass(frozen=True, slots=True, repr=False)
class _Preflight:
    operator_root: Path
    worker_python: Path
    node: Path
    source_root: Path
    extension: Path
    dependencies: PiExtensionDependencies
    price: ModelPrice
    environment: Mapping[str, str]


_PRICE_PROBE = r"""
import {pathToFileURL} from 'node:url';
const [verifier, root, closure, artifact] = process.argv.slice(2);
const {verifyCompactionLock, guardCompactionImports} = await import(pathToFileURL(verifier));
const verified = verifyCompactionLock(root, closure, artifact);
const guard = guardCompactionImports(verified);
try {
  const {getModel} = await import(pathToFileURL(root + '/packages/ai/dist/models.js'));
  const model = getModel('deepseek', 'deepseek-v4-flash');
  const {ENV_AGENT_DIR} = await import(pathToFileURL(root + '/packages/coding-agent/dist/config.js'));
  const {prepareCompaction} = await import(pathToFileURL(root + '/packages/coding-agent/dist/core/compaction/compaction.js'));
  const entries = ['user', 'assistant', 'user', 'assistant'].map((role, index) => ({
    type: 'message', id: 'fixture-' + index, parentId: index ? 'fixture-' + (index - 1) : null,
    timestamp: '2000-01-01T00:00:00.000Z',
    message: {role, content: [{type: 'text', text: 'preflight fixture '.repeat(128)}], timestamp: 0},
  }));
  const prepared = prepareCompaction(entries, {enabled: false, reserveTokens: 4096, keepRecentTokens: 256});
  if (!prepared || (!prepared.messagesToSummarize.length && !prepared.turnPrefixMessages.length)) throw Error();
  const cost = [model.cost.input, model.cost.output].map(value => {
    if (!Number.isFinite(value) || value < 0 || !Number.isSafeInteger(value * 1000000)) throw Error();
    return value * 1000000;
  });
  process.stdout.write(JSON.stringify({input: cost[0], output: cost[1], agent_dir_variable: ENV_AGENT_DIR}));
} finally {guard.deregister();}
"""


def _pi_command(
    node: Path, source: Path, extension_args: tuple[str, ...]
) -> tuple[str, ...]:
    # main.js is in the verified closure. The fixed inline entry introduces no
    # second provider adapter and never reads operator or model configuration.
    entry = "import {pathToFileURL} from 'node:url'; const {main} = await import(pathToFileURL(process.argv[1])); await main(process.argv.slice(2));"
    return (
        str(node),
        "--input-type=module",
        "--eval",
        entry,
        str(source / "packages/coding-agent/dist/main.js"),
        "--mode",
        "rpc",
        "--print",
        "--no-builtin-tools",
        "--tools",
        "ipython",
        "--approve",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--provider",
        "deepseek",
        "--model",
        "deepseek-v4-flash",
        *extension_args,
    )


def _preflight(environment: Mapping[str, str]) -> _Preflight:
    """Read operator configuration only after rejecting source execution."""
    import asterion

    root = Path(environment["ASTERION_PRIME_OPERATOR_ROOT"]).resolve(strict=True)
    package = Path(str(asterion.__file__)).resolve(strict=True)
    if package.is_relative_to(root) or "site-packages" not in package.parts:
        raise P1OperatorError()
    # Preserve the isolated environment's interpreter path. Resolving its
    # symlink would escape the environment and lose the installed Prime extras.
    worker = Path(sys.executable).absolute()
    if not worker.is_file():
        raise P1OperatorError()
    # A probe imports IPython but does not start a worker or Pi session.
    probe = subprocess.run(
        (
            str(worker),
            "-I",
            "-c",
            "import IPython,sys; assert IPython.__version__ == ('8.39.0' if sys.version_info[:2] == (3,10) else '9.17.1')",
        ),
        check=True,
        capture_output=True,
        timeout=10,
        env={"LANG": "C.UTF-8"},
    )
    if probe.stdout or probe.stderr:
        raise P1OperatorError()
    from dotenv import dotenv_values

    configured = dotenv_values(root / ".env", interpolate=False)
    key = configured.get("DEEPSEEK_API_KEY") or environment.get("DEEPSEEK_API_KEY")
    if type(key) is not str or not key.strip():
        raise P1OperatorError()
    source = Path(
        environment.get(
            "ASTERION_PRIME_SOURCE_ROOT", str(root / "3th-party/prime-agent")
        )
    ).absolute()
    if source.resolve(strict=True) != source:
        raise P1OperatorError()
    node = Path(environment["ASTERION_PRIME_NODE"]).resolve(strict=True)
    if not node.is_file():
        raise P1OperatorError()
    resources = (
        Path(str(package_resources.files("asterion.applications.prime"))) / "resources"
    )
    verifier, closure = (
        resources / "pi-compaction-verifier.mjs",
        resources / "pi-compaction-lock.json",
    )
    artifact = (
        Path(str(package_resources.files("asterion.control.providers.prime")))
        / "resources/prime-artifact-lock.json"
    )
    dependencies = PiExtensionDependencies(
        verifier,
        source,
        closure,
        artifact,
        node,
        {
            name: "string"
            if name in {"summarizationSystemPrompt", "turnPrefixPrompt"}
            else "function"
            for name in (
                "buildSessionContext",
                "buildSummarizationPrompt",
                "convertToLlm",
                "prepareCompaction",
                "serializeConversation",
                "summarizationSystemPrompt",
                "turnPrefixPrompt",
            )
        },
    )
    priced = subprocess.run(
        (
            str(node),
            "--input-type=module",
            "--eval",
            _PRICE_PROBE,
            str(node),
            str(verifier),
            str(source),
            str(closure),
            str(artifact),
        ),
        check=True,
        capture_output=True,
        timeout=30,
        env={"PATH": os.defpath, "LANG": "C.UTF-8"},
    )
    if len(priced.stdout) > 4096 or priced.stderr:
        raise P1OperatorError()
    value = json.loads(priced.stdout)
    if (
        type(value) is not dict
        or set(value) != {"input", "output", "agent_dir_variable"}
        or value["agent_dir_variable"]
        not in {"PI_CODING_AGENT_DIR", "PRIME_AGENT_CODING_AGENT_DIR"}
    ):
        raise P1OperatorError()
    price = ModelPrice(value["input"], value["output"])
    quote_compaction_reservation(
        branch_input_caps=(4096, 4096), branch_output_caps=(3276, 3276), price=price
    )
    return _Preflight(
        root,
        worker,
        node,
        source,
        resources / "ipython-extension.mjs",
        dependencies,
        price,
        MappingProxyType(
            {
                "DEEPSEEK_API_KEY": key,
                "LANG": "C.UTF-8",
                "P1_AGENT_DIR_VARIABLE": value["agent_dir_variable"],
            }
        ),
    )


async def _build_resources(preflight: _Preflight) -> P1OperatorResources:
    """Complete lock/lease preflight before the first worker or model process."""
    temporary = tempfile.TemporaryDirectory(prefix="asterion-native-p1-")
    root = Path(temporary.name).resolve()
    bridge_parent, bridge_child = socket.socketpair()
    witness_parent, witness_child = socket.socketpair()
    lease = None
    worker = backend = store = bridge = witness = None
    try:
        nonce = secrets.token_hex(32)
        descriptors = tuple(sorted((bridge_child.fileno(), witness_child.fileno())))
        binding = PiExtensionBinding(
            "prime.ipython",
            preflight.extension,
            ("prime.tool.ipython",),
            descriptors,
            {
                "ASTERION_PRIME_IPYTHON_FD": str(bridge_child.fileno()),
                "ASTERION_PRIME_IPYTHON_CONTEXT_FD": str(witness_child.fileno()),
                "ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE": nonce,
            },
            dependencies=preflight.dependencies,
        )
        lease = binding.preflight()
        bridge_child.close()
        witness_child.close()
        agent_root = root / "agent"
        agent_root.mkdir(mode=0o700)
        (agent_root / "settings.json").write_text(
            json.dumps(
                {
                    "compaction": {
                        "enabled": False,
                        "reserveTokens": 4096,
                        "keepRecentTokens": 256,
                    },
                    "retry": {"enabled": False},
                }
            ),
            encoding="utf-8",
        )
        environment = dict(preflight.environment)
        agent_variable = environment.pop("P1_AGENT_DIR_VARIABLE")
        environment[agent_variable] = str(agent_root)
        environment.update(lease.environment)
        command = _pi_command(
            preflight.node, preflight.source_root, lease.command_args()
        )
        deadline = time.monotonic() + 600
        worker = P1WorkerProcess(
            deadline=deadline, interpreter=str(preflight.worker_python)
        )
        await worker.start()
        owner = P1WorkerOwnerAdapter(worker)
        private = root / "backend"
        private.mkdir(mode=0o700)
        limits = AsterionPrimeLimits(8, 4, 600_000)
        run_id = "p1-" + secrets.token_hex(12)
        identity = PrimeBackendIdentity(
            run_id,
            1,
            "prime-applications",
            "prime.ipython-coding",
            "1.0.0",
            "asterion.prime",
            digest(command),
            binding.binding_fingerprint,
            worker.identity_sha256,
            "p1-continuation",
            private_root_identity(private),
            digest(
                {**asdict(limits), "aggregate_tokens": 64_000, "cost_micros": 500_000}
            ),
        )
        store = FilePrimeSessionStore(private, identity)
        rpc = PiRpcSession(
            PiRpcConfig(
                command=command,
                cwd=root,
                environment=environment,
                inherited_fds=lease.inherited_fds,
                deadline_seconds=600,
                compact_events=True,
            )
        )
        witness = PrimeContextWitnessSession(
            witness_parent,
            launch_nonce=nonce,
            timeout_seconds=60,
            mark_uncertain=lambda: None,
        )
        backend = PrimeSessionBackend(
            identity=identity,
            store=store,
            rpc_session=rpc,
            extension_binding=binding,
            extension_lease=lease,
            approved_command=command,
            approved_environment=environment,
            limits=limits,
            aggregate_tokens=64_000,
            cost_micros=500_000,
            model_price=preflight.price,
            witness=witness,
            tool_executor=owner,
            authority_id="authority-1",
        )
        resources = P1OperatorResources(
            backend=backend,
            store=store,
            worker=worker,
            worker_owner=owner,
            extension_lease=lease,
            private_root=private,
            journal_root=root / "journal",
            run_id=run_id,
            deadline=deadline,
            cleanup_root=temporary.cleanup,
            close_pi=lambda: _force_close_pi(rpc),
            close_witness=witness.close,
        )
        bridge = _P1Bridge(bridge_parent, resources)
        resources._close_bridge = bridge.close
        return resources
    except BaseException:
        if bridge is not None:
            await bridge.close()
        if backend is not None:
            await backend.close()
        else:
            if worker is not None:
                await worker.close()
            if witness is not None:
                witness.close()
            if store is not None:
                store.close()
            if lease is not None:
                lease.close()
        for channel in (bridge_parent, bridge_child, witness_parent, witness_child):
            channel.close()
        temporary.cleanup()
    raise P1OperatorError()


async def _force_close_pi(rpc: PiRpcSession) -> None:
    """Use the retained process owner, never an active RPC command lock."""
    process = rpc.process
    if process is not None and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    loop = asyncio.get_running_loop()
    stopped = loop.create_future()

    def finish(failed: bool) -> None:
        if not stopped.done():
            if failed:
                stopped.set_exception(P1OperatorError())
            else:
                stopped.set_result(None)

    def stop() -> None:
        failed = False
        try:
            rpc.stop()
        except BaseException:
            failed = True
        try:
            loop.call_soon_threadsafe(finish, failed)
        except RuntimeError:
            pass  # The bounded launcher has already closed its loop.

    threading.Thread(target=stop, daemon=True).start()
    await stopped
    if rpc.process is not None or (process is not None and process.poll() is None):
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
                result = P1PublicResult(result.run_id, "protocol-failure")
        finalizer = asyncio.create_task(loop.shutdown_asyncgens())
        if not await wait_task_until(finalizer, shutdown_deadline):
            result = P1PublicResult(result.run_id, "protocol-failure")
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
            if isinstance(resources, P1OperatorResources):
                resources.observe = _public_progress
            return await run_fixed_small_verification(resources)

        result = _run_operator(invoke)
    except BaseException:
        pass
    if result is None:
        print('{"status":"preflight-rejected"}')
        return 2
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
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
