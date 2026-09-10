"""One live Prime owner with durable effects and detachable control views.

Reopening files never recreates a Pi process or worker. Clean reconstruction
attaches to this still-live owner; interrupted effects remain fenced.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
import time
from typing import Literal, Protocol

from asterion.agents.prime.compaction_budget import (
    CompactionReservationQuote,
    ModelPrice,
)
from asterion.agents.prime.context import (
    PrimeContextWitnessSession,
    count_rebuilt_context,
)
from asterion.agents.prime.execution import (
    AsterionPrimeLimits,
    PrimeExecutionKernel,
)
from asterion.agents.prime.state import (
    PrimeBackendIdentity,
    PrimeBackendSnapshot,
    PrimeCheckpoint,
)
from asterion.agents.prime.store import FilePrimeSessionStore
from asterion.control.authority import BudgetUsage, RemainingBudget
from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.state import (
    ControlState,
    SESSION_EVENT_STATUSES,
    reduce_control_event,
)
from asterion.control.protocol import OPAQUE_ID
from asterion.control.session_context import (
    SessionContextCommand,
    SessionContextReceipt,
)
from asterion.runtime.host import CancellationSignal, RunRequest
from asterion.runtimes.pi_extensions import PiExtensionBinding, PiExtensionLease
from asterion.runtimes.pi_rpc import PiRpcCompactResult, PiRpcEvent, PiRpcSession


class PrimeBackendError(RuntimeError):
    """Fixed errors never interpolate private payloads or upstream exceptions."""


class PrimeBackendBudgetError(PrimeBackendError):
    """Positive pre-dispatch budget rejection; no effect has started."""

    def __init__(self) -> None:
        super().__init__("Prime backend budget is unavailable")


class PrimeToolExecutor(Protocol):
    """The preflighted application's worker owner; Pi invokes its bound tools."""

    @property
    def identity_sha256(self) -> str: ...

    def validate_lifecycle(self) -> object:
        """Nonmutating health check returning the same live-owner identity."""
        ...

    async def close(self) -> None: ...


