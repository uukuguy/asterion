"""Host-owned authority admission and monotonic budget accounting."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from asterion.control.host import ControlEvent
from asterion.control.protocol import (
    ACTION_KINDS,
    IDENTIFIER,
    OPAQUE_ID,
    SEMANTIC_VERSION,
)
from asterion.control.session_context import (
    SESSION_CONTEXT_MODEL_OPERATIONS,
    SESSION_CONTEXT_OPERATIONS,
    SessionContextCommand,
)
from asterion.protocol_ordering import is_sorted_unique_scalar_strings


class AuthorityError(ValueError):
    """Raised when authority, admission or accounting is invalid."""


@dataclass(frozen=True, order=True)
class PortfolioGrant:
    provider_id: str
    application_id: str
    version: str
    runtime_id: str

    def __post_init__(self) -> None:
        if (
            any(
                IDENTIFIER.fullmatch(value) is None
                for value in (self.provider_id, self.application_id, self.runtime_id)
            )
            or SEMANTIC_VERSION.fullmatch(self.version) is None
        ):
            raise AuthorityError("authority portfolio grant is invalid")


@dataclass(frozen=True)
class BudgetLimit:
    controller_tokens: int
    application_tokens: int
    child_tokens: int
    aggregate_tokens: int
    cost_micros: int

    def __post_init__(self) -> None:
        _validate_budget_values(self, "authority budget limit")


@dataclass(frozen=True)
class BudgetUsage:
    controller_tokens: int
    application_tokens: int
    child_tokens: int
    aggregate_tokens: int
    cost_micros: int

    def __post_init__(self) -> None:
        _validate_budget_values(self, "authority budget usage")

    @classmethod
    def zero(cls) -> BudgetUsage:
        return cls(0, 0, 0, 0, 0)


@dataclass(frozen=True)
class BudgetRequest:
    controller_tokens: int
    application_tokens: int
    child_tokens: int
    aggregate_tokens: int
    cost_micros: int
    deadline_ms: int

    def __post_init__(self) -> None:
        _validate_budget_values(self, "action budget request")
        _require_positive_integer(self.deadline_ms, "action budget deadline")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> BudgetRequest:
        try:
            return cls(
                controller_tokens=_integer(value["controller_tokens"]),
                application_tokens=_integer(value["application_tokens"]),
                child_tokens=_integer(value["child_tokens"]),
                aggregate_tokens=_integer(value["aggregate_tokens"]),
                cost_micros=_integer(value["cost_micros"]),
                deadline_ms=_integer(value["deadline_ms"]),
            )
        except (KeyError, TypeError, ValueError):
            raise AuthorityError("action budget request is invalid") from None

    def as_usage(self) -> BudgetUsage:
        return BudgetUsage(
            controller_tokens=self.controller_tokens,
            application_tokens=self.application_tokens,
            child_tokens=self.child_tokens,
            aggregate_tokens=self.aggregate_tokens,
            cost_micros=self.cost_micros,
        )


@dataclass(frozen=True)
class RemainingBudget:
    """Current host-authoritative capacity, including a possibly zero deadline."""

    controller_tokens: int
    application_tokens: int
    child_tokens: int
    aggregate_tokens: int
    cost_micros: int
    deadline_ms: int

    def __post_init__(self) -> None:
        _validate_budget_values(self, "remaining budget")
        _require_nonnegative_integer(self.deadline_ms, "remaining budget deadline")


@dataclass(frozen=True)
class AuthorityEnvelope:
    authority_id: str
    revision: int
    allowed_portfolio: tuple[PortfolioGrant, ...]
    allowed_operations: tuple[str, ...]
    budget_limit: BudgetLimit
    expires_at_ms: int
    max_action_deadline_ms: int
    max_recursion_depth: int
    max_concurrent_children: int
    execution_domain: str
    host_service_grants: tuple[str, ...]
    cancelled: bool = False

    def __post_init__(self) -> None:
        if OPAQUE_ID.fullmatch(self.authority_id) is None:
            raise AuthorityError("authority identity is invalid")
        _require_positive_integer(self.revision, "authority revision")
        if not isinstance(self.budget_limit, BudgetLimit):
            raise AuthorityError("authority budget limit is invalid")
        portfolio = tuple(self.allowed_portfolio)
        if (
            not portfolio
            or any(not isinstance(grant, PortfolioGrant) for grant in portfolio)
            or portfolio != tuple(sorted(set(portfolio)))
        ):
            raise AuthorityError("authority portfolio is invalid")
        operations = tuple(self.allowed_operations)
        if any(
            operation not in ACTION_KINDS | SESSION_CONTEXT_OPERATIONS
            for operation in operations
        ) or not is_sorted_unique_scalar_strings(list(operations)):
            raise AuthorityError("authority operations are invalid")
        grants = tuple(self.host_service_grants)
        if any(
            not isinstance(grant, str) or IDENTIFIER.fullmatch(grant) is None
            for grant in grants
        ) or not is_sorted_unique_scalar_strings(list(grants)):
            raise AuthorityError("authority host-service grants are invalid")
        _require_positive_integer(self.expires_at_ms, "authority expiry")
        _require_positive_integer(
            self.max_action_deadline_ms, "authority action deadline"
        )
        _require_nonnegative_integer(
            self.max_recursion_depth, "authority recursion depth"
        )
        _require_nonnegative_integer(
            self.max_concurrent_children, "authority concurrent children"
        )
        if self.execution_domain not in {"trusted-local", "restricted"}:
            raise AuthorityError("authority execution domain is invalid")
        if not isinstance(self.cancelled, bool):
            raise AuthorityError("authority cancellation state is invalid")
        object.__setattr__(self, "allowed_portfolio", portfolio)
        object.__setattr__(self, "allowed_operations", operations)
        object.__setattr__(self, "host_service_grants", grants)


@dataclass(frozen=True)
class AdmissionDecision:
    action_id: str
    authority_id: str
    authority_revision: int
    proposal_digest: str
    status: str
    reason: str
    reservation: BudgetRequest | None

    def __post_init__(self) -> None:
        if (
            OPAQUE_ID.fullmatch(self.action_id) is None
            or OPAQUE_ID.fullmatch(self.authority_id) is None
            or self.status not in {"admitted", "rejected"}
            or IDENTIFIER.fullmatch(self.reason) is None
            or len(self.proposal_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.proposal_digest
            )
            or (self.status == "admitted")
            != isinstance(self.reservation, BudgetRequest)
        ):
            raise AuthorityError("admission decision is invalid")
        _require_positive_integer(self.authority_revision, "admission revision")


@dataclass(frozen=True)
class ActionReceipt:
    action_id: str
    receipt_ref: str
    usage: BudgetUsage

    def __post_init__(self) -> None:
        if (
            OPAQUE_ID.fullmatch(self.action_id) is None
            or OPAQUE_ID.fullmatch(self.receipt_ref) is None
            or not isinstance(self.usage, BudgetUsage)
        ):
            raise AuthorityError("action receipt is invalid")


@dataclass(frozen=True)
class ProviderUsageReport:
    """Cumulative provider usage; it is not added to action receipts."""

    usage: BudgetUsage

    def __post_init__(self) -> None:
        if (
            not isinstance(self.usage, BudgetUsage)
            or self.usage.aggregate_tokens
            < self.usage.controller_tokens
            + self.usage.application_tokens
            + self.usage.child_tokens
        ):
            raise AuthorityError("provider usage report is invalid")


@dataclass(frozen=True)
class SessionContextDecision:
    """Host authority decision for one exact session-context command."""

    command_id: str
    idempotency_key: str
    authority_id: str
    authority_revision: int
    operation: str
    command_digest: str
    status: str
    reason: str
    reservation: BudgetRequest | None

    def __post_init__(self) -> None:
        admitted = self.status == "admitted"
        requires_budget = self.operation in SESSION_CONTEXT_MODEL_OPERATIONS
        if (
            OPAQUE_ID.fullmatch(self.command_id) is None
            or OPAQUE_ID.fullmatch(self.idempotency_key) is None
            or OPAQUE_ID.fullmatch(self.authority_id) is None
            or self.operation not in SESSION_CONTEXT_OPERATIONS
            or self.status not in {"admitted", "rejected"}
            or IDENTIFIER.fullmatch(self.reason) is None
            or len(self.command_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.command_digest
            )
            or (not admitted and self.reservation is not None)
            or (
                admitted
                and requires_budget
                and not isinstance(self.reservation, BudgetRequest)
            )
            or (admitted and not requires_budget and self.reservation is not None)
        ):
            raise AuthorityError("session context decision is invalid")
        _require_positive_integer(
            self.authority_revision, "session context authority revision"
        )


@dataclass(frozen=True)
class SessionContextSettlement:
    """Safe usage settlement for one definitive session-context receipt."""

    command_id: str
    receipt_id: str
    usage: BudgetUsage

    def __post_init__(self) -> None:
        if (
            OPAQUE_ID.fullmatch(self.command_id) is None
            or OPAQUE_ID.fullmatch(self.receipt_id) is None
            or not isinstance(self.usage, BudgetUsage)
        ):
            raise AuthorityError("session context settlement is invalid")


class AuthorityLedger:
    """Evaluate without mutation, then reserve and settle exactly once."""

    def __init__(self, envelope: AuthorityEnvelope) -> None:
        if not isinstance(envelope, AuthorityEnvelope):
            raise AuthorityError("authority envelope is invalid")
        self._envelope = envelope
        self._usage = BudgetUsage.zero()
        self._reported_usage = BudgetUsage.zero()
        self._reservations: dict[str, AdmissionDecision] = {}
        self._receipts: dict[str, ActionReceipt] = {}
        self._context_reservations: dict[str, SessionContextDecision] = {}
        self._context_settlements: dict[str, SessionContextSettlement] = {}
        self._frozen = False

    @property
    def envelope(self) -> AuthorityEnvelope:
        return self._envelope

    @property
    def usage(self) -> BudgetUsage:
        return _effective_usage(self._reported_usage, self._usage)

    @property
    def reported_usage(self) -> BudgetUsage:
        return self._reported_usage

    @property
    def reserved_action_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._reservations))

    @property
    def reservations(self) -> Mapping[str, AdmissionDecision]:
        return MappingProxyType(dict(self._reservations))

    @property
    def receipts(self) -> Mapping[str, ActionReceipt]:
        return MappingProxyType(dict(self._receipts))

    @property
    def reserved_session_context_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._context_reservations))

    @property
    def session_context_reservations(
        self,
    ) -> Mapping[str, SessionContextDecision]:
        return MappingProxyType(dict(self._context_reservations))

    @property
    def session_context_settlements(
        self,
    ) -> Mapping[str, SessionContextSettlement]:
        return MappingProxyType(dict(self._context_settlements))

    def remaining_budget(self, *, now_ms: int) -> RemainingBudget:
        """Return the exact conservative capacity after usage and reservations."""

        _require_nonnegative_integer(now_ms, "remaining budget time")
        envelope = self._envelope
        if envelope.cancelled or now_ms >= envelope.expires_at_ms:
            return RemainingBudget(0, 0, 0, 0, 0, 0)
        committed = _add_usage(self.usage, self._reserved_usage())
        limit = envelope.budget_limit
        return RemainingBudget(
            controller_tokens=max(0, limit.controller_tokens - committed.controller_tokens),
            application_tokens=max(
                0, limit.application_tokens - committed.application_tokens
            ),
            child_tokens=max(0, limit.child_tokens - committed.child_tokens),
            aggregate_tokens=max(0, limit.aggregate_tokens - committed.aggregate_tokens),
            cost_micros=max(0, limit.cost_micros - committed.cost_micros),
            deadline_ms=max(
                0,
                min(
                    envelope.max_action_deadline_ms,
                    envelope.expires_at_ms - now_ms,
                ),
            ),
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, AuthorityLedger)
            and self._envelope == other._envelope
            and self._usage == other._usage
            and self._reported_usage == other._reported_usage
            and self._reservations == other._reservations
            and self._receipts == other._receipts
            and self._context_reservations == other._context_reservations
            and self._context_settlements == other._context_settlements
        )

    @classmethod
    def _from_recovery(
        cls,
        envelope: AuthorityEnvelope,
        operations: Sequence[
            AdmissionDecision
            | ActionReceipt
            | ProviderUsageReport
            | SessionContextDecision
            | SessionContextSettlement
        ],
    ) -> AuthorityLedger:
        """Build a frozen ledger from an already validated ordered journal."""

        ledger = cls(envelope)
        for operation in operations:
            if isinstance(operation, ProviderUsageReport):
                ledger.record_provider_usage(operation)
                continue
            if isinstance(operation, SessionContextSettlement):
                ledger.settle_session_context(operation.command_id, operation)
                continue
            if isinstance(operation, SessionContextDecision):
                if (
                    operation.status != "admitted"
                    or operation.authority_id != envelope.authority_id
                    or operation.authority_revision > envelope.revision
                    or operation.operation not in envelope.allowed_operations
                    or operation.reason != "authorized"
                    or operation.command_id in ledger._context_reservations
                    or operation.command_id in ledger._context_settlements
                ):
                    raise AuthorityError(
                        "recovered session context reservation is invalid"
                    )
                requested = (
                    BudgetUsage.zero()
                    if operation.reservation is None
                    else operation.reservation.as_usage()
                )
                if not _fits(
                    _add_usage(ledger.usage, ledger._reserved_usage(), requested),
                    envelope.budget_limit,
                ):
                    raise AuthorityError(
                        "recovered session context budget is unavailable"
                    )
                ledger._context_reservations[operation.command_id] = operation
                continue
            if isinstance(operation, ActionReceipt):
                ledger.settle(operation.action_id, operation)
                continue
            decision = operation
            if (
                not isinstance(decision, AdmissionDecision)
                or decision.status != "admitted"
                or decision.authority_id != envelope.authority_id
                or decision.authority_revision > envelope.revision
                or decision.reservation is None
                or decision.action_id in ledger._reservations
                or decision.action_id in ledger._receipts
            ):
                raise AuthorityError("recovered admission reservation is invalid")
            effective = _add_usage(
                ledger.usage,
                ledger._reserved_usage(),
                decision.reservation.as_usage(),
            )
            if not _fits(effective, envelope.budget_limit):
                raise AuthorityError("recovered admission budget is unavailable")
            ledger._reservations[decision.action_id] = decision
        ledger._frozen = True
        return ledger

    def _mutable_copy(self) -> AuthorityLedger:
        """Return an owned mutable copy of this ledger's validated state."""

        ledger = AuthorityLedger(self._envelope)
        ledger._usage = self._usage
        ledger._reported_usage = self._reported_usage
        ledger._reservations = dict(self._reservations)
        ledger._receipts = dict(self._receipts)
        ledger._context_reservations = dict(self._context_reservations)
        ledger._context_settlements = dict(self._context_settlements)
        return ledger

    def evaluate_session_context(
        self,
        command: SessionContextCommand,
        *,
        now_ms: int,
    ) -> SessionContextDecision:
        """Evaluate one closed session-context command without mutation."""

        if not isinstance(command, SessionContextCommand):
            raise AuthorityError("session context command is invalid")
        _require_nonnegative_integer(now_ms, "session context evaluation time")
        digest = session_context_command_digest(command)
        if self._envelope.cancelled:
            return self._context_rejected(command, digest, "authority-cancelled")
        if command.authority_revision != self._envelope.revision:
            return self._context_rejected(
                command, digest, "authority-revision-mismatch"
            )
        if now_ms >= self._envelope.expires_at_ms:
            return self._context_rejected(command, digest, "authority-expired")
        if command.operation not in self._envelope.allowed_operations:
            return self._context_rejected(
                command, digest, "operation-not-authorized"
            )
        reservation = None
        if command.operation in SESSION_CONTEXT_MODEL_OPERATIONS:
            budget = command.payload.get("budget")
            if not isinstance(budget, Mapping):
                raise AuthorityError("session context budget is invalid")
            reservation = BudgetRequest.from_mapping(budget)
            if (
                reservation.deadline_ms > self._envelope.max_action_deadline_ms
                or now_ms + reservation.deadline_ms
                > self._envelope.expires_at_ms
            ):
                return self._context_rejected(
                    command, digest, "deadline-not-authorized"
                )
            effective = _add_usage(
                self.usage,
                self._reserved_usage(),
                reservation.as_usage(),
            )
            if not _fits(effective, self._envelope.budget_limit):
                return self._context_rejected(command, digest, "budget-exceeded")
        return SessionContextDecision(
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            authority_id=self._envelope.authority_id,
            authority_revision=self._envelope.revision,
            operation=command.operation,
            command_digest=digest,
            status="admitted",
            reason="authorized",
            reservation=reservation,
        )

    def reject_session_context(
        self,
        command: SessionContextCommand,
        *,
        reason: str,
    ) -> SessionContextDecision:
        """Create a closed host rejection bound to the current authority."""

        if not isinstance(command, SessionContextCommand):
            raise AuthorityError("session context command is invalid")
        return self._context_rejected(
            command,
            session_context_command_digest(command),
            reason,
        )

    def reserve_session_context(self, decision: SessionContextDecision) -> None:
        self._ensure_mutable()
        if (
            not isinstance(decision, SessionContextDecision)
            or decision.status != "admitted"
        ):
            raise AuthorityError("session context reservation is invalid")
        existing = self._context_reservations.get(decision.command_id)
        if existing is not None:
            if existing != decision:
                raise AuthorityError("session context reservation conflicts")
            return
        if decision.command_id in self._context_settlements:
            raise AuthorityError("session context command is already settled")
        if (
            decision.authority_id != self._envelope.authority_id
            or decision.authority_revision != self._envelope.revision
        ):
            raise AuthorityError("session context authority revision is stale")
        requested = (
            BudgetUsage.zero()
            if decision.reservation is None
            else decision.reservation.as_usage()
        )
        if not _fits(
            _add_usage(self.usage, self._reserved_usage(), requested),
            self._envelope.budget_limit,
        ):
            raise AuthorityError("session context budget is no longer available")
        self._context_reservations[decision.command_id] = decision

    def preview_session_context_settlement(
        self,
        command_id: str,
        settlement: SessionContextSettlement,
    ) -> None:
        preview = self._mutable_copy()
        preview.settle_session_context(command_id, settlement)

    def settle_session_context(
        self,
        command_id: str,
        settlement: SessionContextSettlement,
    ) -> None:
        self._ensure_mutable()
        if (
            not isinstance(settlement, SessionContextSettlement)
            or settlement.command_id != command_id
        ):
            raise AuthorityError("session context settlement is invalid")
        existing = self._context_settlements.get(command_id)
        if existing is not None:
            if existing != settlement:
                raise AuthorityError("session context settlement conflicts")
            return
        decision = self._context_reservations.get(command_id)
        if decision is None:
            raise AuthorityError("session context reservation is unavailable")
        limit = (
            BudgetUsage.zero()
            if decision.reservation is None
            else decision.reservation.as_usage()
        )
        if not _fits(settlement.usage, limit):
            raise AuthorityError("session context receipt exceeds reservation")
        candidate = _add_usage(self._usage, settlement.usage)
        if not _fits(
            _effective_usage(self._reported_usage, candidate),
            self._envelope.budget_limit,
        ):
            raise AuthorityError("session context settlement exceeds authority")
        self._usage = candidate
        del self._context_reservations[command_id]
        self._context_settlements[command_id] = settlement

    def evaluate(
        self,
        proposal: ControlEvent,
        *,
        now_ms: int,
        recursion_depth: int = 0,
        active_children: int = 0,
        requested_host_services: Sequence[str] = (),
    ) -> AdmissionDecision:
        if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
            raise AuthorityError("authority proposal is invalid")
        _require_nonnegative_integer(now_ms, "authority evaluation time")
        _require_nonnegative_integer(recursion_depth, "proposal recursion depth")
        _require_nonnegative_integer(active_children, "proposal active children")
        services = tuple(requested_host_services)
        if any(
            not isinstance(service, str) or IDENTIFIER.fullmatch(service) is None
            for service in services
        ) or not is_sorted_unique_scalar_strings(list(services)):
            raise AuthorityError("proposal host services are invalid")
        payload = proposal.payload
        action_id = str(payload["action_id"])
        digest = action_proposal_digest(proposal)
        revision = payload["authority_revision"]
        if self._envelope.cancelled:
            return self._rejected(action_id, digest, "authority-cancelled")
        if revision != self._envelope.revision:
            return self._rejected(action_id, digest, "authority-revision-mismatch")
        if now_ms >= self._envelope.expires_at_ms:
            return self._rejected(action_id, digest, "authority-expired")
        operation = str(payload["kind"])
        if operation not in self._envelope.allowed_operations:
            return self._rejected(action_id, digest, "operation-not-authorized")
        if operation == "application.invoke" and not self._target_is_authorized(
            payload["target"]
        ):
            return self._rejected(action_id, digest, "target-not-authorized")
        if not set(services).issubset(self._envelope.host_service_grants):
            return self._rejected(action_id, digest, "host-service-not-authorized")
        if operation == "child.spawn":
            if (
                self._envelope.max_recursion_depth == 0
                or recursion_depth > self._envelope.max_recursion_depth
            ):
                return self._rejected(action_id, digest, "recursion-depth-exceeded")
            if active_children >= self._envelope.max_concurrent_children:
                return self._rejected(action_id, digest, "child-concurrency-exceeded")
        raw_budget = payload["budget"]
        if not isinstance(raw_budget, Mapping):
            raise AuthorityError("action budget request is invalid")
        request = BudgetRequest.from_mapping(raw_budget)
        if (
            request.deadline_ms > self._envelope.max_action_deadline_ms
            or now_ms + request.deadline_ms > self._envelope.expires_at_ms
        ):
            return self._rejected(action_id, digest, "deadline-not-authorized")
        effective = _add_usage(self.usage, self._reserved_usage(), request.as_usage())
        if not _fits(effective, self._envelope.budget_limit):
            return self._rejected(action_id, digest, "budget-exceeded")
        return AdmissionDecision(
            action_id=action_id,
            authority_id=self._envelope.authority_id,
            authority_revision=self._envelope.revision,
            proposal_digest=digest,
            status="admitted",
            reason="authorized",
            reservation=request,
        )

    def reserve(self, decision: AdmissionDecision) -> None:
        self._ensure_mutable()
        if not isinstance(decision, AdmissionDecision) or decision.status != "admitted":
            raise AuthorityError("admission reservation is invalid")
        existing = self._reservations.get(decision.action_id)
        if existing is not None:
            if existing != decision:
                raise AuthorityError("admission reservation conflicts")
            return
        if decision.action_id in self._receipts:
            raise AuthorityError("admission action is already settled")
        if (
            decision.authority_id != self._envelope.authority_id
            or decision.authority_revision != self._envelope.revision
            or decision.reservation is None
        ):
            raise AuthorityError("admission authority revision is stale")
        effective = _add_usage(
            self.usage,
            self._reserved_usage(),
            decision.reservation.as_usage(),
        )
        if not _fits(effective, self._envelope.budget_limit):
            raise AuthorityError("admission budget is no longer available")
        self._reservations[decision.action_id] = decision

    def settle(self, action_id: str, receipt: ActionReceipt) -> None:
        self._ensure_mutable()
        if not isinstance(receipt, ActionReceipt) or receipt.action_id != action_id:
            raise AuthorityError("action settlement receipt is invalid")
        existing = self._receipts.get(action_id)
        if existing is not None:
            if existing != receipt:
                raise AuthorityError("action settlement conflicts")
            return
        decision = self._reservations.get(action_id)
        if decision is None or decision.reservation is None:
            raise AuthorityError("action reservation is unavailable")
        if not _fits(receipt.usage, decision.reservation.as_usage()):
            raise AuthorityError("action receipt exceeds reservation")
        candidate = _add_usage(self._usage, receipt.usage)
        if not _fits(
            _effective_usage(self._reported_usage, candidate),
            self._envelope.budget_limit,
        ):
            raise AuthorityError("action settlement exceeds authority")
        self._usage = candidate
        del self._reservations[action_id]
        self._receipts[action_id] = receipt

    def preview_provider_usage(self, report: ProviderUsageReport) -> None:
        if not isinstance(report, ProviderUsageReport):
            raise AuthorityError("provider usage report is invalid")
        if not _monotonic(self._reported_usage, report.usage):
            raise AuthorityError("provider usage is not monotonic")
        effective = _effective_usage(report.usage, self._usage)
        if not _fits(_add_usage(effective, self._reserved_usage()), self._envelope.budget_limit):
            raise AuthorityError("provider usage exceeds authority")

    def record_provider_usage(self, report: ProviderUsageReport) -> None:
        self._ensure_mutable()
        self.preview_provider_usage(report)
        self._reported_usage = report.usage

    def preview_settlement(self, action_id: str, receipt: ActionReceipt) -> None:
        """Validate an exact settlement without mutating the live ledger."""

        preview = self._mutable_copy()
        preview.settle(action_id, receipt)

    def replace_authority(self, envelope: AuthorityEnvelope) -> None:
        self._ensure_mutable()
        if (
            not isinstance(envelope, AuthorityEnvelope)
            or envelope.authority_id != self._envelope.authority_id
            or envelope.revision <= self._envelope.revision
        ):
            raise AuthorityError("authority replacement is invalid")
        committed = _add_usage(self.usage, self._reserved_usage())
        if not _fits(committed, envelope.budget_limit):
            raise AuthorityError("authority replacement budget is insufficient")
        self._envelope = envelope

    def _ensure_mutable(self) -> None:
        if self._frozen:
            raise AuthorityError("recovered authority ledger is immutable")

    def _target_is_authorized(self, target: object) -> bool:
        if not isinstance(target, Mapping) or target.get("kind") != "application":
            return False
        try:
            grant = PortfolioGrant(
                provider_id=str(target["provider_id"]),
                application_id=str(target["application_id"]),
                version=str(target["version"]),
                runtime_id=str(target["runtime_id"]),
            )
        except (KeyError, TypeError, ValueError):
            return False
        return grant in self._envelope.allowed_portfolio

    def _reserved_usage(self) -> BudgetUsage:
        usage = BudgetUsage.zero()
        for decision in self._reservations.values():
            assert decision.reservation is not None
            usage = _add_usage(usage, decision.reservation.as_usage())
        for decision in self._context_reservations.values():
            if decision.reservation is not None:
                usage = _add_usage(usage, decision.reservation.as_usage())
        return usage

    def _context_rejected(
        self,
        command: SessionContextCommand,
        command_digest: str,
        reason: str,
    ) -> SessionContextDecision:
        return SessionContextDecision(
            command_id=command.command_id,
            idempotency_key=command.idempotency_key,
            authority_id=self._envelope.authority_id,
            authority_revision=self._envelope.revision,
            operation=command.operation,
            command_digest=command_digest,
            status="rejected",
            reason=reason,
            reservation=None,
        )

    def _rejected(
        self, action_id: str, proposal_digest: str, reason: str
    ) -> AdmissionDecision:
        return AdmissionDecision(
            action_id=action_id,
            authority_id=self._envelope.authority_id,
            authority_revision=self._envelope.revision,
            proposal_digest=proposal_digest,
            status="rejected",
            reason=reason,
            reservation=None,
        )


