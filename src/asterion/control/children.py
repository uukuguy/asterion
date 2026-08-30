"""Provider-neutral child authority derivation contracts."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import stat
import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias, cast

from asterion.control.authority import (
    AuthorityEnvelope,
    AuthorityError,
    BudgetLimit,
    BudgetRequest,
    BudgetUsage,
    AuthorityLedger,
)
from asterion.control.execution import ActionExecutionFailure, ActionExecutionReceipt
from asterion.control.factory import (
    ControlPlaneFactoryContext,
    ControlPlaneFactoryRegistry,
)
from asterion.control.host import ControlCommand, ControlEvent, ControlPlaneClient
from asterion.control.journal import CanonicalJournal, FileCanonicalJournal, JournalRecord
from asterion.control.manager import ActionExecutor, ControlHost
from asterion.control.private_store import (
    MAX_PRIVATE_TEXT_BYTES,
    PrivateContentResolver,
)
from asterion.control.protocol import OPAQUE_ID
from asterion.control.system import AgentSystemPlan
from asterion.runtime.host import CancellationSignal

if TYPE_CHECKING:
    from asterion.operation.services import OperationDispatcher


_BINDING_NAME = "binding.json"
_PHASE_NAME = "phase.json"
_TERMINAL_NAME = "terminal.json"
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)


class ChildSessionError(AuthorityError):
    """Raised for a known, no-effect child session failure."""


class DeriveControlOptions(Protocol):
    """Derive provider options from the exact child identity and authority."""

    def __call__(
        self,
        base: Mapping[str, str],
        *,
        child_root: Path,
        child_session_id: str,
        child_authority: AuthorityEnvelope,
        generation: int,
    ) -> Mapping[str, str]: ...


class DeriveOperationDispatcher(Protocol):
    """Derive one operator-owned dispatcher after a child journal opens."""

    def __call__(
        self,
        *,
        child_authority: AuthorityEnvelope,
        child_journal: CanonicalJournal,
        child_session_id: str,
        generation: int,
    ) -> OperationDispatcher: ...


class LegacyChildActionExecutorFactory(Protocol):
    """Build a child executor with the original nested lifecycle boundary."""

    def __call__(
        self,
        authority: AuthorityEnvelope,
        children: "ChildSessionService",
    ) -> ActionExecutor: ...


class ClientAwareChildActionExecutorFactory(Protocol):
    """Build a child executor with its exact nested client boundary."""

    def __call__(
        self,
        authority: AuthorityEnvelope,
        children: "ChildSessionService",
        client: ControlPlaneClient,
    ) -> ActionExecutor: ...


ChildActionExecutorFactory: TypeAlias = (
    LegacyChildActionExecutorFactory | ClientAwareChildActionExecutorFactory
)


@dataclass(frozen=True, repr=False)
class ChildSessionBinding:
    """Durable public identity for one child session."""

    child_id: str
    action_id: str
    session_id: str
    authority_id: str
    generation: int
    proposal_digest: str

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None
                for value in (
                    self.child_id,
                    self.action_id,
                    self.session_id,
                    self.authority_id,
                )
            )
            or isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 1
            or not _is_digest(self.proposal_digest)
        ):
            raise ChildSessionError("child binding is invalid")

    def to_mapping(self) -> Mapping[str, object]:
        return {
            "child_id": self.child_id,
            "action_id": self.action_id,
            "session_id": self.session_id,
            "authority_id": self.authority_id,
            "generation": self.generation,
            "proposal_digest": self.proposal_digest,
        }

    @classmethod
    def from_mapping(cls, value: object) -> ChildSessionBinding:
        if not isinstance(value, Mapping) or set(value) != {
            "child_id",
            "action_id",
            "session_id",
            "authority_id",
            "generation",
            "proposal_digest",
        }:
            raise ChildSessionError("child binding is invalid")
        try:
            return cls(
                child_id=value["child_id"],  # type: ignore[arg-type]
                action_id=value["action_id"],  # type: ignore[arg-type]
                session_id=value["session_id"],  # type: ignore[arg-type]
                authority_id=value["authority_id"],  # type: ignore[arg-type]
                generation=value["generation"],  # type: ignore[arg-type]
                proposal_digest=value["proposal_digest"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError):
            raise ChildSessionError("child binding is invalid") from None


@dataclass(frozen=True, repr=False)
class ChildSessionStatus:
    """Public-safe status of one child session."""

    child_id: str
    status: Literal[
        "starting", "running", "completed", "failed", "cancelled", "uncertain"
    ]
    action_id: str | None = None
    receipt_ref: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.child_id, str)
            or OPAQUE_ID.fullmatch(self.child_id) is None
            or self.status
            not in {
                "starting",
                "running",
                "completed",
                "failed",
                "cancelled",
                "uncertain",
            }
            or (
                self.action_id is not None
                and (
                    not isinstance(self.action_id, str)
                    or OPAQUE_ID.fullmatch(self.action_id) is None
                )
            )
            or (
                self.receipt_ref is not None
                and (
                    not isinstance(self.receipt_ref, str)
                    or OPAQUE_ID.fullmatch(self.receipt_ref) is None
                )
            )
            or (self.status == "completed" and self.receipt_ref is None)
            or (self.status != "completed" and self.receipt_ref is not None)
        ):
            raise ChildSessionError("child status is invalid")


@dataclass(frozen=True, repr=False)
class ChildTerminalReceipt:
    """Public-safe terminal receipt persisted by the later lifecycle slice."""

    status: Literal["completed"]
    receipt: ActionExecutionReceipt

    def __post_init__(self) -> None:
        if self.status != "completed" or not isinstance(
            self.receipt, ActionExecutionReceipt
        ):
            raise ChildSessionError("child terminal receipt is invalid")

    def to_mapping(self) -> Mapping[str, object]:
        return {
            "action_id": self.receipt.action_id,
            "receipt_ref": self.receipt.receipt_ref,
            "usage": _usage_mapping(self.receipt),
            "artifact_ids": list(self.receipt.artifact_ids),
            "media_types": list(self.receipt.media_types),
        }

    @classmethod
    def from_mapping(cls, value: object) -> ChildTerminalReceipt:
        if not isinstance(value, Mapping) or set(value) != {
            "action_id",
            "receipt_ref",
            "usage",
            "artifact_ids",
            "media_types",
        }:
            raise ChildSessionError("child terminal receipt is invalid")
        usage = value["usage"]
        artifact_ids = value["artifact_ids"]
        media_types = value["media_types"]
        if (
            not isinstance(usage, Mapping)
            or set(usage)
            != {
                "controller_tokens",
                "application_tokens",
                "child_tokens",
                "aggregate_tokens",
                "cost_micros",
            }
            or type(artifact_ids) is not list
            or type(media_types) is not list
        ):
            raise ChildSessionError("child terminal receipt is invalid")
        try:
            from asterion.control.authority import BudgetUsage

            receipt = ActionExecutionReceipt(
                action_id=value["action_id"],  # type: ignore[arg-type]
                receipt_ref=value["receipt_ref"],  # type: ignore[arg-type]
                usage=BudgetUsage(
                    controller_tokens=usage["controller_tokens"],  # type: ignore[arg-type]
                    application_tokens=usage["application_tokens"],  # type: ignore[arg-type]
                    child_tokens=usage["child_tokens"],  # type: ignore[arg-type]
                    aggregate_tokens=usage["aggregate_tokens"],  # type: ignore[arg-type]
                    cost_micros=usage["cost_micros"],  # type: ignore[arg-type]
                ),
                artifact_ids=tuple(artifact_ids),
                media_types=tuple(media_types),
            )
        except (KeyError, TypeError, ValueError):
            raise ChildSessionError("child terminal receipt is invalid") from None
        return cls(status="completed", receipt=receipt)


@dataclass
class _PinnedChildRoot:
    path: Path
    fd: int
    closed: bool = False

    def close(self) -> None:
        if self.closed:
            return
        try:
            os.close(self.fd)
        except OSError:
            pass
        self.closed = True


@dataclass
class _ActiveChild:
    binding: ChildSessionBinding
    digest: str
    child_root: _PinnedChildRoot
    task: asyncio.Task[ActionExecutionReceipt]
    runtime: _ChildRuntime | None = None


@dataclass
class _ChildRuntime:
    """The live provider resources retained until close is proved."""

    client: ControlPlaneClient
    host: ControlHost | None = None
    closed: bool = False
    cancel_requested: bool = False
    cancel_task: asyncio.Task[None] | None = None
    cancellation_uncertain: bool = False


class ChildSessionService:
    """Provider-neutral, durably fenced child control-session lifecycle."""

    def __init__(
        self,
        *,
        plan: AgentSystemPlan,
        authority: AuthorityEnvelope,
        control_factories: ControlPlaneFactoryRegistry,
        private_root: Path,
        content: PrivateContentResolver,
        child_action_executor_factory: ChildActionExecutorFactory,
        clock_ms: Callable[[], int],
        control_options: Mapping[str, str] = {},
        derive_control_options: DeriveControlOptions | None = None,
        derive_operation_dispatcher: DeriveOperationDispatcher | None = None,
        host_services: Mapping[str, object] = {},
        _private_root_fd: int | None = None,
    ) -> None:
        if (
            not isinstance(plan, AgentSystemPlan)
            or not isinstance(authority, AuthorityEnvelope)
            or not isinstance(control_factories, ControlPlaneFactoryRegistry)
            or not isinstance(private_root, Path)
            or not callable(getattr(content, "resolve_text", None))
            or not callable(child_action_executor_factory)
            or not callable(clock_ms)
            or (
                derive_control_options is not None
                and not callable(derive_control_options)
            )
            or (
                derive_operation_dispatcher is not None
                and not callable(derive_operation_dispatcher)
            )
            or (
                _private_root_fd is not None
                and (
                    isinstance(_private_root_fd, bool)
                    or not isinstance(_private_root_fd, int)
                )
            )
        ):
            raise ChildSessionError("child service construction is invalid")
        self._plan = plan
        self._authority = authority
        self._factories = control_factories
        self._private_root = private_root
        self._content = content
        self._executor_factory = child_action_executor_factory
        self._clock_ms = clock_ms
        try:
            options = dict(control_options)
            services = dict(host_services)
            if any(
                type(key) is not str or type(value) is not str
                for key, value in options.items()
            ):
                raise TypeError
        except Exception:
            raise ChildSessionError("child service construction is invalid") from None
        self._control_options = MappingProxyType(options)
        self._derive_options = derive_control_options
        self._derive_operation_dispatcher = derive_operation_dispatcher
        self._host_services = MappingProxyType(services)
        self._private_root_fd = -1
        self._children_root_fd = -1
        self._child_roots: dict[str, _PinnedChildRoot] = {}
        self._require_path_binding = _private_root_fd is None
        try:
            self._private_root_fd = (
                _open_trusted_private_root(private_root)
                if _private_root_fd is None
                else _open_trusted_private_root_fd(_private_root_fd)
            )
            self._children_root_fd = _open_or_create_private_directory_at(
                self._private_root_fd,
                "children",
                private_root / "children",
                require_path_binding=self._require_path_binding,
            )
        except ChildSessionError:
            self._close_root_descriptors()
            raise
        self._entries: dict[str, _ActiveChild] = {}
        self._statuses: dict[str, ChildSessionStatus] = {}
        self._lock = asyncio.Lock()
        self._closing = False
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    @property
    def active_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

    def status(self, child_id: str) -> ChildSessionStatus:
        if not isinstance(child_id, str) or OPAQUE_ID.fullmatch(child_id) is None:
            raise ChildSessionError("child identity is invalid")
        try:
            return self._statuses[child_id]
        except KeyError:
            raise ChildSessionError("child session is unknown") from None

    def _prepare_pinned_child_root(self, child_id: str) -> _PinnedChildRoot:
        if OPAQUE_ID.fullmatch(child_id) is None or len(Path(child_id).parts) != 1:
            raise ChildSessionError("child root is invalid")
        existing = self._child_roots.get(child_id)
        if existing is not None and not existing.closed:
            return existing
        descriptor = _open_or_create_private_directory_at(
            self._children_root_fd,
            child_id,
            self._private_root / "children" / child_id,
            require_path_binding=self._require_path_binding,
        )
        root = _PinnedChildRoot(self._private_root / "children" / child_id, descriptor)
        self._child_roots[child_id] = root
        return root

    def _release_child_root(self, child_id: str) -> None:
        root = self._child_roots.pop(child_id, None)
        if root is not None:
            root.close()

    def _close_root_descriptors(self) -> None:
        for child_id in tuple(self._child_roots):
            self._release_child_root(child_id)
        for descriptor in (self._children_root_fd, self._private_root_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
        self._children_root_fd = -1
        self._private_root_fd = -1

    @staticmethod
    def _binding_for(
        proposal: ControlEvent, child_id: str, digest: str
    ) -> ChildSessionBinding:
        action_id = proposal.payload.get("action_id")
        if not isinstance(action_id, str) or OPAQUE_ID.fullmatch(action_id) is None:
            raise ChildSessionError("child proposal is invalid")
        return ChildSessionBinding(
            child_id=child_id,
            action_id=action_id,
            session_id=f"child-session-{child_id}",
            authority_id=f"child:{child_id}",
            generation=1,
            proposal_digest=digest,
        )

    async def spawn(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        child_id = _child_id(proposal, "child.spawn")
        digest = self.proposal_digest(proposal)
        if _cancelled(signal):
            self._statuses[child_id] = ChildSessionStatus(
                child_id, "cancelled", str(proposal.payload["action_id"])
            )
            raise ActionExecutionFailure("cancelled", "child-start-cancelled", None)
        async with self._lock:
            if self._closing or self._closed:
                raise ChildSessionError("child service is closed")
            entry = self._entries.get(child_id)
            if entry is not None:
                if entry.digest != digest:
                    raise ChildSessionError("child binding conflicts")
                task = entry.task
            else:
                root = self._prepare_pinned_child_root(child_id)
                binding = self.load_binding(root)
                expected = self._binding_for(proposal, child_id, digest)
                if binding is not None and binding != expected:
                    raise ChildSessionError("child binding conflicts")
                terminal = self.load_terminal(root)
                if terminal is not None:
                    if binding != expected:
                        raise ChildSessionError("child binding conflicts")
                    self._statuses[child_id] = ChildSessionStatus(
                        child_id,
                        "completed",
                        terminal.receipt.action_id,
                        terminal.receipt.receipt_ref,
                    )
                    self._release_child_root(child_id)
                    return terminal.receipt
                if self.load_phase(root) == "provider-create-started":
                    self._statuses[child_id] = ChildSessionStatus(
                        child_id, "uncertain", expected.action_id
                    )
                    raise _uncertain()
                if len(self._entries) >= self._authority.max_concurrent_children:
                    raise ChildSessionError("child concurrency is unavailable")
                # Validation is deliberately before the durable provider fence.
                _validate_goal(self._content, proposal)
                child_authority = derive_child_authority(
                    self._authority, proposal, child_id, now_ms=self._clock_ms()
                )
                self.persist_binding(
                    child_root=root,
                    child_id=expected.child_id,
                    action_id=expected.action_id,
                    session_id=expected.session_id,
                    authority_id=expected.authority_id,
                    generation=expected.generation,
                    proposal_digest=expected.proposal_digest,
                )
                task = asyncio.create_task(
                    self._run_spawn(root, expected, child_authority, proposal, signal)
                )
                task.add_done_callback(_consume_child_task_exception)
                entry = _ActiveChild(expected, digest, root, task)
                self._entries[child_id] = entry
                self._statuses[child_id] = ChildSessionStatus(
                    child_id, "starting", expected.action_id
                )
        return await _await_without_cancelling(task)

    async def _run_spawn(
        self,
        root: _PinnedChildRoot,
        binding: ChildSessionBinding,
        authority: AuthorityEnvelope,
        proposal: ControlEvent,
        signal: CancellationSignal,
    ) -> ActionExecutionReceipt:
        """Run one fenced child to a terminal state and close its provider."""

        runtime: _ChildRuntime | None = None
        nested_children: ChildSessionService | None = None
        journal: FileCanonicalJournal | None = None
        fenced = False
        try:
            options: Mapping[str, str] = self._control_options
            if self._derive_options is not None:
                options = self._derive_options(
                    self._control_options,
                    child_root=root.path,
                    child_session_id=binding.session_id,
                    child_authority=authority,
                    generation=binding.generation,
                )
            factory_binding = self._factories.select(
                self._plan.control_binding.control_plane_id,
                self._plan.control_binding.version,
            )
            operation_manager: OperationDispatcher | None = None
            child_host_services: Mapping[str, object] = self._host_services
            if "operations-v1" in factory_binding.capabilities:
                journal = FileCanonicalJournal.open_at(
                    root.fd, root.path, binding.session_id
                )
                if journal.position == 0:
                    system = journal.append(
                        0,
                        JournalRecord.system_bound(
                            system_id=self._plan.system_id,
                            system_version=self._plan.version,
                        ),
                    )
                    journal.append(
                        system.position,
                        JournalRecord.authority_bound(
                            authority_id=authority.authority_id,
                            authority_revision=authority.revision,
                        ),
                    )
                operation_manager = self._derive_child_operation_dispatcher(
                    authority=authority,
                    journal=journal,
                    session_id=binding.session_id,
                    generation=binding.generation,
                )
                child_host_services_map = dict(self._host_services)
                child_host_services_map["operation-dispatcher"] = operation_manager
                child_host_services = MappingProxyType(child_host_services_map)
            context = ControlPlaneFactoryContext(
                system_id=self._plan.system_id,
                system_version=self._plan.version,
                control_plane_id=self._plan.control_binding.control_plane_id,
                control_plane_version=self._plan.control_binding.version,
                private_root=root.path,
                options=options,
                authority=authority,
                host_services=child_host_services,
            )
            factory = factory_binding.factory
            client_executor = _factory_accepts_client(self._executor_factory)
            nested_children: ChildSessionService | None = None
            executor: ActionExecutor | None = None
            if not client_executor:
                nested_children = ChildSessionService(
                    plan=self._plan,
                    authority=authority,
                    control_factories=self._factories,
                    private_root=root.path,
                    content=self._content,
                    child_action_executor_factory=self._executor_factory,
                    clock_ms=self._clock_ms,
                    control_options=self._control_options,
                    derive_control_options=self._derive_options,
                    derive_operation_dispatcher=self._derive_operation_dispatcher,
                    host_services=child_host_services,
                    _private_root_fd=root.fd,
                )
                legacy_factory = cast(
                    LegacyChildActionExecutorFactory, self._executor_factory
                )
                executor = legacy_factory(authority, nested_children)
            if journal is None:
                journal = FileCanonicalJournal.open_at(
                    root.fd, root.path, binding.session_id
                )
            self.persist_phase(child_root=root, phase="provider-create-started")
            fenced = True
            client = factory(context)
            _seed_child_client_goal(client, self._content, proposal)
            if nested_children is None:
                nested_content = (
                    client
                    if callable(getattr(client, "resolve_text", None))
                    else self._content
                )
                nested_services = (
                    {**self._host_services, "private-content": client}
                    if callable(getattr(client, "resolve_text", None))
                    else self._host_services
                )
                nested_children = ChildSessionService(
                    plan=self._plan,
                    authority=authority,
                    control_factories=self._factories,
                    private_root=root.path,
                    content=nested_content,  # type: ignore[arg-type]
                    child_action_executor_factory=self._executor_factory,
                    clock_ms=self._clock_ms,
                    control_options=self._control_options,
                    derive_control_options=self._derive_options,
                    derive_operation_dispatcher=self._derive_operation_dispatcher,
                    host_services={
                        **nested_services,
                        **(
                            {"operation-dispatcher": operation_manager}
                            if operation_manager is not None
                            else {}
                        ),
                    },
                    _private_root_fd=root.fd,
                )
            if executor is None:
                executor = _build_child_executor(
                    self._executor_factory,
                    authority,
                    nested_children,
                    client,
                )
            runtime = _ChildRuntime(client=client)
            await self._attach_runtime(binding.child_id, runtime)
            host = ControlHost(
                session_id=binding.session_id,
                generation=binding.generation,
                plan=self._plan,
                authority=AuthorityLedger(authority),
                journal=journal,
                client=client,
                action_executor=executor,
                clock_ms=self._clock_ms,
                cancellation_signal=signal,
                child_service=nested_children,
                operation_manager=operation_manager,
            )
            journal = None
            runtime.host = host
            await self._mark_running(binding)
            await host.dispatch(
                ControlCommand(
                    command_id=f"child-create-{binding.child_id}",
                    session_id=binding.session_id,
                    authority_revision=authority.revision,
                    type="session.create",
                    payload={
                        "system_id": self._plan.system_id,
                        "system_version": self._plan.version,
                        "goal_id": f"child-goal-{binding.child_id}",
                        "goal_ref": proposal.payload["input_ref"],
                    },
                )
            )
            await host.pump(until_terminal=True)
            terminal = _terminal_failure(host)
            await _close_runtime(runtime)
            if terminal is not None:
                if terminal.status == "uncertain":
                    async with self._lock:
                        self._statuses[binding.child_id] = ChildSessionStatus(
                            binding.child_id, "uncertain", binding.action_id
                        )
                    raise terminal
                known_status: Literal["failed", "cancelled"] = (
                    "cancelled" if terminal.status == "cancelled" else "failed"
                )
                await self._finish_known(binding, known_status)
                raise terminal
            child_usage = host.snapshot().authority_usage
            if not isinstance(child_usage, BudgetUsage):
                raise RuntimeError("child authority usage is unavailable")
            receipt = ActionExecutionReceipt(
                action_id=binding.action_id,
                receipt_ref=f"child-receipt-{binding.child_id}",
                usage=BudgetUsage(
                    controller_tokens=0,
                    application_tokens=0,
                    child_tokens=child_usage.aggregate_tokens,
                    aggregate_tokens=child_usage.aggregate_tokens,
                    cost_micros=child_usage.cost_micros,
                ),
            )
            self.persist_terminal(
                child_root=root, terminal=ChildTerminalReceipt("completed", receipt)
            )
            await self._finish_known(binding, "completed", receipt.receipt_ref)
            return receipt
        except asyncio.CancelledError:
            close_failed = False
            if journal is not None:
                journal.close()
            if runtime is not None and runtime.cancellation_uncertain:
                async with self._lock:
                    entry = self._entries.get(binding.child_id)
                    if entry is not None and entry.runtime is None:
                        entry.runtime = runtime
                    if entry is not None:
                        self._statuses[binding.child_id] = ChildSessionStatus(
                            binding.child_id, "uncertain", binding.action_id
                        )
                raise _uncertain() from None
            if runtime is not None:
                try:
                    await _close_runtime(runtime)
                except Exception:
                    close_failed = True
                if runtime.host is None and nested_children is not None:
                    try:
                        await nested_children.close()
                    except Exception:
                        close_failed = True
            elif nested_children is not None:
                try:
                    await nested_children.close()
                except Exception:
                    close_failed = True
            async with self._lock:
                entry = self._entries.get(binding.child_id)
                if entry is not None and entry.runtime is None and runtime is not None:
                    entry.runtime = runtime
                self._statuses[binding.child_id] = ChildSessionStatus(
                    binding.child_id, "cancelled", binding.action_id
                )
            if not self._closing:
                raise
            if not close_failed:
                await self._finish_known(binding, "cancelled")
            raise ActionExecutionFailure(
                "cancelled", "child-close-cancelled", None
            ) from None
        except ActionExecutionFailure:
            if journal is not None:
                journal.close()
            raise
        except Exception:
            if not fenced and runtime is None:
                if journal is not None:
                    journal.close()
                if nested_children is not None:
                    try:
                        await nested_children.close()
                    except Exception:
                        pass
                await self._finish_known(binding, "failed")
                raise ChildSessionError("child construction is unavailable") from None
            if journal is not None:
                journal.close()
            if runtime is not None:
                try:
                    await _close_runtime(runtime)
                except Exception:
                    pass
                if runtime.host is None and nested_children is not None:
                    try:
                        await nested_children.close()
                    except Exception:
                        pass
            elif nested_children is not None:
                try:
                    await nested_children.close()
                except Exception:
                    pass
            async with self._lock:
                entry = self._entries.get(binding.child_id)
                if entry is not None:
                    self._statuses[binding.child_id] = ChildSessionStatus(
                        binding.child_id, "uncertain", binding.action_id
                    )
            raise _uncertain() from None

    def _derive_child_operation_dispatcher(
        self,
        *,
        authority: AuthorityEnvelope,
        journal: CanonicalJournal,
        session_id: str,
        generation: int,
    ) -> OperationDispatcher:
        deriver = self._derive_operation_dispatcher
        if deriver is None:
            raise ChildSessionError("child operation dispatcher is unavailable")
        try:
            dispatcher = deriver(
                child_authority=authority,
                child_journal=journal,
                child_session_id=session_id,
                generation=generation,
            )
            dispatcher_session_id = object.__getattribute__(
                dispatcher, "session_id"
            )
            dispatcher_generation = object.__getattribute__(
                dispatcher, "generation"
            )
            dispatcher_authority_id = object.__getattribute__(
                dispatcher, "authority_id"
            )
            dispatcher_authority_revision = object.__getattribute__(
                dispatcher, "authority_revision"
            )
            execute = object.__getattribute__(dispatcher, "execute")
            cancel = object.__getattribute__(dispatcher, "cancel")
            reconcile = object.__getattribute__(dispatcher, "reconcile")
            if (
                dispatcher_session_id != session_id
                or type(dispatcher_generation) is not int
                or dispatcher_generation != generation
                or dispatcher_authority_id != authority.authority_id
                or type(dispatcher_authority_revision) is not int
                or dispatcher_authority_revision != authority.revision
                or not all(callable(value) for value in (execute, cancel, reconcile))
            ):
                raise ValueError
            return cast("OperationDispatcher", dispatcher)
        except ChildSessionError:
            raise
        except Exception:
            raise ChildSessionError(
                "child operation dispatcher is unavailable"
            ) from None

    async def _attach_runtime(self, child_id: str, runtime: _ChildRuntime) -> None:
        """Retain a created provider before any later fallible construction."""

        async with self._lock:
            entry = self._entries.get(child_id)
            if entry is None or self._closing or self._closed:
                raise RuntimeError("child registry is unavailable")
            entry.runtime = runtime

    async def _mark_running(self, binding: ChildSessionBinding) -> None:
        async with self._lock:
            if binding.child_id not in self._entries:
                raise RuntimeError("child registry is unavailable")
            self._statuses[binding.child_id] = ChildSessionStatus(
                binding.child_id, "running", binding.action_id
            )

    async def _finish_known(
        self,
        binding: ChildSessionBinding,
        status: Literal["completed", "failed", "cancelled"],
        receipt_ref: str | None = None,
    ) -> None:
        """Remove a child only after its provider close completed successfully."""

        async with self._lock:
            self._entries.pop(binding.child_id, None)
            self._release_child_root(binding.child_id)
            self._statuses[binding.child_id] = ChildSessionStatus(
                binding.child_id, status, binding.action_id, receipt_ref
            )

    async def message(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        """Steer one active child through its exact bound provider session."""

        del signal
        binding, runtime = await self._active_runtime(proposal, "child.message")
        input_ref = proposal.payload.get("input_ref")
        action_id = proposal.payload.get("action_id")
        if not isinstance(input_ref, str) or OPAQUE_ID.fullmatch(input_ref) is None:
            raise ChildSessionError("child message is invalid")
        assert isinstance(action_id, str)
        try:
            await runtime.client.send(
                ControlCommand(
                    command_id=f"child-message-{action_id}",
                    session_id=binding.session_id,
                    authority_revision=binding.generation,
                    type="input.submit",
                    payload={
                        "input_id": action_id,
                        "delivery": "steer",
                        "content_ref": input_ref,
                    },
                )
            )
        except Exception:
            await self._mark_uncertain(binding.child_id, binding.action_id)
            raise _uncertain() from None
        return _zero_receipt(action_id, f"child-message-{binding.child_id}-{action_id}")

    async def cancel(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        """Request cancellation of one exact active child session."""

        del signal
        binding, runtime = await self._active_runtime(proposal, "child.cancel")
        action_id = proposal.payload.get("action_id")
        assert isinstance(action_id, str)
        await self._send_cancel(
            binding, runtime, command_id=f"child-cancel-{action_id}"
        )
        return _zero_receipt(action_id, f"child-cancel-{binding.child_id}-{action_id}")

    async def cancel_all(self) -> None:
        """Request cancellation of every currently retained child without holding locks."""

        async with self._lock:
            active = tuple(
                (entry.binding, entry.runtime)
                for _, entry in sorted(self._entries.items())
                if entry.runtime is not None
                and not entry.runtime.closed
                and not entry.runtime.cancel_requested
            )
        results = await asyncio.gather(
            *(
                self._send_cancel(
                    binding, runtime, command_id=f"child-cancel-all-{binding.child_id}"
                )
                for binding, runtime in active
                if runtime is not None
            ),
            return_exceptions=True,
        )
        if any(isinstance(result, BaseException) for result in results):
            raise _uncertain()

    async def close(self) -> None:
        """Await the one service-owned shutdown task without cancelling it."""
        async with self._lock:
            if self._closed:
                return
            if self._close_task is None:
                self._closing = True
                self._close_task = asyncio.create_task(self._close_impl())
            task = self._close_task
        await asyncio.shield(task)

    async def _close_impl(self) -> None:
        """Cancel, drain, close, and release while the service remains closing."""
        cancellation_failed = False
        try:
            await self.cancel_all()
        except Exception:
            cancellation_failed = True
        async with self._lock:
            entries = tuple(self._entries.values())
            tasks = tuple(
                entry.task
                for entry in entries
                if entry.runtime is None
                or (
                    entry.runtime.cancel_requested
                    and not entry.runtime.cancellation_uncertain
                    and (
                        entry.runtime.cancel_task is None
                        or entry.runtime.cancel_task.done()
                    )
                )
            )
            unconfirmed_cancellations = any(
                entry.runtime is not None
                and (
                    entry.runtime.cancellation_uncertain
                    or not entry.runtime.cancel_requested
                    or (
                        entry.runtime.cancel_task is not None
                        and not entry.runtime.cancel_task.done()
                    )
                )
                for entry in entries
            )
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            active = tuple(
                (entry.binding, entry.runtime)
                for _, entry in sorted(self._entries.items())
                if entry.runtime is not None
            )
        failures = cancellation_failed or unconfirmed_cancellations
        for binding, runtime in active:
            assert runtime is not None
            if (
                runtime.cancellation_uncertain
                or not runtime.cancel_requested
                or (runtime.cancel_task is not None and not runtime.cancel_task.done())
            ):
                failures = True
                continue
            try:
                await _close_runtime(runtime)
            except Exception:
                failures = True
                continue
            # A running or uncertain child remains retained for its task/retry path.
            async with self._lock:
                entry = self._entries.get(binding.child_id)
                if entry is not None and entry.runtime is runtime and entry.task.done():
                    status = self._statuses.get(binding.child_id)
                    if status is not None and status.status in {
                        "completed",
                        "failed",
                        "cancelled",
                    }:
                        self._entries.pop(binding.child_id, None)
        if failures:
            self._closed = False
            async with self._lock:
                self._close_task = None
            raise ChildSessionError("child provider close is unavailable")
        self._closed = True
        self._close_root_descriptors()
        async with self._lock:
            if not self._closed:
                self._close_task = None
            self._closing = False

    async def _active_runtime(
        self, proposal: ControlEvent, kind: str
    ) -> tuple[ChildSessionBinding, _ChildRuntime]:
        child_id = _child_id(proposal, kind)
        action_id = proposal.payload.get("action_id")
        if not isinstance(action_id, str) or OPAQUE_ID.fullmatch(action_id) is None:
            raise ChildSessionError("child action identity is invalid")
        async with self._lock:
            entry = self._entries.get(child_id)
            if entry is None or entry.runtime is None or entry.runtime.closed:
                raise ChildSessionError("child session is not active")
            return entry.binding, entry.runtime

    async def _mark_uncertain(self, child_id: str, action_id: str) -> None:
        async with self._lock:
            if child_id in self._entries:
                self._statuses[child_id] = ChildSessionStatus(
                    child_id, "uncertain", action_id
                )

    async def _send_cancel(
        self, binding: ChildSessionBinding, runtime: _ChildRuntime, *, command_id: str
    ) -> None:
        if runtime.cancel_task is None:
            runtime.cancel_task = asyncio.create_task(
                self._deliver_cancel(binding, runtime, command_id=command_id)
            )
            runtime.cancel_task.add_done_callback(_consume_cancel_task_exception)
        await _await_cancel_task(runtime.cancel_task)

    async def _deliver_cancel(
        self, binding: ChildSessionBinding, runtime: _ChildRuntime, *, command_id: str
    ) -> None:
        try:
            await runtime.client.send(
                ControlCommand(
                    command_id=command_id,
                    session_id=binding.session_id,
                    authority_revision=binding.generation,
                    type="session.cancel",
                    payload={"reason_code": "child-cancel-requested"},
                )
            )
        except Exception:
            runtime.cancellation_uncertain = True
            await self._mark_uncertain(binding.child_id, binding.action_id)
            raise _uncertain() from None
        runtime.cancel_requested = True

    @staticmethod
    def proposal_digest(proposal: ControlEvent) -> str:
        if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
            raise ChildSessionError("child proposal is invalid")
        encoded = json.dumps(
            proposal.to_mapping(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def prepare_child_root(private_root: Path, child_id: str) -> Path:
        if (
            not isinstance(private_root, Path)
            or not isinstance(child_id, str)
            or OPAQUE_ID.fullmatch(child_id) is None
            or len(Path(child_id).parts) != 1
        ):
            raise ChildSessionError("child root is invalid")
        children_root = private_root / "children"
        _ensure_private_directory(children_root)
        child_root = children_root / child_id
        _ensure_private_directory(child_root)
        return child_root

    @staticmethod
    def persist_binding(
        *,
        child_root: Path | _PinnedChildRoot,
        child_id: str,
        action_id: str,
        session_id: str,
        authority_id: str,
        generation: int,
        proposal_digest: str,
    ) -> str:
        binding = ChildSessionBinding(
            child_id=child_id,
            action_id=action_id,
            session_id=session_id,
            authority_id=authority_id,
            generation=generation,
            proposal_digest=proposal_digest,
        )
        existing = _load_json(child_root, _BINDING_NAME)
        if (
            existing is not None
            and ChildSessionBinding.from_mapping(existing) != binding
        ):
            raise ChildSessionError("child binding conflicts")
        if existing is None:
            if not _write_json(child_root, _BINDING_NAME, binding.to_mapping()):
                concurrent = _load_json(child_root, _BINDING_NAME)
                if (
                    concurrent is None
                    or ChildSessionBinding.from_mapping(concurrent) != binding
                ):
                    raise ChildSessionError("child binding conflicts")
        return binding.proposal_digest

    @staticmethod
    def load_binding(child_root: Path | _PinnedChildRoot) -> ChildSessionBinding | None:
        value = _load_json(child_root, _BINDING_NAME)
        return None if value is None else ChildSessionBinding.from_mapping(value)

    @staticmethod
    def persist_phase(*, child_root: Path | _PinnedChildRoot, phase: str) -> None:
        if phase != "provider-create-started":
            raise ChildSessionError("child phase is invalid")
        existing = _load_json(child_root, _PHASE_NAME)
        if existing is not None and existing != {"phase": phase}:
            raise ChildSessionError("child phase conflicts")
        if existing is None:
            if not _write_json(child_root, _PHASE_NAME, {"phase": phase}):
                if _load_json(child_root, _PHASE_NAME) != {"phase": phase}:
                    raise ChildSessionError("child phase conflicts")

    @staticmethod
    def load_phase(child_root: Path | _PinnedChildRoot) -> str | None:
        value = _load_json(child_root, _PHASE_NAME)
        if value is None:
            return None
        if not isinstance(value, Mapping) or dict(value) != {
            "phase": "provider-create-started"
        }:
            raise ChildSessionError("child phase is invalid")
        return "provider-create-started"

    @staticmethod
    def persist_terminal(
        *, child_root: Path | _PinnedChildRoot, terminal: ChildTerminalReceipt
    ) -> None:
        if not isinstance(terminal, ChildTerminalReceipt):
            raise ChildSessionError("child terminal receipt is invalid")
        record = {
            "status": "completed",
            "close_complete": True,
            "receipt": dict(terminal.to_mapping()),
        }
        existing = _load_json(child_root, _TERMINAL_NAME)
        if existing is not None and existing != record:
            raise ChildSessionError("child terminal conflicts")
        if existing is None:
            if not _write_json(child_root, _TERMINAL_NAME, record):
                if _load_json(child_root, _TERMINAL_NAME) != record:
                    raise ChildSessionError("child terminal conflicts")

    @staticmethod
    def load_terminal(
        child_root: Path | _PinnedChildRoot,
    ) -> ChildTerminalReceipt | None:
        value = _load_json(child_root, _TERMINAL_NAME)
        if value is None:
            return None
        if (
            not isinstance(value, Mapping)
            or set(value) != {"status", "close_complete", "receipt"}
            or value.get("status") != "completed"
            or value.get("close_complete") is not True
        ):
            raise ChildSessionError("child terminal receipt is invalid")
        return ChildTerminalReceipt.from_mapping(value["receipt"])


def derive_child_authority(
    parent: AuthorityEnvelope,
    proposal: ControlEvent,
    child_id: str,
    *,
    now_ms: int,
) -> AuthorityEnvelope:
    """Derive the closed, strictly narrower authority envelope for one child."""

    if not isinstance(parent, AuthorityEnvelope):
        raise AuthorityError("parent authority is invalid")
    if parent.cancelled:
        raise AuthorityError("parent authority is cancelled")
    _require_nonnegative_integer(now_ms, "child authority evaluation time")
    if now_ms >= parent.expires_at_ms:
        raise AuthorityError("parent authority is expired")
    if parent.max_recursion_depth < 1:
        raise AuthorityError("child recursion depth is unavailable")
    if not isinstance(child_id, str) or OPAQUE_ID.fullmatch(child_id) is None:
        raise AuthorityError("child identity is invalid")
    if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
        raise AuthorityError("child proposal is invalid")

    payload = proposal.payload
    if payload.get("kind") != "child.spawn":
        raise AuthorityError("child proposal kind is invalid")
    if payload.get("authority_revision") != parent.revision:
        raise AuthorityError("child proposal authority revision is invalid")
    if not _is_exact_child_target(payload.get("target"), child_id):
        raise AuthorityError("child proposal target is invalid")
    request = _closed_budget_request(payload.get("budget"))
    if (
        request.deadline_ms > parent.max_action_deadline_ms
        or now_ms + request.deadline_ms > parent.expires_at_ms
    ):
        raise AuthorityError("child proposal deadline is invalid")

    child_limit = BudgetLimit(
        controller_tokens=request.child_tokens,
        application_tokens=request.application_tokens,
        child_tokens=request.child_tokens,
        aggregate_tokens=request.aggregate_tokens,
        cost_micros=request.cost_micros,
    )
    if not _budget_fits(request, parent.budget_limit) or not _budget_fits(
        child_limit, parent.budget_limit
    ):
        raise AuthorityError("child proposal budget is unavailable")
    return AuthorityEnvelope(
        authority_id=f"child:{child_id}",
        revision=1,
        allowed_portfolio=parent.allowed_portfolio,
        allowed_operations=parent.allowed_operations,
        budget_limit=child_limit,
        expires_at_ms=min(parent.expires_at_ms, now_ms + request.deadline_ms),
        max_action_deadline_ms=min(parent.max_action_deadline_ms, request.deadline_ms),
        max_recursion_depth=parent.max_recursion_depth - 1,
        max_concurrent_children=parent.max_concurrent_children,
        execution_domain=parent.execution_domain,
        host_service_grants=parent.host_service_grants,
    )


def _is_exact_child_target(value: object, child_id: str) -> bool:
    return isinstance(value, Mapping) and dict(value) == {
        "kind": "child",
        "child_id": child_id,
    }


def _cancelled(signal: CancellationSignal) -> bool:
    try:
        return bool(signal.cancelled)
    except Exception:
        raise ChildSessionError("child cancellation state is unavailable") from None


def _consume_child_task_exception(
    task: asyncio.Future[ActionExecutionReceipt],
) -> None:
    try:
        task.exception()
    except asyncio.CancelledError:
        pass


def _consume_cancel_task_exception(task: asyncio.Future[None]) -> None:
    try:
        task.exception()
    except asyncio.CancelledError:
        pass


async def _await_without_cancelling(
    task: asyncio.Task[ActionExecutionReceipt],
) -> ActionExecutionReceipt:
    """Await a shared child task without letting waiter cancellation cancel it."""

    if not task.done():
        await asyncio.wait((task,), return_when=asyncio.FIRST_COMPLETED)
    return task.result()


async def _await_cancel_task(task: asyncio.Task[None]) -> None:
    """Await shared cancellation delivery without cancelling the send."""

    if not task.done():
        await asyncio.wait((task,), return_when=asyncio.FIRST_COMPLETED)
    task.result()


def _child_id(proposal: ControlEvent, kind: str) -> str:
    if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
        raise ChildSessionError("child proposal is invalid")
    payload = proposal.payload
    target = payload.get("target")
    child_id = target.get("child_id") if isinstance(target, Mapping) else None
    if not isinstance(child_id, str) or OPAQUE_ID.fullmatch(child_id) is None:
        raise ChildSessionError("child identity is invalid")
    if payload.get("kind") != kind or not _is_exact_child_target(target, child_id):
        raise ChildSessionError("child proposal is invalid")
    return child_id


def _seed_child_client_goal(
    client: ControlPlaneClient,
    content: PrivateContentResolver,
    proposal: ControlEvent,
) -> None:
    cacher = getattr(client, "cache_private_input", None)
    if not callable(cacher):
        return
    reference = proposal.payload.get("input_ref")
    if not isinstance(reference, str):
        raise ChildSessionError("child private input is invalid")
    try:
        body = content.resolve_text(reference, max_bytes=MAX_PRIVATE_TEXT_BYTES)
        cacher(reference, body)
    except Exception:
        raise ChildSessionError("child private input is unavailable") from None


def _build_child_executor(
    factory: ChildActionExecutorFactory,
    authority: AuthorityEnvelope,
    children: ChildSessionService,
    client: ControlPlaneClient,
) -> ActionExecutor:
    if _factory_accepts_client(factory):
        client_factory = cast(ClientAwareChildActionExecutorFactory, factory)
        return client_factory(authority, children, client)
    legacy_factory = cast(LegacyChildActionExecutorFactory, factory)
    return legacy_factory(authority, children)


def _factory_accepts_client(factory: ChildActionExecutorFactory) -> bool:
    try:
        parameters = inspect.signature(factory).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = 0
    for parameter in parameters:
        if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
            return True
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional += 1
    return positional >= 3


def _validate_goal(content: PrivateContentResolver, proposal: ControlEvent) -> None:
    reference = proposal.payload.get("input_ref")
    if not isinstance(reference, str) or OPAQUE_ID.fullmatch(reference) is None:
        raise ChildSessionError("child private input is invalid")
    try:
        body = content.resolve_text(reference, max_bytes=MAX_PRIVATE_TEXT_BYTES)
    except Exception:
        raise ChildSessionError("child private input is unavailable") from None
    if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_PRIVATE_TEXT_BYTES:
        raise ChildSessionError("child private input is invalid")


def _terminal_failure(host: ControlHost) -> ActionExecutionFailure | None:
    status = host.snapshot().state.session_status
    if status == "completed":
        return None
    if status == "failed":
        return ActionExecutionFailure(
            "failed", "child-terminal-failed", "child-terminal"
        )
    if status == "cancelled":
        return ActionExecutionFailure("cancelled", "child-terminal-cancelled", None)
    if status == "budget_limited":
        return ActionExecutionFailure(
            "failed", "child-terminal-budget-limited", "child-terminal"
        )
    return _uncertain()


async def _close_runtime(runtime: _ChildRuntime) -> None:
    """Close the one provider resource set, including partial construction."""

    if runtime.closed:
        return
    if runtime.host is not None:
        await runtime.host.close()
    else:
        await runtime.client.close()
    runtime.closed = True


def _zero_receipt(action_id: str, receipt_ref: str) -> ActionExecutionReceipt:
    return ActionExecutionReceipt(
        action_id=action_id,
        receipt_ref=receipt_ref,
        usage=BudgetUsage.zero(),
    )


def _uncertain() -> ActionExecutionFailure:
    return ActionExecutionFailure("uncertain", "child-progress-unknown", None)


def _closed_budget_request(value: object) -> BudgetRequest:
    fields = {
        "controller_tokens",
        "application_tokens",
        "child_tokens",
        "aggregate_tokens",
        "cost_micros",
        "deadline_ms",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise AuthorityError("child proposal budget is invalid")
    return BudgetRequest.from_mapping(value)


def _budget_fits(limit: BudgetLimit | BudgetRequest, parent: BudgetLimit) -> bool:
    return all(
        getattr(limit, field) <= getattr(parent, field)
        for field in (
            "controller_tokens",
            "application_tokens",
            "child_tokens",
            "aggregate_tokens",
            "cost_micros",
        )
    )


def _require_nonnegative_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AuthorityError(f"{label} is invalid")


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _usage_mapping(receipt: ActionExecutionReceipt) -> Mapping[str, int]:
    usage = receipt.usage
    return {
        "controller_tokens": usage.controller_tokens,
        "application_tokens": usage.application_tokens,
        "child_tokens": usage.child_tokens,
        "aggregate_tokens": usage.aggregate_tokens,
        "cost_micros": usage.cost_micros,
    }


def _identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _open_trusted_private_root(path: Path) -> int:
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC)
    except OSError:
        raise ChildSessionError("child root is unavailable") from None
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(details.st_mode)
            or _identity(before) != _identity(details)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise ChildSessionError("child root is unsafe")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_trusted_private_root_fd(source_fd: int) -> int:
    try:
        descriptor = os.dup(source_fd)
    except OSError:
        raise ChildSessionError("child root is unavailable") from None
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700
        ):
            raise ChildSessionError("child root is unsafe")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_or_create_private_directory_at(
    parent_fd: int, name: str, path: Path, *, require_path_binding: bool
) -> int:
    if (
        not isinstance(name, str)
        or not name
        or len(Path(name).parts) != 1
        or name in {".", ".."}
    ):
        raise ChildSessionError("child root is invalid")
    try:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC,
            dir_fd=parent_fd,
        )
    except OSError:
        raise ChildSessionError("child root is unavailable") from None
    try:
        details = os.fstat(descriptor)
        path_details = path.lstat() if require_path_binding else None
        if (
            not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(details.st_mode)
            or _identity(before) != _identity(details)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != 0o700
            or (
                path_details is not None
                and (
                    not stat.S_ISDIR(path_details.st_mode)
                    or _identity(path_details) != _identity(details)
                )
            )
        ):
            raise ChildSessionError("child root is unsafe")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _ensure_private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    except OSError:
        raise ChildSessionError("child root is unavailable") from None
    try:
        details = path.lstat()
    except OSError:
        raise ChildSessionError("child root is unavailable") from None
    if (
        stat.S_ISLNK(details.st_mode)
        or not stat.S_ISDIR(details.st_mode)
        or details.st_uid != os.getuid()
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise ChildSessionError("child root is unsafe")


def _load_json(root: Path | _PinnedChildRoot, name: str) -> Mapping[str, object] | None:
    directory_fd: int | None = None
    root_path: Path | None = None
    if isinstance(root, _PinnedChildRoot):
        if root.closed:
            raise ChildSessionError("child root is unavailable")
        directory_fd = root.fd
    else:
        _ensure_private_directory(root)
        root_path = root
    try:
        if directory_fd is None:
            assert root_path is not None
            descriptor = os.open(root_path / name, os.O_RDONLY | _NOFOLLOW | _CLOEXEC)
        else:
            descriptor = os.open(
                name,
                os.O_RDONLY | _NOFOLLOW | _CLOEXEC,
                dir_fd=directory_fd,
            )
    except FileNotFoundError:
        return None
    except OSError:
        raise ChildSessionError("child durable record is unavailable") from None
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            details = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
            ):
                raise ChildSessionError("child durable record is unsafe")
            if details.st_size > 64 * 1024:
                raise ChildSessionError("child durable record is invalid")
            value = json.loads(stream.read(64 * 1024 + 1).decode("utf-8"))
    except ChildSessionError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError):
        raise ChildSessionError("child durable record is invalid") from None
    if not isinstance(value, Mapping):
        raise ChildSessionError("child durable record is invalid")
    return value


def _write_json(
    root: Path | _PinnedChildRoot, name: str, value: Mapping[str, object]
) -> bool:
    directory_fd: int | None = None
    root_path: Path | None = None
    if isinstance(root, _PinnedChildRoot):
        if root.closed:
            raise ChildSessionError("child root is unavailable")
        directory_fd = root.fd
    else:
        _ensure_private_directory(root)
        root_path = root
    encoded = (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        + b"\n"
    )
    temporary = f".{name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    try:
        if directory_fd is None:
            assert root_path is not None
            owned_directory_fd = os.open(
                root_path, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC
            )
        else:
            owned_directory_fd = os.dup(directory_fd)
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _CLOEXEC,
                0o600,
                dir_fd=owned_directory_fd,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(
                        temporary,
                        name,
                        src_dir_fd=owned_directory_fd,
                        dst_dir_fd=owned_directory_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    return False
                os.fsync(owned_directory_fd)
                return True
            finally:
                try:
                    os.unlink(temporary, dir_fd=owned_directory_fd)
                except FileNotFoundError:
                    pass
        finally:
            os.close(owned_directory_fd)
    except ChildSessionError:
        raise
    except OSError:
        raise ChildSessionError("child durable record is unavailable") from None