def _json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _encode(value: object) -> bytes:
    return json.dumps(
        _json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(_encode(value)).hexdigest()


def _id(value: object) -> None:
    if type(value) is not str or OPAQUE_ID.fullmatch(value) is None:
        raise PrimeBackendError("Prime backend identity is invalid")


@dataclass(frozen=True, repr=False, slots=True)
class PrimePromptRequest:
    command_id: str
    session_id: str
    generation: int
    input_text: str

    def __post_init__(self) -> None:
        _id(self.command_id)
        _id(self.session_id)
        if type(self.generation) is not int or self.generation < 1:
            raise PrimeBackendError("Prime backend generation is invalid")
        if type(self.input_text) is not str or not self.input_text:
            raise PrimeBackendError("Prime backend prompt is invalid")
        try:
            if len(self.input_text.encode()) > 65536:
                raise ValueError
        except (ValueError, UnicodeError):
            raise PrimeBackendError("Prime backend prompt is invalid") from None

    def __repr__(self) -> str:
        return "<PrimePromptRequest redacted>"


@dataclass(frozen=True, repr=False, slots=True)
class PrimePromptReceipt:
    command_id: str
    record_id: str
    generation: int
    cursor: int
    checkpoint_sha256: str
    status: Literal["completed", "cancelled", "failed"]

    def __repr__(self) -> str:
        return "<PrimePromptReceipt redacted>"


@dataclass(frozen=True, repr=False, slots=True)
class PrimeBackendEvent:
    cursor: int
    event: ControlEvent

    @property
    def type(self) -> str:
        return self.event.type

    def __repr__(self) -> str:
        return "<PrimeBackendEvent redacted>"


@dataclass(frozen=True, slots=True)
class PrimeCleanupReceipt:
    effects_stopped: bool
    application_closed: bool
    pi_closed: bool
    witness_closed: bool
    extension_closed: bool
    store_closed: bool

    @property
    def complete(self) -> bool:
        return all(asdict(self).values())


class _Signal:
    def __init__(
        self,
        owner: PrimeSessionBackend,
        outer: CancellationSignal | None,
        *,
        deadline: float | None = None,
    ):
        self.owner, self.outer = owner, outer
        self.deadline = deadline

    @property
    def cancelled(self) -> bool:
        return (
            self.owner._cancelled
            or self.owner._remaining_seconds() <= 0
            or (self.deadline is not None and time.monotonic() >= self.deadline)
            or (self.outer is not None and self.outer.cancelled)
        )


class PrimeAttachment:
    """A revocable view. Closing it never closes the live resource owners."""

    def __init__(self, backend: PrimeSessionBackend, generation: int) -> None:
        self._backend = backend
        self._generation = generation
        self._closed = False

    @property
    def generation(self) -> int:
        """Attachment serial, separate from the unchanged live kernel generation."""
        return self._generation

    def __repr__(self) -> str:
        return "<PrimeAttachment redacted>"

    def _owner(self) -> PrimeSessionBackend:
        if self._closed:
            raise PrimeBackendError("Prime attachment is closed")
        return self._backend

    def snapshot(self) -> PrimeBackendSnapshot:
        return self._owner().snapshot()

    def replay_events(self, after_cursor: int = 0) -> tuple[PrimeBackendEvent, ...]:
        return self._owner().replay_events(after_cursor)

    async def execute_prompt(
        self, request: PrimePromptRequest, *, signal: CancellationSignal | None = None
    ) -> PrimePromptReceipt:
        return await self._owner().execute_prompt(request, signal=signal)

    async def execute_context(
        self, command: SessionContextCommand
    ) -> SessionContextReceipt:
        return await self._owner().execute_context(command)

    async def accept_control(self, command: ControlCommand) -> None:
        await self._owner().accept_control(command)

    def sync_authority_snapshot(
        self, budget: RemainingBudget, *, authority_revision: int | None = None
    ) -> None:
        self._owner().sync_authority_snapshot(
            budget, authority_revision=authority_revision
        )

    async def cancel_context(self, command_id: str) -> None:
        await self._owner().cancel_context(command_id)

    async def close(self) -> None:
        self._closed = True


class PrimeSessionBackend:
    """Serialize effects on one kernel; acknowledge only durable outcomes."""

    def __init__(
        self,
        *,
        identity: PrimeBackendIdentity,
        store: FilePrimeSessionStore,
        rpc_session: PiRpcSession,
        extension_binding: PiExtensionBinding,
        extension_lease: PiExtensionLease,
        approved_command: tuple[str, ...],
        limits: AsterionPrimeLimits,
        aggregate_tokens: int,
        cost_micros: int,
        approved_environment: Mapping[str, str] | None = None,
        authority_id: str | None = None,
        model_price: ModelPrice | None = None,
        witness: PrimeContextWitnessSession | None = None,
        tool_executor: PrimeToolExecutor | None = None,
    ) -> None:
        try:
            if type(identity) is not PrimeBackendIdentity or store.identity != identity:
                raise ValueError
            if any(
                type(v) is not int or not 1 <= v <= (1 << 53) - 1
                for v in (aggregate_tokens, cost_micros)
            ):
                raise ValueError
            if (
                identity.pi_command_sha256 != _digest(approved_command)
                or identity.extension_binding_fingerprint
                != extension_binding.binding_fingerprint
                or identity.ceilings_sha256
                != _digest(
                    {
                        **asdict(limits),
                        "aggregate_tokens": aggregate_tokens,
                        "cost_micros": cost_micros,
                    }
                )
            ):
                raise ValueError
            if authority_id is not None:
                _id(authority_id)
            self._worker_lifecycle = (
                None if tool_executor is None else tool_executor.validate_lifecycle()
            )
            if tool_executor is not None and self._worker_lifecycle is None:
                raise ValueError
            self._kernel = PrimeExecutionKernel(
                rpc_session=rpc_session,
                extension_binding=extension_binding,
                extension_lease=extension_lease,
                approved_command=approved_command,
                approved_environment=approved_environment,
                limits=limits,
                reusable=True,
            )
            # P1 recovery is attachment reconstruction, not resource resurrection.
            if store.position:
                raise ValueError
        except Exception:
            raise PrimeBackendError("Prime backend configuration is invalid") from None
        self.identity = identity
        self._store, self._rpc, self._lease = store, rpc_session, extension_lease
        self._binding, self._approved_command = extension_binding, approved_command
        self._approved_environment = (
            None if approved_environment is None else dict(approved_environment)
        )
        self._limits = limits
        self._token_cap, self._cost_cap = aggregate_tokens, cost_micros
        self._price, self._witness, self._tool_executor = (
            model_price,
            witness,
            tool_executor,
        )
        self._authority_id = authority_id
        self._authority_revision = 0
        self._budget: RemainingBudget | None = None
        self._usage = BudgetUsage.zero()
        self._snapshot_usage = self._usage
        self._phase: Literal[
            "created",
            "open",
            "effect-active",
            "suspended",
            "terminal",
            "recovery-required",
        ] = "created"
        self._outstanding: str | None = None
        self._events: list[PrimeBackendEvent] = []
        self._control_state = ControlState.empty(
            identity.session_id, generation=identity.generation
        )
        self._commands: dict[str, tuple[str, object]] = {}
        self._keys: dict[str, str] = {}
        self._transcript: list[Mapping[str, object]] = []
        self._summary: bytes | None = None
        self._covered_leaf: str | None = None
        self._checkpoint: PrimeCheckpoint | None = None
        # Only authenticated post-compaction projection proves a current count.
        self._context_tokens: int | None = None
        self._turns = 0
        self._lock = asyncio.Lock()
        self._active_task: asyncio.Task | None = None
        self._cancelled = self._closing = self._opened = False
        self._cleanup: PrimeCleanupReceipt | None = None
        self._deadline: float | None = None
        self._authority_deadline: float | None = None
        self._rpc_lifecycle: object | None = None
        self._attachment_generation = 0
        self._position = 0

    def __repr__(self) -> str:
        return "<PrimeSessionBackend redacted>"

    @property
    def kernel(self) -> PrimeExecutionKernel:
        return self._kernel

    @property
    def usage(self) -> BudgetUsage:
        return self._usage

    def snapshot(self) -> PrimeBackendSnapshot:
        return PrimeBackendSnapshot(
            self.identity,
            len(self._events),
            self._phase,
            self._outstanding,
            self._authority_revision,
        )

    def attach(self, identity: PrimeBackendIdentity) -> PrimeAttachment:
        if type(identity) is not PrimeBackendIdentity or identity != self.identity:
            raise PrimeBackendError("Prime backend identity mismatch")
        self._ready(read_only=True)
        if self._phase == "effect-active":
            raise PrimeBackendError("Prime backend already has an active effect")
        self._validate_recovery()
        self._attachment_generation += 1
        return PrimeAttachment(self, self._attachment_generation)

    def _validate_recovery(self) -> None:
        """Clean recovery means the same live resources, not just matching files."""
        failed = False
        try:
            if self._phase == "recovery-required" or self._outstanding is not None:
                raise ValueError
            if (
                self._tool_executor is None
                or self._tool_executor.identity_sha256
                != self.identity.worker_identity_sha256
            ):
                raise ValueError
            if self._tool_executor.validate_lifecycle() is not self._worker_lifecycle:
                raise ValueError
            self._kernel._validate_launch_material(
                self._rpc,
                self._binding,
                self._lease,
                self._approved_command,
                self._approved_environment,
                self._limits,
            )
            if (
                self._rpc.validate_lifecycle(opened=self._opened)
                is not self._rpc_lifecycle
            ):
                raise ValueError
            records = self._store.records()
            if len(records) != self._position:
                raise ValueError
            recovered = self._store.recover_checkpoint()
            if (
                None if recovered is None else recovered.checkpoint
            ) != self._checkpoint:
                raise ValueError
        except Exception:
            failed = True
        if failed:
            self._fence(self._outstanding or "resource-validation")
            # Raise outside the handler: even introspecting __context__ is safe.
            raise PrimeBackendError("Prime backend recovery required")

    def replay_events(self, after_cursor: int = 0) -> tuple[PrimeBackendEvent, ...]:
        if type(after_cursor) is not int or not 0 <= after_cursor <= len(self._events):
            raise PrimeBackendError("Prime backend cursor is invalid")
        return tuple(self._events[after_cursor:])

    def _append(self, record_id: str, kind: str, payload: Mapping[str, object]):
        try:
            record = self._store.append(
                record_id, kind, payload, expected_position=self._position
            )
            self._position = max(self._position, record.position)
            return record
        except Exception:
            self._phase = "recovery-required"
            raise PrimeBackendError("Prime backend recovery required") from None

    def _event(self, kind: str, payload: Mapping[str, object]) -> None:
        if (
            SESSION_EVENT_STATUSES.get(kind) == self._control_state.session_status
            and kind in SESSION_EVENT_STATUSES
        ):
            return
        cursor = len(self._events) + 1
        event = ControlEvent(
            f"event-{cursor}",
            self.identity.session_id,
            self.identity.generation,
            cursor,
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            kind,
            payload,
        )
        state = reduce_control_event(self._control_state, event)
        self._append(
            f"event-{cursor}",
            "public.event",
            {"cursor": cursor, "event": event.to_mapping()},
        )
        self._events.append(PrimeBackendEvent(cursor, event))
        self._control_state = state

    def _require_created(self) -> None:
        if self._control_state.session_status is None:
            raise PrimeBackendError("Prime backend session is not created")

    def _remaining_seconds(self) -> float:
        deadlines = [
            d for d in (self._deadline, self._authority_deadline) if d is not None
        ]
        return min(deadlines) - time.monotonic() if deadlines else 0.0

    def _ready(self, *, read_only: bool = False) -> None:
        if self._cleanup is not None or self._closing:
            raise PrimeBackendError("Prime backend is closed")
        if not read_only and self._phase == "recovery-required":
            raise PrimeBackendError("Prime backend recovery required")
        if not read_only and (
            self._phase in {"terminal", "suspended"} or self._cancelled
        ):
            raise PrimeBackendError("Prime backend is unavailable")

    def _identity(
        self, session_id: str, generation: int, revision: int | None = None
    ) -> None:
        if (
            session_id != self.identity.session_id
            or generation != self.identity.generation
        ):
            raise PrimeBackendError("Prime backend identity mismatch")
        if revision is not None and revision != self._authority_revision:
            raise PrimeBackendError("Prime backend authority mismatch")

    def _duplicate(self, command_id: str, digest: str) -> object | None:
        previous = self._commands.get(command_id)
        if previous is None:
            return None
        if previous[0] != digest:
            raise PrimeBackendError("Prime backend command digest mismatch")
        return previous[1]

    def sync_authority_snapshot(
        self, budget: RemainingBudget, *, authority_revision: int | None = None
    ) -> None:
        self._ready(read_only=True)
        revision = (
            self._authority_revision
            if authority_revision is None
            else authority_revision
        )
        if (
            type(budget) is not RemainingBudget
            or type(revision) is not int
            or revision < 1
            or revision < self._authority_revision
        ):
            raise PrimeBackendError("Prime backend authority mismatch")
        if self._lock.locked():
            raise PrimeBackendError("Prime backend already has an active effect")
        try:
            self._append(
                f"authority-{self._store.position + 1}",
                "authority",
                {"revision": revision, "remaining": asdict(budget)},
            )
        except Exception:
            self._phase = "recovery-required"
            raise PrimeBackendError("Prime backend recovery required") from None
        self._budget, self._authority_revision = budget, revision
        self._snapshot_usage = self._usage
        self._authority_deadline = time.monotonic() + budget.deadline_ms / 1000

    def _begin(self, command_id: str, digest: str, kind: str) -> None:
        self._ready()
        self._require_created()
        self._validate_recovery()
        try:
            if (
                self._tool_executor is None
                or type(self._price) is not ModelPrice
                or self._tool_executor.identity_sha256
                != self.identity.worker_identity_sha256
            ):
                raise ValueError
        except Exception:
            raise PrimeBackendError("Prime backend worker identity mismatch") from None
        if self._budget is None:
            raise PrimeBackendError("Prime backend budget is unavailable")
        if (
            (
                kind != "context"
                and any(
                    getattr(self._budget, field)
                    <= getattr(self._usage, field)
                    - getattr(self._snapshot_usage, field)
                    for field in (
                        "aggregate_tokens",
                        "application_tokens",
                        "cost_micros",
                    )
                )
            )
            or self._budget.deadline_ms == 0
            or self._usage.aggregate_tokens >= self._token_cap
            or self._usage.cost_micros >= self._cost_cap
        ):
            raise PrimeBackendBudgetError()
        if self._remaining_seconds() <= 0:
            raise PrimeBackendBudgetError()
        self._append(
            f"started-{command_id}",
            "effect-started",
            {"command_id": command_id, "command_sha256": digest, "kind": kind},
        )
        self._outstanding = command_id
        self._phase = "effect-active"
        self._active_task = asyncio.current_task()

    def _fence(self, command_id: str) -> None:
        self._outstanding, self._phase = command_id, "recovery-required"
        self._context_tokens = None
        try:
            self._append(
                f"uncertain-{command_id}",
                "effect-uncertain",
                {"command_id": command_id},
            )
            if self._control_state.session_status is not None:
                self._event(
                    "session.recovery-required", {"reason_code": "uncertain-effect"}
                )
        except Exception:
            # The original write-ahead record remains unresolved even on disk failure.
            pass

    async def mark_uncertain(self, command_id: str) -> None:
        _id(command_id)
        async with self._lock:
            self._fence(command_id)

    def _charge(self, tokens: int, cost: int, *, controller: bool = False) -> None:
        old = self._usage
        usage = BudgetUsage(
            old.controller_tokens + (tokens if controller else 0),
            old.application_tokens + (0 if controller else tokens),
            old.child_tokens,
            old.aggregate_tokens + tokens,
            old.cost_micros + cost,
        )
        if (
            usage.aggregate_tokens > self._token_cap
            or usage.cost_micros > self._cost_cap
        ):
            raise PrimeBackendError("Prime backend usage limit exceeded")
        if (
            not controller
            and self._budget is not None
            and any(
                getattr(usage, field) - getattr(self._snapshot_usage, field)
                > getattr(self._budget, field)
                for field in ("application_tokens", "aggregate_tokens", "cost_micros")
            )
        ):
            raise PrimeBackendError("Prime backend usage limit exceeded")
        self._usage = usage

    def _checkpoint_value(
        self, command_id: str, outstanding: str | None = None
    ) -> PrimeCheckpoint:
        transcript = _encode(self._transcript)
        return PrimeCheckpoint(
            f"checkpoint-{command_id}",
            self.identity.generation,
            len(self._events),
            hashlib.sha256(transcript).hexdigest(),
            None
            if self._summary is None
            else hashlib.sha256(self._summary).hexdigest(),
            self._covered_leaf,
            self.identity.worker_identity_sha256,
            self.identity.continuation_id,
            _digest(asdict(self._usage)),
            outstanding,
            None if self._checkpoint is None else _digest(asdict(self._checkpoint)),
        )

    def _persist_checkpoint(self, checkpoint: PrimeCheckpoint) -> PrimeCheckpoint:
        record = self._store.write_checkpoint(
            checkpoint,
            expected_position=self._position,
            transcript=_encode(self._transcript),
            summary=self._summary,
            usage=asdict(self._usage),
        )
        self._position = record.position
        self._checkpoint = checkpoint
        return checkpoint

    def _seal_checkpoint(
        self, command_id: str, outstanding: str | None = None
    ) -> PrimeCheckpoint:
        return self._persist_checkpoint(self._checkpoint_value(command_id, outstanding))

    async def execute_prompt(
        self, request: PrimePromptRequest, *, signal: CancellationSignal | None = None
    ) -> PrimePromptReceipt:
        if type(request) is not PrimePromptRequest:
            raise PrimeBackendError("Prime backend prompt is invalid")
        self._identity(request.session_id, request.generation)
        digest = _digest(asdict(request))
        async with self._lock:
            self._ready()
            previous = self._duplicate(request.command_id, digest)
            if previous is not None:
                assert isinstance(previous, PrimePromptReceipt)
                return previous
            if signal is not None and signal.cancelled:
                raise asyncio.CancelledError
            self._begin(request.command_id, digest, "prompt")
            self._context_tokens = None
            try:
                if not self._opened:
                    await asyncio.wait_for(
                        self._rpc.open(signal=_Signal(self, signal)),
                        timeout=max(0.001, self._remaining_seconds()),
                    )
                    self._opened = True
                    self._rpc_lifecycle = self._rpc.validate_lifecycle(opened=True)
                    self._deadline = time.monotonic() + self._limits.deadline_ms / 1000
                self._event("session.running", {"reason_code": "prompt-started"})
                status: Literal["completed", "cancelled", "failed"] = "failed"

                def emit(kind: str, payload: Mapping[str, object]) -> None:
                    nonlocal status
                    if kind == "usage.reported":
                        incoming, outgoing = (
                            payload["input_tokens"],
                            payload["output_tokens"],
                        )
                        assert type(incoming) is int and type(outgoing) is int
                        cost = (
                            0
                            if self._price is None
                            else (
                                (incoming * self._price.input_per_million + 999999)
                                // 1000000
                                + (outgoing * self._price.output_per_million + 999999)
                                // 1000000
                            )
                        )
                        self._charge(incoming + outgoing, cost)
                        self._event("budget.reported", asdict(self._usage))
                    elif kind == "run.completed":
                        status = (
                            "cancelled"
                            if payload["status"] == "cancelled"
                            else "completed"
                        )
                    elif kind == "run.failed":
                        status = "failed"

                result = await asyncio.wait_for(
                    self._kernel.invoke(
                        RunRequest(request.command_id, request.input_text),
                        _Signal(self, signal),
                        emit,
                    ),
                    timeout=max(0.001, self._remaining_seconds()),
                )
                if status != "completed":
                    self._fence(request.command_id)
                    raise PrimeBackendError("Prime backend recovery required")
                self._transcript.append(
                    {
                        "command_id": request.command_id,
                        "prompt": request.input_text,
                        "events": [
                            {
                                "sequence": event.sequence,
                                "type": event.type,
                                "payload": event.payload,
                            }
                            for event in result.native_events
                        ],
                        "final_text": result.final_text,
                    }
                )
                self._turns += 1
                self._event("session.paused", {"reason_code": "prompt-completed"})
                self._seal_checkpoint(
                    request.command_id, outstanding=request.command_id
                )
                checkpoint = self._checkpoint_value(f"settled-{request.command_id}")
                receipt = PrimePromptReceipt(
                    request.command_id,
                    f"completed-{request.command_id}",
                    request.generation,
                    len(self._events),
                    _digest(asdict(checkpoint)),
                    status,
                )
                self._append(
                    receipt.record_id,
                    "prompt-completed",
                    {"command_sha256": digest, "receipt": asdict(receipt)},
                )
                self._persist_checkpoint(checkpoint)
                self._commands[request.command_id] = (digest, receipt)
                self._outstanding, self._phase = None, "open"
                return receipt
            except asyncio.CancelledError:
                self._fence(request.command_id)
                raise
            except Exception:
                self._fence(request.command_id)
                raise PrimeBackendError("Prime backend recovery required") from None
            finally:
                self._active_task = None

    def _receipt(
        self,
        command: SessionContextCommand,
        status: str,
        result: Mapping[str, object] | None,
        reason: str = "ok",
    ) -> SessionContextReceipt:
        return SessionContextReceipt(
            f"receipt-{command.command_id}",
            command.command_id,
            command.session_id,
            command.generation,
            command.operation,
            status,
            reason,
            {"evidence_ref": None, "result": result},
        )

    async def execute_context(
        self, command: SessionContextCommand
    ) -> SessionContextReceipt:
        if type(command) is not SessionContextCommand:
            raise PrimeBackendError("Prime backend context is invalid")
        self._identity(
            command.session_id, command.generation, command.authority_revision
        )
        digest = _digest(command.to_mapping())
        async with self._lock:
            self._ready(read_only=command.operation == "session.describe")
            self._require_created()
            previous = self._duplicate(command.command_id, digest)
            if previous is not None:
                assert isinstance(previous, SessionContextReceipt)
                return previous
            key = self._keys.get(command.idempotency_key)
            if key is not None and key != command.command_id:
                raise PrimeBackendError("Prime backend command digest mismatch")
            if command.operation == "session.describe":
                status = (
                    "recovery-required"
                    if self._phase == "recovery-required"
                    else "idle"
                )
                receipt = self._receipt(
                    command,
                    "succeeded" if self._context_tokens is not None else "rejected",
                    None
                    if self._context_tokens is None
                    else {
                        "continuation_id": self.identity.continuation_id,
                        "status": status,
                        "context_tokens": self._context_tokens,
                        "turns": self._turns,
                        "usage": asdict(self._usage),
                        "name_sha256": None,
                    },
                    "context-count-unavailable"
                    if self._context_tokens is None
                    else "completed",
                )
            elif (
                command.payload.get("continuation_id") != self.identity.continuation_id
            ):
                raise PrimeBackendError("Prime backend continuation mismatch")
            elif command.operation == "session.continuation.resume":
                self._validate_recovery()
                if self._checkpoint is None or self._outstanding is not None:
                    raise PrimeBackendError("Prime backend recovery required")
                receipt = self._receipt(
                    command,
                    "succeeded",
                    {
                        "previous_continuation_id": self.identity.continuation_id,
                        "current_continuation_id": self.identity.continuation_id,
                        "transition_sha256": _digest(asdict(self._checkpoint)),
                    },
                )
            elif command.operation == "session.compact":
                return await self._compact(command, digest)
            else:
                receipt = self._receipt(
                    command, "rejected", None, "unsupported-operation"
                )
            try:
                self._append(
                    f"context-{command.command_id}",
                    "context-completed",
                    {"command_sha256": digest, "receipt": receipt.to_mapping()},
                )
            except Exception:
                self._phase = "recovery-required"
                raise PrimeBackendError("Prime backend recovery required") from None
            self._commands[command.command_id] = (digest, receipt)
            self._keys[command.idempotency_key] = command.command_id
            return receipt

    async def _compact(
        self, command: SessionContextCommand, digest: str
    ) -> SessionContextReceipt:
        # Native compaction needs the authenticated witness and operator price.
        if self._witness is None or self._price is None or not self._opened:
            return self._commit_context(
                command,
                digest,
                self._receipt(command, "rejected", None, "context-unavailable"),
            )
        budget = command.payload["budget"]
        assert isinstance(budget, Mapping)
        if command.payload["instructions_ref"] is not None:
            return self._commit_context(
                command,
                digest,
                self._receipt(command, "rejected", None, "instructions-unavailable"),
            )
        deadline = min(
            time.monotonic() + self._remaining_seconds(),
            time.monotonic() + int(budget["deadline_ms"]) / 1000,
        )
        self._begin(command.command_id, digest, "context")
        rpc_task: asyncio.Task[PiRpcCompactResult] | None = None
        native: list[PiRpcEvent] = []
        witness_binding: tuple[str, str, int] | None = None
        try:
            nonce = _digest(command.to_mapping())
            await self._witness.arm(
                command_nonce=nonce,
                deadline=deadline,
                authority_sha256=_digest(
                    {
                        "revision": self._authority_revision,
                        "reservation": budget,
                        "remaining": None
                        if self._budget is None
                        else asdict(self._budget),
                    }
                ),
            )
            rpc_task = asyncio.create_task(
                self._rpc.compact(
                    signal=_Signal(self, None, deadline=deadline),
                    on_event=native.append,
                )
            )

            def reserve(quote: CompactionReservationQuote) -> bool:
                if (
                    int(budget["aggregate_tokens"]) < quote.reserved_tokens
                    or int(budget["controller_tokens"]) < quote.reserved_tokens
                    or int(budget["application_tokens"]) != 0
                    or int(budget["child_tokens"]) != 0
                    or int(budget["cost_micros"]) < quote.cost_micro_units
                    or self._usage.aggregate_tokens + int(budget["aggregate_tokens"])
                    > self._token_cap
                    or self._usage.cost_micros + int(budget["cost_micros"])
                    > self._cost_cap
                ):
                    return False
                self._append(
                    f"reserved-{command.command_id}",
                    "context-reservation",
                    {"command_sha256": digest, "budget": budget},
                )
                # This is private session accounting. Only the host settles its ledger.
                self._kernel.model_callbacks += 2
                self._charge(
                    int(budget["aggregate_tokens"]),
                    int(budget["cost_micros"]),
                    controller=True,
                )
                return True

            approved = await self._witness.receive_proposal_and_decide(
                price=self._price,
                remaining_callbacks=self._limits.model_callbacks
                - self._kernel.model_callbacks,
                deadline=deadline,
                reserve=reserve,
            )
            if not approved:
                native_result = await asyncio.wait_for(
                    rpc_task, max(0.0, deadline - time.monotonic())
                )
                if time.monotonic() >= deadline:
                    raise ValueError
                if native_result.events != tuple(native):
                    raise ValueError
                if native_result.outcome != "aborted":
                    raise ValueError
                self._kernel.observe_context_events(native_result)
                self._rpc.settle_rejected_compact(native_result)
                receipt = self._receipt(
                    command, "rejected", None, "context-not-admitted"
                )
                result = self._commit_context(command, digest, receipt)
                self._outstanding, self._phase = None, "open"
                return result

            def persist(frame: bytes) -> None:
                nonlocal witness_binding
                value = json.loads(frame)
                self._append(
                    f"witness-{command.command_id}",
                    "context-witness",
                    {"canonical_frame": frame.decode()},
                )
                self._summary = value["summary"].encode()
                self._covered_leaf = value["covered_leaf_id"]
                self._context_tokens = count_rebuilt_context(
                    value["post_context_projection"]
                )
                self._transcript.append(
                    {"command_id": command.command_id, "compact_frame": value}
                )
                self._seal_checkpoint(
                    command.command_id, outstanding=command.command_id
                )
                witness_binding = (
                    value["summary_sha256"],
                    value["first_kept_entry_id"],
                    value["compaction_entry"]["tokensBefore"],
                )

            evidence = await self._witness.receive_persisted(persist=persist)
            native_result = await asyncio.wait_for(
                rpc_task, max(0.0, deadline - time.monotonic())
            )
            if time.monotonic() >= deadline:
                raise ValueError
            if native_result.events != tuple(native):
                raise ValueError
            if native_result.outcome != "completed":
                raise ValueError
            body = native_result.events[-2].payload.get("result")
            if not isinstance(body, Mapping) or type(body.get("summary")) is not str:
                raise ValueError
            summary = body["summary"]
            assert isinstance(summary, str)
            # tokensBefore is private matching material, never our public count.
            if witness_binding != (
                hashlib.sha256(summary.encode()).hexdigest(),
                body.get("firstKeptEntryId"),
                body.get("tokensBefore"),
            ):
                raise ValueError
            self._kernel.observe_context_events(native_result)
            receipt = self._receipt(
                command,
                "succeeded",
                {
                    "continuation_id": self.identity.continuation_id,
                    "covered_leaf_id": evidence.covered_leaf_id,
                    "before_context_tokens": evidence.before_context_tokens,
                    "after_context_tokens": evidence.after_context_tokens,
                    "summary_sha256": evidence.summary_sha256,
                    "usage": {
                        key: value
                        for key, value in budget.items()
                        if key != "deadline_ms"
                    },
                },
            )
            self._commit_context(command, digest, receipt)
            self._seal_checkpoint(f"settled-{command.command_id}")
            self._outstanding, self._phase = None, "open"
            return receipt
        except asyncio.CancelledError:
            self._fence(command.command_id)
            raise
        except Exception:
            self._fence(command.command_id)
            # A durable definitive receipt must never be replaced by a conflicting one.
            if command.command_id in self._commands:
                raise PrimeBackendError("Prime backend recovery required") from None
            receipt = self._receipt(command, "uncertain", None, "recovery-required")
            try:
                return self._commit_context(command, digest, receipt)
            except Exception:
                raise PrimeBackendError("Prime backend recovery required") from None
        finally:
            if rpc_task is not None and not rpc_task.done():
                rpc_task.cancel()
            if rpc_task is not None:
                try:
                    await rpc_task
                except BaseException:
                    pass
            self._active_task = None

    def _commit_context(
        self,
        command: SessionContextCommand,
        digest: str,
        receipt: SessionContextReceipt,
    ) -> SessionContextReceipt:
        self._append(
            f"context-{command.command_id}",
            "context-completed",
            {"command_sha256": digest, "receipt": receipt.to_mapping()},
        )
        self._commands[command.command_id] = (digest, receipt)
        self._keys[command.idempotency_key] = command.command_id
        return receipt

    async def accept_control(self, command: ControlCommand) -> None:
        if type(command) is not ControlCommand:
            raise PrimeBackendError("Prime backend control is invalid")
        self._identity(
            command.session_id, self.identity.generation, command.authority_revision
        )
        digest = _digest(command.to_mapping())
        if command.type != "session.create":
            self._require_created()
        # Cancellation can interrupt the lock owner only after exact duplicate checks.
        if self._duplicate(command.command_id, digest) is not None:
            return
        if command.type == "session.cancel":
            self._cancelled = True
            if self._active_task is not None:
                self._active_task.cancel()
        async with self._lock:
            self._ready(read_only=True)
            if self._phase == "recovery-required" and command.type != "session.cancel":
                raise PrimeBackendError("Prime backend recovery required")
            if self._duplicate(command.command_id, digest) is not None:
                return
            if command.type == "session.create":
                if (
                    self._authority_id is None
                    or self._phase != "created"
                    or command.payload["system_id"] != self.identity.application_id
                    or command.payload["system_version"]
                    != self.identity.application_version
                ):
                    raise PrimeBackendError("Prime backend control is invalid")
                self._event(
                    "session.created",
                    {
                        "goal_id": command.payload["goal_id"],
                        "authority_id": self._authority_id,
                        "authority_revision": self._authority_revision,
                    },
                )
                self._phase = "open"
                self._event("session.running", {"reason_code": "session-created"})
            elif command.type == "session.attach":
                cursor = command.payload["cursor"]
                assert isinstance(cursor, Mapping)
                if cursor["generation"] != self.identity.generation:
                    raise PrimeBackendError("Prime backend generation mismatch")
                self.replay_events(cursor["sequence"])  # type: ignore[arg-type]
            elif command.type in {"session.pause", "session.detach"}:
                if command.type == "session.pause":
                    if self._control_state.session_status not in {"running", "paused"}:
                        raise PrimeBackendError("Prime backend control is unavailable")
                    self._phase = "suspended"
                    self._event("session.paused", {"reason_code": "operator-paused"})
            elif command.type == "session.resume":
                self._validate_recovery()
                if self._control_state.session_status not in {"running", "paused"}:
                    raise PrimeBackendError("Prime backend control is unavailable")
                self._phase = "open"
                self._event("session.running", {"reason_code": "operator-resumed"})
            elif command.type == "session.cancel":
                self._phase = (
                    "terminal" if self._outstanding is None else "recovery-required"
                )
                self._event("session.cancelled", {"reason_code": "operator-cancelled"})
            elif command.type == "checkpoint.request":
                if self._outstanding is not None or not self._events:
                    raise PrimeBackendError("Prime backend recovery required")
                checkpoint = self._seal_checkpoint(command.command_id)
                self._event(
                    "checkpoint.created",
                    {
                        "checkpoint_id": command.payload["checkpoint_id"],
                        "capsule_id": checkpoint.checkpoint_id,
                        "capsule_digest": checkpoint.digest,
                        "control_plane_id": "asterion.prime-control",
                        "control_plane_version": "1.0.0",
                        "checkpoint_version": "1.0.0",
                        "covered_sequence": checkpoint.public_event_cursor,
                        "storage_ref": checkpoint.checkpoint_id,
                    },
                )
            else:
                raise PrimeBackendError("Prime backend control is unavailable")
            self._append(
                f"control-{command.command_id}",
                "control-completed",
                {"command_sha256": digest},
            )
            self._commands[command.command_id] = (digest, True)

    async def cancel_context(self, command_id: str) -> None:
        _id(command_id)
        if self._outstanding == command_id and self._active_task is not None:
            self._active_task.cancel()

    async def close(self) -> PrimeCleanupReceipt:
        if self._cleanup is not None:
            return self._cleanup
        self._closing = self._cancelled = True
        active = self._active_task
        if active is not None and active is not asyncio.current_task():
            active.cancel()
            try:
                await active
            except BaseException:
                pass
        async with self._lock:
            if self._cleanup is not None:
                return self._cleanup
            closed: list[bool] = []
            for owner in (
                self._tool_executor,
                self._rpc,
                self._witness,
                self._lease,
                self._store,
            ):
                try:
                    if owner is not None:
                        result = owner.close()  # type: ignore[attr-defined]
                        if inspect.isawaitable(result):
                            await result
                    closed.append(True)
                except BaseException:
                    closed.append(False)
            self._cleanup = PrimeCleanupReceipt(self._active_task is None, *closed)
            if self._phase != "recovery-required":
                self._phase = "terminal"
            return self._cleanup


__all__ = (
    "PrimeAttachment",
    "PrimeBackendError",
    "PrimeBackendBudgetError",
    "PrimeBackendEvent",
    "PrimeCleanupReceipt",
    "PrimePromptRequest",
    "PrimePromptReceipt",
    "PrimeSessionBackend",
)
