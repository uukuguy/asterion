"""Public-safe Pathlight projection for long-running control causality."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from asterion.control.authority import (
    AdmissionDecision,
    AuthorityEnvelope,
    BudgetUsage,
)
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.host import ControlEvent
from asterion.control.protocol import TERMINAL_CONTROL_EVENT_TYPES
from asterion.control.system import AgentSystemPlan
from asterion.pathlight.protocol import SafeAttributeValue, TraceEvent
from asterion.pathlight.recorder import PathlightRecorder


CONTROL_PATHLIGHT_GAP = "control-pathlight-recording"

_EVENT_KINDS = {
    "action.proposed": "action",
    "budget.reported": "session",
    "checkpoint.created": "checkpoint",
    "fault.raised": "fault",
    "goal.updated": "goal",
}
_SESSION_STATUSES = {
    "session.budget-limited": "budget_limited",
    "session.cancelled": "cancelled",
    "session.completed": "completed",
    "session.created": "created",
    "session.failed": "failed",
    "session.paused": "paused",
    "session.recovery-required": "recovery_required",
    "session.running": "running",
}


class ControlEvidenceProjector:
    """Project canonical control facts without retaining content-bearing values."""

    def __init__(self, recorder: PathlightRecorder) -> None:
        self._recorder = recorder
        self._trace_id: str | None = None
        self._system_span_id: str | None = None
        self._session_span_id: str | None = None
        self._gaps: set[str] = set()
        self._failed = False
        try:
            self._trace_id = recorder.trace_id
        except Exception:
            self._record_gap()

    @property
    def gaps(self) -> tuple[str, ...]:
        return tuple(sorted(self._gaps))

    def start_system(
        self,
        plan: AgentSystemPlan,
        *,
        session_id: str,
        generation: int,
        authority: AuthorityEnvelope,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        try:
            self._start_system(
                plan,
                session_id=session_id,
                generation=generation,
                authority=authority,
                journal_position=journal_position,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._record_gap()

    def _start_system(
        self,
        plan: AgentSystemPlan,
        *,
        session_id: str,
        generation: int,
        authority: AuthorityEnvelope,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        if self._disabled:
            return
        assert self._trace_id is not None
        self._system_span_id = _span_id(
            f"system:{plan.system_id}:{plan.version}:{session_id}"
        )
        self._session_span_id = _span_id(
            f"session:{plan.system_id}:{plan.version}:{session_id}:{generation}"
        )
        start = self._recorder.next_sequence
        self._record_many(
            (
                TraceEvent.start(
                    self._trace_id,
                    self._system_span_id,
                    None,
                    start,
                    "system",
                    attributes={"system_id": _digest(plan.system_id)},
                    timestamp_ns=timestamp_ns,
                ),
                TraceEvent.start(
                    self._trace_id,
                    self._session_span_id,
                    self._system_span_id,
                    start + 1,
                    "session",
                    attributes={
                        "session_id": _digest(session_id),
                        "authority_id": _digest(authority.authority_id),
                        "control_status": "created",
                        "generation": generation,
                        "authority_revision": authority.revision,
                        "journal_position": journal_position,
                    },
                    timestamp_ns=timestamp_ns,
                ),
            )
        )

    def project_event(
        self,
        event: ControlEvent,
        *,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        try:
            self._project_event(
                event,
                journal_position=journal_position,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._record_gap()

    def _project_event(
        self,
        event: ControlEvent,
        *,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        if self._disabled or self._session_span_id is None:
            return
        assert self._trace_id is not None
        kind = _event_kind(event.type)
        status = _event_status(event)
        attributes: dict[str, SafeAttributeValue] = {
            "session_id": _digest(event.session_id),
            "event_id": _digest(event.event_id),
            "control_event_sha256": _mapping_digest(event.to_mapping()),
            "control_event_type": event.type,
            "control_status": status,
            "generation": event.generation,
            "event_sequence": event.sequence,
            "journal_position": journal_position,
        }
        _add_event_payload_attributes(attributes, event)
        span_id = _span_id(
            f"event:{event.session_id}:{event.generation}:{event.event_id}"
        )
        start = self._recorder.next_sequence
        terminal_status = _terminal_trace_status(event.type)
        records: list[TraceEvent] = [
            TraceEvent.start(
                self._trace_id,
                span_id,
                self._session_span_id,
                start,
                kind,
                attributes=attributes,
                timestamp_ns=timestamp_ns,
            ),
            TraceEvent.terminal(
                self._trace_id,
                span_id,
                start + 1,
                terminal_status,
                kind=kind,
                timestamp_ns=timestamp_ns,
            ),
        ]
        if event.type in TERMINAL_CONTROL_EVENT_TYPES:
            assert self._system_span_id is not None
            records.extend(
                (
                    TraceEvent.terminal(
                        self._trace_id,
                        self._session_span_id,
                        start + 2,
                        terminal_status,
                        kind="session",
                        timestamp_ns=timestamp_ns,
                    ),
                    TraceEvent.terminal(
                        self._trace_id,
                        self._system_span_id,
                        start + 3,
                        terminal_status,
                        kind="system",
                        timestamp_ns=timestamp_ns,
                    ),
                )
            )
        self._record_many(records)

    def project_admission(
        self,
        decision: AdmissionDecision,
        *,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        try:
            self._project_admission(
                decision,
                journal_position=journal_position,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._record_gap()

    def _project_admission(
        self,
        decision: AdmissionDecision,
        *,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        if self._disabled or self._session_span_id is None:
            return
        assert self._trace_id is not None
        span_id = _span_id(
            "admission:"
            f"{decision.action_id}:{decision.proposal_digest}:{decision.status}"
        )
        start = self._recorder.next_sequence
        attributes: dict[str, SafeAttributeValue] = {
            "action_id": _digest(decision.action_id),
            "authority_id": _digest(decision.authority_id),
            "control_event_sha256": decision.proposal_digest,
            "control_event_type": f"action.{decision.status}",
            "control_reason_sha256": _digest(decision.reason),
            "control_status": decision.status,
            "authority_revision": decision.authority_revision,
            "journal_position": journal_position,
        }
        self._record_many(
            (
                TraceEvent.start(
                    self._trace_id,
                    span_id,
                    self._session_span_id,
                    start,
                    "admission",
                    attributes=attributes,
                    timestamp_ns=timestamp_ns,
                ),
                TraceEvent.complete(
                    self._trace_id,
                    span_id,
                    start + 1,
                    kind="admission",
                    timestamp_ns=timestamp_ns,
                ),
            )
        )

    def project_execution(
        self,
        *,
        action_id: str,
        status: str,
        reason_code: str,
        receipt_ref: str | None,
        receipt: ActionExecutionReceipt | None,
        usage: BudgetUsage,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        try:
            self._project_execution(
                action_id=action_id,
                status=status,
                reason_code=reason_code,
                receipt_ref=receipt_ref,
                receipt=receipt,
                usage=usage,
                journal_position=journal_position,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._record_gap()

    def project_action_running(
        self,
        *,
        action_id: str,
        status: str,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        try:
            self._project_fixed_action(
                action_id=action_id,
                status=status,
                reason_code="action-running",
                receipt_ref=None,
                usage=BudgetUsage.zero(),
                journal_position=journal_position,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._record_gap()

    def project_action_receipt(
        self,
        *,
        action_id: str,
        status: str,
        receipt: ActionExecutionReceipt,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        try:
            self._project_fixed_action(
                action_id=action_id,
                status=status,
                reason_code="action-receipt",
                receipt_ref=receipt.receipt_ref,
                usage=receipt.usage,
                journal_position=journal_position,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._record_gap()

    def project_provider_recovery(
        self,
        *,
        scenario_id: str,
        status: str,
        process_counts: Mapping[str, int],
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        try:
            self._project_provider_recovery(
                scenario_id=scenario_id,
                status=status,
                process_counts=process_counts,
                journal_position=journal_position,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._record_gap()

    def project_child_session(
        self,
        *,
        child_id: str,
        status: str,
        active_count: int,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        try:
            self._project_child_session(
                child_id=child_id,
                status=status,
                active_count=active_count,
                journal_position=journal_position,
                timestamp_ns=timestamp_ns,
            )
        except Exception:
            self._record_gap()

    def complete_provider_free_projection(self, *, timestamp_ns: int) -> None:
        try:
            self._complete_provider_free_projection(timestamp_ns=timestamp_ns)
        except Exception:
            self._record_gap()

    def _project_execution(
        self,
        *,
        action_id: str,
        status: str,
        reason_code: str,
        receipt_ref: str | None,
        receipt: ActionExecutionReceipt | None,
        usage: BudgetUsage,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        if self._disabled or self._session_span_id is None:
            return
        assert self._trace_id is not None
        artifact_ids = receipt.artifact_ids if receipt is not None else ()
        media_types = receipt.media_types if receipt is not None else ()
        attributes: dict[str, SafeAttributeValue] = {
            "action_id": _digest(action_id),
            "control_reason_sha256": _digest(reason_code),
            "control_status": status,
            "content_length": len(artifact_ids),
            "artifact_sha256": _digest("\n".join(artifact_ids)),
            "field_count": len(media_types),
            "scope_sha256": _digest("\n".join(media_types)),
            "input_tokens": usage.controller_tokens,
            "output_tokens": usage.application_tokens,
            "leaf_count": usage.child_tokens,
            "metric_value": usage.aggregate_tokens,
            "cost_microunits": usage.cost_micros,
            "journal_position": journal_position,
        }
        if receipt_ref is not None:
            attributes["evidence_ref"] = _digest(receipt_ref)
        span_id = _span_id(f"execution:{action_id}:{status}")
        start = self._recorder.next_sequence
        terminal = {
            "cancelled": "cancelled",
            "failed": "failed",
            "uncertain": "failed",
        }.get(status, "completed")
        self._record_many(
            (
                TraceEvent.start(
                    self._trace_id,
                    span_id,
                    self._session_span_id,
                    start,
                    "action",
                    attributes=attributes,
                    timestamp_ns=timestamp_ns,
                ),
                TraceEvent.terminal(
                    self._trace_id,
                    span_id,
                    start + 1,
                    terminal,
                    kind="action",
                    timestamp_ns=timestamp_ns,
                ),
            )
        )

    def _project_fixed_action(
        self,
        *,
        action_id: str,
        status: str,
        reason_code: str,
        receipt_ref: str | None,
        usage: BudgetUsage,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        if self._disabled:
            return
        assert self._trace_id is not None
        self._ensure_projection_root(timestamp_ns=timestamp_ns)
        attributes: dict[str, SafeAttributeValue] = {
            "action_id": _digest(action_id),
            "control_event_type": "action.admitted",
            "control_reason_sha256": _digest(reason_code),
            "control_status": _safe_control_status(status),
            "input_tokens": usage.controller_tokens,
            "output_tokens": usage.application_tokens,
            "leaf_count": usage.child_tokens,
            "metric_value": usage.aggregate_tokens,
            "cost_microunits": usage.cost_micros,
            "journal_position": journal_position,
        }
        if receipt_ref is not None:
            attributes["evidence_ref"] = _digest(receipt_ref)
        span_id = _span_id(f"fixed-action:{action_id}:{reason_code}:{status}")
        start = self._recorder.next_sequence
        terminal = {
            "cancelled": "cancelled",
            "failed": "failed",
            "uncertain": "failed",
        }.get(status, "completed")
        self._record_many(
            (
                TraceEvent.start(
                    self._trace_id,
                    span_id,
                    self._session_span_id,
                    start,
                    "action",
                    attributes=attributes,
                    timestamp_ns=timestamp_ns,
                ),
                TraceEvent.terminal(
                    self._trace_id,
                    span_id,
                    start + 1,
                    terminal,
                    kind="action",
                    timestamp_ns=timestamp_ns,
                ),
            )
        )

    def _project_provider_recovery(
        self,
        *,
        scenario_id: str,
        status: str,
        process_counts: Mapping[str, int],
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        if self._disabled:
            return
        assert self._trace_id is not None
        self._ensure_projection_root(timestamp_ns=timestamp_ns)
        counts = _safe_counts(process_counts)
        total = sum(counts.values())
        span_id = _span_id(f"provider-recovery:{scenario_id}:{status}:{total}")
        start = self._recorder.next_sequence
        self._record_many(
            (
                TraceEvent.start(
                    self._trace_id,
                    span_id,
                    self._session_span_id,
                    start,
                    "session",
                    attributes={
                        "session_id": _digest(scenario_id),
                        "control_event_type": "session.recovery-required",
                        "control_status": "recovery_required",
                        "control_reason_sha256": _digest(status),
                        "content_length": total,
                        "field_count": len(counts),
                        "journal_position": journal_position,
                    },
                    timestamp_ns=timestamp_ns,
                ),
                TraceEvent.complete(
                    self._trace_id,
                    span_id,
                    start + 1,
                    kind="session",
                    timestamp_ns=timestamp_ns,
                ),
            )
        )

    def _project_child_session(
        self,
        *,
        child_id: str,
        status: str,
        active_count: int,
        journal_position: int,
        timestamp_ns: int,
    ) -> None:
        if self._disabled:
            return
        if isinstance(active_count, bool) or not isinstance(active_count, int) or active_count < 0:
            raise ValueError("child session count is invalid")
        assert self._trace_id is not None
        self._ensure_projection_root(timestamp_ns=timestamp_ns)
        span_id = _span_id(f"child-session:{child_id}:{status}:{active_count}")
        start = self._recorder.next_sequence
        self._record_many(
            (
                TraceEvent.start(
                    self._trace_id,
                    span_id,
                    self._session_span_id,
                    start,
                    "session",
                    attributes={
                        "session_id": _digest(child_id),
                        "control_event_type": "session.running",
                        "control_status": _safe_control_status(status),
                        "leaf_count": active_count,
                        "journal_position": journal_position,
                    },
                    timestamp_ns=timestamp_ns,
                ),
                TraceEvent.complete(
                    self._trace_id,
                    span_id,
                    start + 1,
                    kind="session",
                    timestamp_ns=timestamp_ns,
                ),
            )
        )

    def _ensure_projection_root(self, *, timestamp_ns: int) -> None:
        if self._session_span_id is not None:
            return
        assert self._trace_id is not None
        self._session_span_id = _span_id(f"projection-root:{self._trace_id}")
        self._record_many(
            (
                TraceEvent.start(
                    self._trace_id,
                    self._session_span_id,
                    None,
                    self._recorder.next_sequence,
                    "session",
                    attributes={
                        "session_id": _digest(self._trace_id),
                        "control_event_type": "session.running",
                        "control_status": "running",
                        "journal_position": 0,
                    },
                    timestamp_ns=timestamp_ns,
                ),
            )
        )

    def _complete_provider_free_projection(self, *, timestamp_ns: int) -> None:
        if self._disabled or self._session_span_id is None:
            return
        assert self._trace_id is not None
        span_id = self._session_span_id
        self._record_many(
            (
                TraceEvent.complete(
                    self._trace_id,
                    span_id,
                    self._recorder.next_sequence,
                    kind="session",
                    timestamp_ns=timestamp_ns,
                ),
            )
        )
        self._session_span_id = None

    @property
    def _disabled(self) -> bool:
        return self._trace_id is None or self._failed

    def _record_many(self, events: Sequence[TraceEvent]) -> None:
        try:
            self._recorder.record_many(events)
        except Exception:
            self._record_gap()

    def _record_gap(self) -> None:
        self._failed = True
        self._gaps.add(CONTROL_PATHLIGHT_GAP)


def _event_kind(event_type: str) -> str:
    if event_type.startswith("session."):
        return "session"
    return _EVENT_KINDS[event_type]


def _event_status(event: ControlEvent) -> str:
    if event.type in _SESSION_STATUSES:
        return _SESSION_STATUSES[event.type]
    if event.type == "goal.updated":
        return str(event.payload["status"])
    if event.type == "action.proposed":
        return "proposed"
    if event.type == "fault.raised":
        return "failed"
    if event.type == "checkpoint.created":
        return "completed"
    return "running"


def _terminal_trace_status(event_type: str) -> str:
    if event_type == "session.cancelled":
        return "cancelled"
    if event_type in {"session.failed", "session.budget-limited"}:
        return "failed"
    return "completed"


def _add_event_payload_attributes(
    attributes: dict[str, SafeAttributeValue], event: ControlEvent
) -> None:
    payload = event.payload
    for field in ("goal_id", "action_id", "checkpoint_id", "authority_id"):
        value = payload.get(field)
        if isinstance(value, str):
            attributes[field] = _digest(value)
    revision = payload.get("authority_revision")
    if type(revision) is int:
        attributes["authority_revision"] = revision
    reason = payload.get("reason_code")
    if not isinstance(reason, str) and event.type == "fault.raised":
        reason = payload.get("code")
    if isinstance(reason, str):
        attributes["control_reason_sha256"] = _digest(reason)


def _mapping_digest(value: Mapping[str, object]) -> str:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return _digest(rendered)


def _safe_control_status(value: str) -> str:
    return {
        "active": "active",
        "admitted": "admitted",
        "budget_limited": "budget_limited",
        "cancelled": "cancelled",
        "completed": "completed",
        "created": "created",
        "failed": "failed",
        "needs_input": "needs_input",
        "paused": "paused",
        "proposed": "proposed",
        "recovery_required": "recovery_required",
        "rejected": "rejected",
        "running": "running",
        "succeeded": "succeeded",
        "uncertain": "uncertain",
    }.get(value, "uncertain")


def _safe_counts(value: Mapping[str, int]) -> Mapping[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError("process counts are invalid")
    counts: dict[str, int] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or key not in {"fake_daemon", "gateway"}
            or isinstance(item, bool)
            or not isinstance(item, int)
            or item < 0
        ):
            raise ValueError("process counts are invalid")
        counts[key] = item
    return {key: counts[key] for key in sorted(counts)}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _span_id(value: str) -> str:
    hexadecimal = list(_digest(value)[:32])
    hexadecimal[12] = "4"
    hexadecimal[16] = "8"
    raw = "".join(hexadecimal)
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