def action_proposal_digest(proposal: ControlEvent) -> str:
    """Return the canonical public digest used to bind an admission decision."""

    if not isinstance(proposal, ControlEvent) or proposal.type != "action.proposed":
        raise AuthorityError("authority proposal is invalid")
    encoded = json.dumps(
        proposal.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def session_context_command_digest(command: SessionContextCommand) -> str:
    """Return the canonical public digest binding one context decision."""

    if not isinstance(command, SessionContextCommand):
        raise AuthorityError("session context command is invalid")
    encoded = json.dumps(
        command.to_mapping(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_budget_values(value: object, label: str) -> None:
    for field in (
        "controller_tokens",
        "application_tokens",
        "child_tokens",
        "aggregate_tokens",
        "cost_micros",
    ):
        _require_nonnegative_integer(getattr(value, field, None), f"{label} {field}")


def _add_usage(*values: BudgetUsage) -> BudgetUsage:
    return BudgetUsage(
        controller_tokens=sum(value.controller_tokens for value in values),
        application_tokens=sum(value.application_tokens for value in values),
        child_tokens=sum(value.child_tokens for value in values),
        aggregate_tokens=sum(value.aggregate_tokens for value in values),
        cost_micros=sum(value.cost_micros for value in values),
    )


def _monotonic(previous: BudgetUsage, current: BudgetUsage) -> bool:
    return all(
        getattr(current, field) >= getattr(previous, field)
        for field in (
            "controller_tokens", "application_tokens", "child_tokens",
            "aggregate_tokens", "cost_micros",
        )
    )


def _effective_usage(reported: BudgetUsage, settled: BudgetUsage) -> BudgetUsage:
    controller = max(reported.controller_tokens, settled.controller_tokens)
    application = max(reported.application_tokens, settled.application_tokens)
    child = max(reported.child_tokens, settled.child_tokens)
    return BudgetUsage(
        controller_tokens=controller,
        application_tokens=application,
        child_tokens=child,
        aggregate_tokens=max(
            reported.aggregate_tokens,
            settled.aggregate_tokens,
            controller + application + child,
        ),
        cost_micros=max(reported.cost_micros, settled.cost_micros),
    )


def _fits(value: BudgetUsage, limit: BudgetLimit | BudgetUsage) -> bool:
    return all(
        getattr(value, field) <= getattr(limit, field)
        for field in (
            "controller_tokens",
            "application_tokens",
            "child_tokens",
            "aggregate_tokens",
            "cost_micros",
        )
    )


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("integer is invalid")
    return value


def _require_nonnegative_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AuthorityError(f"{label} is invalid")


def _require_positive_integer(value: object, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise AuthorityError(f"{label} is invalid")
