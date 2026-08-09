"""Provider-neutral child authority derivation contracts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Protocol

from asterion.control.authority import (
    AuthorityEnvelope,
    AuthorityError,
    BudgetLimit,
    BudgetRequest,
    BudgetUsage,
    AuthorityLedger,
)
from asterion.control.execution import ActionExecutionFailure, ActionExecutionReceipt
from asterion.control.factory import ControlPlaneFactoryContext, ControlPlaneFactoryRegistry
from asterion.control.host import ControlCommand, ControlEvent, ControlPlaneClient
from asterion.control.journal import FileCanonicalJournal
from asterion.control.manager import ActionExecutor, ControlHost
from asterion.control.private_store import MAX_PRIVATE_TEXT_BYTES, PrivateContentResolver
from asterion.control.protocol import OPAQUE_ID
from asterion.control.system import AgentSystemPlan
from asterion.runtime.host import CancellationSignal


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
            or self.status not in {
                "starting", "running", "completed", "failed", "cancelled", "uncertain"
            }
            or (
                self.action_id is not None
                and (not isinstance(self.action_id, str) or OPAQUE_ID.fullmatch(self.action_id) is None)
            )
            or (
                self.receipt_ref is not None
                and (not isinstance(self.receipt_ref, str) or OPAQUE_ID.fullmatch(self.receipt_ref) is None)
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
class _ActiveChild:
    binding: ChildSessionBinding
    digest: str
    task: asyncio.Task[ActionExecutionReceipt]
    runtime: _ChildRuntime | None = None


@dataclass
class _ChildRuntime:
    """The live provider resources retained until close is proved."""

    client: ControlPlaneClient
    host: ControlHost | None = None
    closed: bool = False
    cancel_requested: bool = False


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
        child_action_executor_factory: Callable[[AuthorityEnvelope], ActionExecutor],
        clock_ms: Callable[[], int],
        control_options: Mapping[str, str] = {},
        derive_control_options: DeriveControlOptions | None = None,
        host_services: Mapping[str, object] = {},
    ) -> None:
        if (
            not isinstance(plan, AgentSystemPlan)
            or not isinstance(authority, AuthorityEnvelope)
            or not isinstance(control_factories, ControlPlaneFactoryRegistry)
            or not isinstance(private_root, Path)
            or not callable(getattr(content, "resolve_text", None))
            or not callable(child_action_executor_factory)
            or not callable(clock_ms)
            or (derive_control_options is not None and not callable(derive_control_options))
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
            if any(type(key) is not str or type(value) is not str for key, value in options.items()):
                raise TypeError
        except Exception:
            raise ChildSessionError("child service construction is invalid") from None
        self._control_options = MappingProxyType(options)
        self._derive_options = derive_control_options
        self._host_services = MappingProxyType(services)
        self._entries: dict[str, _ActiveChild] = {}
        self._statuses: dict[str, ChildSessionStatus] = {}
        self._lock = asyncio.Lock()

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

    async def spawn(self, proposal: ControlEvent, signal: CancellationSignal) -> ActionExecutionReceipt:
        child_id = _child_id(proposal, "child.spawn")
        digest = self.proposal_digest(proposal)
        if _cancelled(signal):
            self._statuses[child_id] = ChildSessionStatus(
                child_id, "cancelled", str(proposal.payload["action_id"])
            )
            raise ActionExecutionFailure("cancelled", "child-start-cancelled", None)
        async with self._lock:
            entry = self._entries.get(child_id)
            if entry is not None:
                if entry.digest != digest:
                    raise ChildSessionError("child binding conflicts")
                task = entry.task
            else:
                root = self.prepare_child_root(self._private_root, child_id)
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
                    return terminal.receipt
                if self.load_phase(root) == "provider-create-started":
                    self._statuses[child_id] = ChildSessionStatus(child_id, "uncertain", expected.action_id)
                    raise _uncertain()
                if len(self._entries) >= self._authority.max_concurrent_children:
                    raise ChildSessionError("child concurrency is unavailable")
                # Validation is deliberately before the durable provider fence.
                _validate_goal(self._content, proposal)
                child_authority = derive_child_authority(self._authority, proposal, child_id, now_ms=self._clock_ms())
                self.persist_binding(
                    child_root=root,
                    child_id=expected.child_id,
                    action_id=expected.action_id,
                    session_id=expected.session_id,
                    authority_id=expected.authority_id,
                    generation=expected.generation,
                    proposal_digest=expected.proposal_digest,
                )
                task = asyncio.create_task(self._run_spawn(root, expected, child_authority, proposal, signal))
                entry = _ActiveChild(expected, digest, task)
                self._entries[child_id] = entry
                self._statuses[child_id] = ChildSessionStatus(child_id, "starting", expected.action_id)
        return await task

    async def _run_spawn(
        self,
        root: Path,
        binding: ChildSessionBinding,
        authority: AuthorityEnvelope,
        proposal: ControlEvent,
        signal: CancellationSignal,
    ) -> ActionExecutionReceipt:
        """Run one fenced child to a terminal state and close its provider."""

        runtime: _ChildRuntime | None = None
        try:
            self.persist_phase(child_root=root, phase="provider-create-started")
            options: Mapping[str, str] = self._control_options
            if self._derive_options is not None:
                options = self._derive_options(
                    self._control_options,
                    child_root=root,
                    child_session_id=binding.session_id,
                    child_authority=authority,
                    generation=binding.generation,
                )
            context = ControlPlaneFactoryContext(
                system_id=self._plan.system_id,
                system_version=self._plan.version,
                control_plane_id=self._plan.control_binding.control_plane_id,
                control_plane_version=self._plan.control_binding.version,
                private_root=root,
                options=options,
                host_services=self._host_services,
            )
            factory = self._factories.select(
                self._plan.control_binding.control_plane_id,
                self._plan.control_binding.version,
            ).factory
            client = factory(context)
            runtime = _ChildRuntime(client=client)
            await self._attach_runtime(binding.child_id, runtime)
            executor = self._executor_factory(authority)
            host = ControlHost(
                session_id=binding.session_id,
                generation=binding.generation,
                plan=self._plan,
                authority=AuthorityLedger(authority),
                journal=FileCanonicalJournal.open(root, binding.session_id),
                client=client,
                action_executor=executor,
                clock_ms=self._clock_ms,
                cancellation_signal=signal,
            )
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
        except ActionExecutionFailure:
            raise
        except Exception:
            if runtime is not None:
                try:
                    await _close_runtime(runtime)
                except Exception:
                    pass
            async with self._lock:
                entry = self._entries.get(binding.child_id)
                if entry is not None:
                    self._statuses[binding.child_id] = ChildSessionStatus(
                        binding.child_id, "uncertain", binding.action_id
                    )
            raise _uncertain() from None

    async def _attach_runtime(self, child_id: str, runtime: _ChildRuntime) -> None:
        """Retain a created provider before any later fallible construction."""

        async with self._lock:
            entry = self._entries.get(child_id)
            if entry is None:
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
                    payload={"input_id": action_id, "delivery": "steer", "content_ref": input_ref},
                )
            )
        except Exception:
            await self._mark_uncertain(binding.child_id, binding.action_id)
            raise _uncertain() from None
        return _zero_receipt(action_id, f"child-message-{binding.child_id}-{action_id}")

    async def cancel(
        self, proposal: ControlEvent, signal: CancellationSignal) -> ActionExecutionReceipt:
        """Request cancellation of one exact active child session."""

        del signal
        binding, runtime = await self._active_runtime(proposal, "child.cancel")
        action_id = proposal.payload.get("action_id")
        assert isinstance(action_id, str)
        await self._send_cancel(binding, runtime, command_id=f"child-cancel-{action_id}")
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
        for binding, runtime in active:
            assert runtime is not None
            await self._send_cancel(
                binding, runtime, command_id=f"child-cancel-all-{binding.child_id}"
            )

    async def close(self) -> None:
        """Cancel first, then close retained provider resources exactly once."""

        await self.cancel_all()
        async with self._lock:
            active = tuple(
                (entry.binding, entry.runtime)
                for _, entry in sorted(self._entries.items())
                if entry.runtime is not None
            )
        failures = False
        for binding, runtime in active:
            assert runtime is not None
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
                    if status is not None and status.status in {"completed", "failed", "cancelled"}:
                        self._entries.pop(binding.child_id, None)
        if failures:
            raise ChildSessionError("child provider close is unavailable")

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
        runtime.cancel_requested = True
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
            await self._mark_uncertain(binding.child_id, binding.action_id)
            raise _uncertain() from None

    @staticmethod
    def proposal_digest(proposal: ControlEvent) -> str:
        if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
            raise ChildSessionError("child proposal is invalid")
        encoded = json.dumps(
            proposal.to_mapping(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
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
        child_root: Path,
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
        if existing is not None and ChildSessionBinding.from_mapping(existing) != binding:
            raise ChildSessionError("child binding conflicts")
        if existing is None:
            if not _write_json(child_root, _BINDING_NAME, binding.to_mapping()):
                concurrent = _load_json(child_root, _BINDING_NAME)
                if concurrent is None or ChildSessionBinding.from_mapping(concurrent) != binding:
                    raise ChildSessionError("child binding conflicts")
        return binding.proposal_digest

    @staticmethod
    def load_binding(child_root: Path) -> ChildSessionBinding | None:
        value = _load_json(child_root, _BINDING_NAME)
        return None if value is None else ChildSessionBinding.from_mapping(value)

    @staticmethod
    def persist_phase(*, child_root: Path, phase: str) -> None:
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
    def load_phase(child_root: Path) -> str | None:
        value = _load_json(child_root, _PHASE_NAME)
        if value is None:
            return None
        if not isinstance(value, Mapping) or dict(value) != {"phase": "provider-create-started"}:
            raise ChildSessionError("child phase is invalid")
        return "provider-create-started"

    @staticmethod
    def persist_terminal(
        *, child_root: Path, terminal: ChildTerminalReceipt
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
    def load_terminal(child_root: Path) -> ChildTerminalReceipt | None:
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
        return ActionExecutionFailure("failed", "child-terminal-failed", "child-terminal")
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


def _load_json(root: Path, name: str) -> Mapping[str, object] | None:
    _ensure_private_directory(root)
    try:
        descriptor = os.open(root / name, os.O_RDONLY | _NOFOLLOW | _CLOEXEC)
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


def _write_json(root: Path, name: str, value: Mapping[str, object]) -> bool:
    _ensure_private_directory(root)
    encoded = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
        + b"\n"
    )
    temporary = f".{name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    try:
        directory_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC)
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _CLOEXEC,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=True) as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
                except FileExistsError:
                    return False
                os.fsync(directory_fd)
                return True
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory_fd)
    except ChildSessionError:
        raise
    except OSError:
        raise ChildSessionError("child durable record is unavailable") from None
