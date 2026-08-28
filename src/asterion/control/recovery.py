"""Pure reconstruction of host-owned control state from a canonical journal."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from asterion.control.authority import (
    ActionReceipt,
    AdmissionDecision,
    AuthorityEnvelope,
    AuthorityError,
    AuthorityLedger,
    BudgetRequest,
    BudgetUsage,
    ProviderUsageReport,
    SessionContextDecision,
    SessionContextSettlement,
    OperationDecision,
    OperationSettlement,
    session_context_command_digest,
)

if TYPE_CHECKING:
    from asterion.operation.protocol import OperationReceipt, OperationTransaction
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.host import ControlCommand, ControlEvent, EventCursor
from asterion.control.journal import (
    JournalConflictError,
    JournalEntry,
)
from asterion.control.session_context import (
    SESSION_CONTEXT_MODEL_OPERATIONS,
    SessionContextCommand,
    SessionContextReceipt,
)
from asterion.control.state import (
    ControlState,
    ControlStateError,
    apply_action_admission,
    apply_action_resolution,
    apply_authority_revision,
    mark_session_recovery_required,
    mark_action_running,
    reconcile_uncertain_action,
    reduce_control_event,
)


_RecoveryAuthorityOperation = (
    AdmissionDecision
    | ActionReceipt
    | ProviderUsageReport
    | SessionContextDecision
    | SessionContextSettlement
    | OperationDecision
    | OperationSettlement
)


@dataclass(frozen=True)
class RecoveredControlState:
    state: ControlState
    authority: AuthorityLedger
    cursor: EventCursor
    journal_position: int
    proposals: Mapping[str, ControlEvent]
    admission_commands: Mapping[str, ControlCommand]
    terminal_commands: Mapping[str, ControlCommand]
    result_receipts: Mapping[str, ActionExecutionReceipt]
    running_action_ids: tuple[str, ...]
    session_context_commands: Mapping[str, SessionContextCommand]
    session_context_decisions: Mapping[str, SessionContextDecision]
    session_context_receipts: Mapping[str, SessionContextReceipt]

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposals", MappingProxyType(dict(self.proposals)))
        object.__setattr__(
            self,
            "admission_commands",
            MappingProxyType(dict(self.admission_commands)),
        )
        object.__setattr__(
            self,
            "terminal_commands",
            MappingProxyType(dict(self.terminal_commands)),
        )
        object.__setattr__(
            self,
            "result_receipts",
            MappingProxyType(dict(self.result_receipts)),
        )
        object.__setattr__(
            self,
            "session_context_commands",
            MappingProxyType(dict(self.session_context_commands)),
        )
        object.__setattr__(
            self,
            "session_context_decisions",
            MappingProxyType(dict(self.session_context_decisions)),
        )
        object.__setattr__(
            self,
            "session_context_receipts",
            MappingProxyType(dict(self.session_context_receipts)),
        )

    @property
    def authority_usage(self) -> BudgetUsage:
        return self.authority.usage

    @property
    def reservations(self) -> tuple[str, ...]:
        return self.authority.reserved_action_ids


@dataclass
class _OperationRecoveryPhase:
    """Strict, per-operation durable prefix used by control-state recovery."""

    transaction: OperationTransaction | None = None
    decision: OperationDecision | None = None
    reserved: bool = False
    dispatched: bool = False
    handoff: bool = False
    prepared_proof_digest: str | None = None
    entered_proof_digest: str | None = None
    receipt: OperationReceipt | None = None
    reconciliation_attempt: int = 0
    reconciled_after_uncertain: bool = False


def recover_control_host_state(
    entries: Sequence[JournalEntry],
    envelope: AuthorityEnvelope,
    *,
    expected_session_id: str | None = None,
    expected_generation: int | None = None,
) -> RecoveredControlState:
    """Validate and replay one complete journal prefix without mutating inputs."""

    try:
        values = tuple(entries)
        if not isinstance(envelope, AuthorityEnvelope) or not values:
            raise JournalConflictError("control journal recovery failed")
        if (expected_session_id is None) != (expected_generation is None):
            raise JournalConflictError("control journal recovery failed")
        _validate_entries(values)
        system = values[0].record
        if system.kind != "system.bound":
            raise JournalConflictError("control journal recovery failed")
        system_id = str(system.payload["system_id"])
        system_version = str(system.payload["system_version"])
        authority_id = envelope.authority_id
        journal_revision = envelope.revision
        start = 1
        if len(values) >= 2:
            authority_binding = values[1].record
            if authority_binding.kind != "authority.bound":
                raise JournalConflictError("control journal recovery failed")
            authority_id = str(authority_binding.payload["authority_id"])
            journal_revision = _integer(authority_binding.payload["authority_revision"])
            if (
                authority_id != envelope.authority_id
                or journal_revision > envelope.revision
            ):
                raise JournalConflictError("control journal recovery failed")
            start = 2

        state: ControlState | None = None
        session_id = expected_session_id
        proposals: dict[str, ControlEvent] = {}
        accepted_events: dict[str, ControlEvent] = {}
        receipts: dict[str, ActionReceipt] = {}
        result_receipts: dict[str, ActionExecutionReceipt] = {}
        authority_operations: list[_RecoveryAuthorityOperation] = []
        decisions: dict[str, AdmissionDecision] = {}
        terminal_commands: dict[str, ControlCommand] = {}
        admission_commands: dict[str, ControlCommand] = {}
        running_action_ids: set[str] = set()
        context_commands: dict[str, SessionContextCommand] = {}
        context_decisions: dict[str, SessionContextDecision] = {}
        context_receipts: dict[str, SessionContextReceipt] = {}
        context_idempotency: dict[str, str] = {}
        operation_phases: dict[str, _OperationRecoveryPhase] = {}

        for entry in values[start:]:
            record = entry.record
            if record.kind in {
                "client.intent.accepted",
                "client.observation.accepted",
                "client.event.accepted",
            }:
                continue
            if _recover_operation_record(record, operation_phases, authority_operations):
                continue
            if record.kind == "event.accepted":
                event = ControlEvent.from_mapping(_mapping(record.payload["event"]))
                if event.type == "session.created" and (
                    event.payload["authority_id"] != authority_id
                    or event.payload["authority_revision"] != journal_revision
                ):
                    raise JournalConflictError("control journal recovery failed")
                state, session_id = _reduce_event(
                    state, session_id, event, accepted_events
                )
                if event.type == "action.proposed":
                    action_id = str(event.payload["action_id"])
                    if action_id in proposals:
                        raise JournalConflictError("control journal recovery failed")
                    proposals[action_id] = event
                if event.type == "budget.reported":
                    authority_operations.append(
                        ProviderUsageReport(_usage(event.payload))
                    )
                continue
            if record.kind == "checkpoint.sealed":
                event = ControlEvent.from_mapping(
                    _mapping(record.payload["checkpoint_event"])
                )
                existing = accepted_events.get(event.event_id)
                if existing is None:
                    state, session_id = _reduce_event(
                        state, session_id, event, accepted_events
                    )
                elif existing != event:
                    raise JournalConflictError("control journal recovery failed")
                continue
            if record.kind == "command.accepted":
                command = ControlCommand.from_mapping(
                    _mapping(record.payload["command"])
                )
                session_id = _bind_session(session_id, command.session_id)
                if command.authority_revision != journal_revision:
                    raise JournalConflictError("control journal recovery failed")
                if command.type == "session.create" and (
                    command.payload["system_id"] != system_id
                    or command.payload["system_version"] != system_version
                ):
                    raise JournalConflictError("control journal recovery failed")
                if command.type == "action.resolve":
                    state = _apply_resolution_command(
                        state,
                        command,
                        receipts=receipts,
                        decisions=decisions,
                        admission_commands=admission_commands,
                        terminal_commands=terminal_commands,
                    )
                continue
            if record.kind == "context.command.accepted":
                command = SessionContextCommand.from_mapping(
                    _mapping(record.payload["command"])
                )
                session_id = _bind_session(session_id, command.session_id)
                if (
                    command.generation
                    != (expected_generation if state is None else state.generation)
                    or command.authority_revision != journal_revision
                    or command.command_id in context_commands
                ):
                    raise JournalConflictError("control journal recovery failed")
                digest = session_context_command_digest(command)
                prior_digest = context_idempotency.get(command.idempotency_key)
                if prior_digest is not None and prior_digest != digest:
                    raise JournalConflictError("control journal recovery failed")
                context_commands[command.command_id] = command
                context_idempotency[command.idempotency_key] = digest
                continue
            if record.kind == "context.operation.decided":
                command_id = str(record.payload["command_id"])
                command = context_commands.get(command_id)
                if command is None or command_id in context_decisions:
                    raise JournalConflictError("control journal recovery failed")
                status = str(record.payload["status"])
                reservation = None
                if status == "admitted" and (
                    command.operation in SESSION_CONTEXT_MODEL_OPERATIONS
                ):
                    reservation = BudgetRequest.from_mapping(
                        _mapping(command.payload["budget"])
                    )
                decision = SessionContextDecision(
                    command_id=command_id,
                    idempotency_key=str(record.payload["idempotency_key"]),
                    authority_id=authority_id,
                    authority_revision=_integer(record.payload["authority_revision"]),
                    operation=str(record.payload["operation"]),
                    command_digest=str(record.payload["command_digest"]),
                    status=status,
                    reason=str(record.payload["reason"]),
                    reservation=reservation,
                )
                if (
                    decision.idempotency_key != command.idempotency_key
                    or decision.authority_revision != command.authority_revision
                    or decision.operation != command.operation
                    or decision.command_digest
                    != session_context_command_digest(command)
                ):
                    raise JournalConflictError("control journal recovery failed")
                context_decisions[command_id] = decision
                if decision.status == "admitted":
                    authority_operations.append(decision)
                continue
            if record.kind == "context.operation.receipted":
                receipt = SessionContextReceipt.from_mapping(
                    _mapping(record.payload["receipt"])
                )
                command = context_commands.get(receipt.command_id)
                decision = context_decisions.get(receipt.command_id)
                if (
                    command is None
                    or decision is None
                    or receipt.command_id in context_receipts
                    or receipt.session_id != command.session_id
                    or receipt.generation != command.generation
                    or receipt.operation != command.operation
                    or (decision.status == "rejected" and receipt.status != "rejected")
                ):
                    raise JournalConflictError("control journal recovery failed")
                usage_value = record.payload["usage"]
                if receipt.status == "uncertain":
                    if usage_value is not None:
                        raise JournalConflictError("control journal recovery failed")
                elif decision.status == "admitted":
                    usage = _usage(usage_value)
                    if (
                        receipt.status == "succeeded"
                        and command.operation in SESSION_CONTEXT_MODEL_OPERATIONS
                        and usage
                        != _usage(_mapping(receipt.payload["result"])["usage"])
                    ):
                        raise JournalConflictError("control journal recovery failed")
                    authority_operations.append(
                        SessionContextSettlement(
                            command_id=receipt.command_id,
                            receipt_id=receipt.receipt_id,
                            usage=usage,
                        )
                    )
                elif _usage(usage_value) != BudgetUsage.zero():
                    raise JournalConflictError("control journal recovery failed")
                context_receipts[receipt.command_id] = receipt
                if receipt.status == "uncertain" and state is not None:
                    state = mark_session_recovery_required(state)
                continue
            if record.kind == "action.decided":
                if state is None:
                    raise JournalConflictError("control journal recovery failed")
                action_id = str(record.payload["action_id"])
                proposal = proposals.get(action_id)
                if proposal is None:
                    raise JournalConflictError("control journal recovery failed")
                status = str(record.payload["status"])
                reservation = None
                if status == "admitted":
                    reservation = BudgetRequest.from_mapping(
                        _mapping(proposal.payload["budget"])
                    )
                decision = AdmissionDecision(
                    action_id=action_id,
                    authority_id=str(authority_id),
                    authority_revision=_integer(record.payload["authority_revision"]),
                    proposal_digest=str(record.payload["proposal_digest"]),
                    status=status,
                    reason=str(record.payload["reason"]),
                    reservation=reservation,
                )
                if decision.authority_revision != journal_revision:
                    raise JournalConflictError("control journal recovery failed")
                if action_id in decisions:
                    raise JournalConflictError("control journal recovery failed")
                decisions[action_id] = decision
                if decision.status == "admitted":
                    authority_operations.append(decision)
                state = apply_action_admission(state, decision)
                continue
            if record.kind == "action.running":
                if state is None:
                    raise JournalConflictError("control journal recovery failed")
                action_id = str(record.payload["action_id"])
                decision = decisions.get(action_id)
                if (
                    decision is None
                    or decision.status != "admitted"
                    or record.payload["proposal_digest"] != decision.proposal_digest
                    or action_id not in admission_commands
                    or action_id in running_action_ids
                ):
                    raise JournalConflictError("control journal recovery failed")
                state = mark_action_running(state, action_id)
                running_action_ids.add(action_id)
                continue
            if record.kind == "action.receipted":
                if state is None:
                    raise JournalConflictError("control journal recovery failed")
                action_id = str(record.payload["action_id"])
                usage = _usage(record.payload["usage"])
                receipt = ActionReceipt(
                    action_id=action_id,
                    receipt_ref=str(record.payload["receipt_ref"]),
                    usage=usage,
                )
                result_receipt = ActionExecutionReceipt(
                    action_id=action_id,
                    receipt_ref=receipt.receipt_ref,
                    usage=usage,
                    artifact_ids=_string_tuple(record.payload.get("artifact_ids", ())),
                    media_types=_string_tuple(record.payload.get("media_types", ())),
                )
                existing = receipts.get(action_id)
                if existing is not None:
                    raise JournalConflictError("control journal recovery failed")
                receipts[action_id] = receipt
                result_receipts[action_id] = result_receipt
                authority_operations.append(receipt)
                action = state.actions.get(action_id)
                if action is None:
                    raise JournalConflictError("control journal recovery failed")
                if action.status == "admitted":
                    # Task 8 journals predate the explicit executor-contact fence.
                    state = mark_action_running(state, action_id)
                elif action.status == "uncertain":
                    terminal = terminal_commands.get(action_id)
                    if (
                        terminal is None
                        or terminal.payload["resolution"] != "succeeded"
                        or terminal.payload["receipt_ref"] != receipt.receipt_ref
                    ):
                        raise JournalConflictError("control journal recovery failed")
                    state = reconcile_uncertain_action(
                        state,
                        action_id,
                        "succeeded",
                        receipt_ref=receipt.receipt_ref,
                    )
                elif action.status != "running":
                    raise JournalConflictError("control journal recovery failed")
                continue
            if record.kind == "authority.revised":
                if state is None or record.payload["authority_id"] != authority_id:
                    raise JournalConflictError("control journal recovery failed")
                revision = _integer(record.payload["authority_revision"])
                if revision <= journal_revision or revision > envelope.revision:
                    raise JournalConflictError("control journal recovery failed")
                state = apply_authority_revision(state, revision)
                journal_revision = revision
                continue
            if record.kind in {"fault.projected"}:
                continue
            raise JournalConflictError("control journal recovery failed")

        if journal_revision != envelope.revision:
            raise JournalConflictError("control journal recovery failed")
        if state is None:
            if expected_session_id is None or expected_generation is None:
                raise JournalConflictError("control journal recovery failed")
            state = ControlState.empty(
                expected_session_id, generation=expected_generation
            )
        if expected_session_id is not None and (
            state.session_id != expected_session_id
            or state.generation != expected_generation
        ):
            raise JournalConflictError("control journal recovery failed")
        ledger = AuthorityLedger._from_recovery(envelope, authority_operations)
        return RecoveredControlState(
            state=state,
            authority=ledger,
            cursor=EventCursor(
                generation=state.generation,
                sequence=state.next_sequence - 1,
            ),
            journal_position=len(values),
            proposals=proposals,
            admission_commands=admission_commands,
            terminal_commands=terminal_commands,
            result_receipts=result_receipts,
            running_action_ids=tuple(sorted(running_action_ids)),
            session_context_commands=context_commands,
            session_context_decisions=context_decisions,
            session_context_receipts=context_receipts,
        )
    except JournalConflictError:
        raise
    except (AuthorityError, ControlStateError, KeyError, TypeError, ValueError):
        raise JournalConflictError("control journal recovery failed") from None


def _recover_operation_record(
    record: object,
    phases: dict[str, _OperationRecoveryPhase],
    authority_operations: list[_RecoveryAuthorityOperation],
) -> bool:
    """Replay one operation record and report whether the record belonged to this FSM."""

    from asterion.operation.protocol import OperationReceipt, OperationTransaction

    kind = getattr(record, "kind", None)
    payload = getattr(record, "payload", None)
    if not isinstance(payload, Mapping):
        raise JournalConflictError("control journal recovery failed")
    if kind == "operation.transaction.accepted":
        value = payload.get("transaction")
        if not isinstance(value, Mapping):
            raise JournalConflictError("control journal recovery failed")
        transaction = OperationTransaction.from_mapping(value)
        phase = phases.setdefault(transaction.operation_id, _OperationRecoveryPhase())
        if phase.transaction is not None:
            raise JournalConflictError("control journal recovery failed")
        phase.transaction = transaction
        return True
    if kind == "operation.admitted":
        decision = OperationDecision(**payload)  # type: ignore[arg-type]
        phase = phases.get(decision.operation_id)
        if phase is None or phase.transaction is None:
            raise JournalConflictError("control journal recovery failed")
        transaction = phase.transaction
        if (
            phase.decision is not None
            or phase.receipt is not None
            or decision.authority_id != transaction.authority_id
            or decision.authority_revision != transaction.authority_revision
            or decision.feature_id != transaction.feature_id
            or decision.transaction_digest != _operation_transaction_digest(transaction)
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.decision = decision
        return True
    if kind == "operation.reserved":
        operation_id = payload.get("operation_id")
        digest = payload.get("transaction_digest")
        phase = phases.get(operation_id) if isinstance(operation_id, str) else None
        if (
            phase is None
            or phase.decision is None
            or not isinstance(digest, str)
            or phase.decision.status != "admitted"
            or phase.reserved
            or phase.receipt is not None
            or digest != phase.decision.transaction_digest
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.reserved = True
        authority_operations.append(phase.decision)
        return True
    if kind == "operation.dispatch.started":
        phase = _operation_phase_for_digest(phases, record)
        if (
            phase.decision is None
            or phase.decision.status != "admitted"
            or not phase.reserved
            or phase.dispatched
            or phase.handoff
            or phase.prepared_proof_digest is not None
            or phase.entered_proof_digest is not None
            or phase.receipt is not None
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.dispatched = True
        return True
    if kind == "operation.handoff.fenced":
        phase = _operation_phase_for_digest(phases, record)
        if (
            phase.decision is None
            or phase.decision.status != "admitted"
            or not phase.reserved
            or not phase.dispatched
            or phase.handoff
            or phase.prepared_proof_digest is not None
            or phase.entered_proof_digest is not None
            or phase.receipt is not None
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.handoff = True
        return True
    if kind == "operation.handoff.prepared":
        phase = _operation_phase_for_digest(phases, record)
        proof = payload.get("handoff_proof_digest")
        if (
            phase.decision is None
            or phase.decision.status != "admitted"
            or not phase.reserved
            or not phase.dispatched
            or phase.handoff
            or phase.prepared_proof_digest is not None
            or phase.entered_proof_digest is not None
            or phase.receipt is not None
            or type(proof) is not str
            or len(proof) != 64
            or any(character not in "0123456789abcdef" for character in proof)
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.prepared_proof_digest = proof
        return True
    if kind == "operation.handoff.entered":
        phase = _operation_phase_for_digest(phases, record)
        proof = payload.get("handoff_proof_digest")
        if (
            phase.decision is None
            or phase.decision.status != "admitted"
            or not phase.reserved
            or not phase.dispatched
            or phase.handoff
            or phase.prepared_proof_digest is None
            or phase.entered_proof_digest is not None
            or phase.receipt is not None
            or proof != phase.prepared_proof_digest
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.entered_proof_digest = proof
        return True
    if kind == "operation.reconciliation.recorded":
        operation_id = payload.get("operation_id")
        attempt = payload.get("attempt")
        phase = phases.get(operation_id) if isinstance(operation_id, str) else None
        if (
            phase is None
            or phase.transaction is None
            or phase.decision is None
            or type(attempt) is not int
            or phase.decision.status != "admitted"
            or not phase.reserved
            or not phase.dispatched
            or phase.receipt is None
            or phase.receipt.status != "uncertain"
            or (
                phase.prepared_proof_digest is not None
                and phase.entered_proof_digest is None
            )
            or attempt != phase.reconciliation_attempt + 1
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.reconciliation_attempt = attempt
        phase.reconciled_after_uncertain = True
        return True
    if kind == "operation.receipted":
        value = payload.get("receipt")
        if not isinstance(value, Mapping):
            raise JournalConflictError("control journal recovery failed")
        receipt = OperationReceipt.from_mapping(value)
        phase = phases.get(receipt.operation_id)
        if (
            phase is None
            or phase.transaction is None
            or not _same_operation_identity(phase.transaction, receipt)
        ):
            raise JournalConflictError("control journal recovery failed")
        _record_recovered_operation_receipt(phase, receipt)
        if (
            receipt.status != "uncertain"
            and phase.decision is not None
            and phase.decision.status == "admitted"
            and phase.reserved
        ):
            authority_operations.append(
                OperationSettlement(
                    receipt.operation_id,
                    receipt.receipt_id,
                    _operation_receipt_digest(receipt),
                )
            )
        return True
    return False


def _same_operation_identity(
    transaction: OperationTransaction, receipt: OperationReceipt
) -> bool:
    return (
        receipt.operation_id == transaction.operation_id
        and receipt.request_ref == transaction.request.request_ref
        and receipt.request_sha256 == transaction.request.request_sha256
        and receipt.purpose == transaction.request.purpose
        and receipt.session_id == transaction.session_id
        and receipt.client_id == transaction.client_id
        and receipt.generation == transaction.generation
        and receipt.authority_revision == transaction.authority_revision
        and receipt.authority_id == transaction.authority_id
        and receipt.idempotency_key == transaction.idempotency_key
        and receipt.feature_id == transaction.feature_id
    )


def _operation_phase_for_digest(
    phases: Mapping[str, _OperationRecoveryPhase], record: object
) -> _OperationRecoveryPhase:
    payload = getattr(record, "payload", None)
    if not isinstance(payload, Mapping):
        raise JournalConflictError("control journal recovery failed")
    operation_id = payload.get("operation_id")
    digest = payload.get("transaction_digest")
    if not isinstance(operation_id, str) or not isinstance(digest, str):
        raise JournalConflictError("control journal recovery failed")
    phase = phases.get(operation_id)
    if (
        phase is None
        or phase.transaction is None
        or digest != _operation_transaction_digest(phase.transaction)
    ):
        raise JournalConflictError("control journal recovery failed")
    return phase


def _record_recovered_operation_receipt(
    phase: _OperationRecoveryPhase, receipt: OperationReceipt
) -> None:
    """Validate every operation receipt as the next legal durable phase."""

    prior = phase.receipt
    decision = phase.decision
    if prior is not None:
        if (
            prior.status != "uncertain"
            or receipt.status == "uncertain"
            or not phase.reconciled_after_uncertain
            or receipt.status not in {"succeeded", "failed", "cancelled", "rejected"}
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.receipt = receipt
        return
    if decision is None:
        if (
            receipt.status != "rejected"
            or phase.reserved
            or phase.dispatched
            or phase.handoff
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.receipt = receipt
        return
    if decision.status == "rejected":
        if (
            receipt.status != "rejected"
            or phase.reserved
            or phase.dispatched
            or phase.handoff
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.receipt = receipt
        return
    if not phase.reserved:
        raise JournalConflictError("control journal recovery failed")
    if receipt.status == "uncertain":
        if not phase.dispatched or (
            phase.prepared_proof_digest is not None
            and phase.entered_proof_digest is None
        ):
            raise JournalConflictError("control journal recovery failed")
        phase.receipt = receipt
        return
    if phase.dispatched:
        entered_staged_handoff = (
            phase.prepared_proof_digest is not None
            and phase.entered_proof_digest == phase.prepared_proof_digest
        )
        if not phase.handoff and not entered_staged_handoff:
            raise JournalConflictError("control journal recovery failed")
    elif (
        receipt.status not in {"failed", "cancelled"}
        or receipt.reason_code
        not in {"private-request-unavailable", "cancelled-before-dispatch"}
    ):
        raise JournalConflictError("control journal recovery failed")
    phase.receipt = receipt


def _operation_transaction_digest(transaction: OperationTransaction) -> str:
    from asterion.control.authority import operation_transaction_digest

    return operation_transaction_digest(transaction)


def _operation_receipt_digest(receipt: OperationReceipt) -> str:
    import hashlib
    import json

    return hashlib.sha256(
        json.dumps(
            _json_value(receipt.to_mapping()),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _validate_entries(entries: tuple[JournalEntry, ...]) -> None:
    record_ids: set[str] = set()
    for position, entry in enumerate(entries, start=1):
        if (
            not isinstance(entry, JournalEntry)
            or entry.position != position
            or entry.digest != entry.record.digest
            or entry.record.record_id in record_ids
        ):
            raise JournalConflictError("control journal recovery failed")
        if position == 1 and entry.record.kind != "system.bound":
            raise JournalConflictError("control journal recovery failed")
        if position == 2 and entry.record.kind != "authority.bound":
            raise JournalConflictError("control journal recovery failed")
        if position > 2 and entry.record.kind in {"system.bound", "authority.bound"}:
            raise JournalConflictError("control journal recovery failed")
        record_ids.add(entry.record.record_id)


def _reduce_event(
    state: ControlState | None,
    session_id: str | None,
    event: ControlEvent,
    accepted_events: dict[str, ControlEvent],
) -> tuple[ControlState, str]:
    session_id = _bind_session(session_id, event.session_id)
    existing = accepted_events.get(event.event_id)
    if existing is not None:
        if existing != event:
            raise JournalConflictError("control journal recovery failed")
        if state is None:
            raise JournalConflictError("control journal recovery failed")
        return state, session_id
    if state is None:
        state = ControlState.empty(session_id, generation=event.generation)
    state = reduce_control_event(state, event)
    accepted_events[event.event_id] = event
    return state, session_id


def _bind_session(current: str | None, candidate: str) -> str:
    if current is not None and current != candidate:
        raise JournalConflictError("control journal recovery failed")
    return candidate


def _apply_resolution_command(
    state: ControlState | None,
    command: ControlCommand,
    *,
    receipts: Mapping[str, ActionReceipt],
    decisions: Mapping[str, AdmissionDecision],
    admission_commands: dict[str, ControlCommand],
    terminal_commands: dict[str, ControlCommand],
) -> ControlState:
    if state is None:
        raise JournalConflictError("control journal recovery failed")
    resolution = str(command.payload["resolution"])
    if resolution in {"admitted", "rejected"}:
        action_id = str(command.payload["action_id"])
        decision = decisions.get(action_id)
        if (
            decision is None
            or resolution != decision.status
            or command.payload["reason_code"] != decision.reason
            or command.payload["receipt_ref"] is not None
            or command.command_id != f"admission:{action_id}"
        ):
            raise JournalConflictError("control journal recovery failed")
        existing_admission = admission_commands.get(action_id)
        if existing_admission is not None and existing_admission != command:
            raise JournalConflictError("control journal recovery failed")
        admission_commands[action_id] = command
        return state
    action_id = str(command.payload["action_id"])
    if command.command_id != f"terminal:{action_id}":
        raise JournalConflictError("control journal recovery failed")
    decision = decisions.get(action_id)
    if (
        decision is None
        or decision.status != "admitted"
        or action_id not in admission_commands
    ):
        raise JournalConflictError("control journal recovery failed")
    existing = terminal_commands.get(action_id)
    if existing is not None:
        if existing != command:
            raise JournalConflictError("control journal recovery failed")
        return state
    terminal_commands[action_id] = command
    action = state.actions.get(action_id)
    if action is None:
        raise JournalConflictError("control journal recovery failed")
    if (
        action.status == "admitted"
        and resolution == "cancelled"
        and command.payload["receipt_ref"] is None
        and command.payload["reason_code"] == "cancelled-before-start"
    ):
        return apply_action_resolution(state, action_id, "cancelled")
    if action.status != "running":
        raise JournalConflictError("control journal recovery failed")
    receipt = receipts.get(action_id)
    receipt_ref = command.payload["receipt_ref"]
    if resolution == "succeeded":
        if receipt is None or receipt_ref != receipt.receipt_ref:
            raise JournalConflictError("control journal recovery failed")
        return apply_action_resolution(
            state,
            action_id,
            "succeeded",
            receipt_ref=receipt.receipt_ref,
        )
    if resolution == "uncertain":
        if receipt is not None or receipt_ref is not None:
            raise JournalConflictError("control journal recovery failed")
        return apply_action_resolution(
            state,
            action_id,
            "uncertain",
            receipt_ref=(str(receipt_ref) if receipt_ref is not None else None),
        )
    if resolution in {"failed", "cancelled"}:
        if receipt is not None or (resolution == "failed" and receipt_ref is None):
            raise JournalConflictError("control journal recovery failed")
        return apply_action_resolution(
            state,
            action_id,
            resolution,
            receipt_ref=(str(receipt_ref) if receipt_ref is not None else None),
        )
    raise JournalConflictError("control journal recovery failed")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise JournalConflictError("control journal recovery failed")
    return {str(key): _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _usage(value: object) -> BudgetUsage:
    usage = _mapping(value)
    return BudgetUsage(
        controller_tokens=_integer(usage["controller_tokens"]),
        application_tokens=_integer(usage["application_tokens"]),
        child_tokens=_integer(usage["child_tokens"]),
        aggregate_tokens=_integer(usage["aggregate_tokens"]),
        cost_micros=_integer(usage["cost_micros"]),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, str) for item in value
    ):
        raise JournalConflictError("control journal recovery failed")
    return tuple(value)


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise JournalConflictError("control journal recovery failed")
    return value
