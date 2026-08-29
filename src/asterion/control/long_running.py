"""Provider-neutral scheduling state for bounded long-running operations."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol

from asterion.control.journal import (
    CanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalRecord,
)
from asterion.control.protocol import OPAQUE_ID


class LongRunningError(ValueError):
    """Raised when long-running state or an effect conflicts."""


class LongRunningTransportError(RuntimeError):
    """Marks transport loss after a durable effect intent exists."""


class CancellationSignal(Protocol):
    @property
    def cancelled(self) -> bool:
        """Return whether future long-running effects must stop."""
        ...


class LongRunningProcessObserver(Protocol):
    def owned_process_ids(self) -> tuple[str, ...]:
        """Return exact host-owned process identities."""
        ...

    def evict_controller(self, controller_id: str) -> None:
        """Release processes owned by one resident controller."""
        ...


@dataclass(frozen=True)
class HeartbeatSpec:
    heartbeat_id: str
    owner_kind: Literal["user", "agent"]
    owner_id: str | None
    interval_ms: int

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.heartbeat_id)
            or self.owner_kind not in {"user", "agent"}
            or isinstance(self.interval_ms, bool)
            or not isinstance(self.interval_ms, int)
            or self.interval_ms < 1
            or (self.owner_kind == "user" and self.owner_id is not None)
            or (self.owner_kind == "agent" and not _valid_id(self.owner_id))
        ):
            raise LongRunningError("heartbeat specification is invalid")

    @property
    def owner_key(self) -> str:
        return "user" if self.owner_kind == "user" else f"agent:{self.owner_id}"

    def to_mapping(self) -> Mapping[str, object]:
        return {
            "interval_ms": self.interval_ms,
            "owner_id": self.owner_id,
            "owner_kind": self.owner_kind,
            "source_id": self.heartbeat_id,
            "spec_type": "heartbeat",
        }


@dataclass(frozen=True)
class ScheduleSpec:
    schedule_id: str
    kind: Literal["once", "cron"]
    due_at_ms: int | None
    cron_expression: str | None

    def __post_init__(self) -> None:
        if not _valid_id(self.schedule_id):
            raise LongRunningError("schedule specification is invalid")
        if self.kind == "once":
            valid = (
                not isinstance(self.due_at_ms, bool)
                and isinstance(self.due_at_ms, int)
                and self.due_at_ms >= 0
                and self.cron_expression is None
            )
        elif self.kind == "cron":
            valid = self.due_at_ms is None and _valid_cron(self.cron_expression)
        else:
            valid = False
        if not valid:
            raise LongRunningError("schedule specification is invalid")

    @classmethod
    def once(cls, schedule_id: str, due_at_ms: int) -> ScheduleSpec:
        return cls(schedule_id, "once", due_at_ms, None)

    @classmethod
    def cron(cls, schedule_id: str, expression: str) -> ScheduleSpec:
        return cls(schedule_id, "cron", None, expression)

    def to_mapping(self) -> Mapping[str, object]:
        return {
            "cron_expression": self.cron_expression,
            "due_at_ms": self.due_at_ms,
            "schedule_kind": self.kind,
            "source_id": self.schedule_id,
            "spec_type": "schedule",
        }


@dataclass(frozen=True)
class LongRunningIntent:
    effect_id: str
    source_id: str
    source_kind: Literal["heartbeat", "schedule"]
    due_at_ms: int

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.effect_id)
            or not _valid_id(self.source_id)
            or self.source_kind not in {"heartbeat", "schedule"}
            or isinstance(self.due_at_ms, bool)
            or not isinstance(self.due_at_ms, int)
            or self.due_at_ms < 0
        ):
            raise LongRunningError("long-running intent is invalid")

    def to_mapping(self) -> Mapping[str, object]:
        return {
            "due_at_ms": self.due_at_ms,
            "effect_id": self.effect_id,
            "source_id": self.source_id,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True)
class LongRunningReceipt:
    effect_id: str
    source_id: str
    source_kind: Literal["heartbeat", "schedule"]
    due_at_ms: int
    status: Literal["succeeded", "failed", "cancelled", "uncertain"]

    def __post_init__(self) -> None:
        try:
            LongRunningIntent(
                self.effect_id,
                self.source_id,
                self.source_kind,
                self.due_at_ms,
            )
        except LongRunningError:
            raise LongRunningError("long-running receipt is invalid") from None
        if self.status not in {"succeeded", "failed", "cancelled", "uncertain"}:
            raise LongRunningError("long-running receipt is invalid")

    @classmethod
    def succeeded(cls, intent: LongRunningIntent) -> LongRunningReceipt:
        return cls._from_intent(intent, "succeeded")

    @classmethod
    def uncertain(cls, intent: LongRunningIntent) -> LongRunningReceipt:
        return cls._from_intent(intent, "uncertain")

    @classmethod
    def cancelled(cls, intent: LongRunningIntent) -> LongRunningReceipt:
        return cls._from_intent(intent, "cancelled")

    @classmethod
    def _from_intent(
        cls,
        intent: LongRunningIntent,
        status: Literal["succeeded", "failed", "cancelled", "uncertain"],
    ) -> LongRunningReceipt:
        if not isinstance(intent, LongRunningIntent):
            raise LongRunningError("long-running receipt is invalid")
        return cls(
            intent.effect_id,
            intent.source_id,
            intent.source_kind,
            intent.due_at_ms,
            status,
        )

    def to_mapping(self) -> Mapping[str, object]:
        return {
            **LongRunningIntent(
                self.effect_id,
                self.source_id,
                self.source_kind,
                self.due_at_ms,
            ).to_mapping(),
            "status": self.status,
        }


@dataclass(frozen=True)
class LongRunningSnapshot:
    heartbeat_ids: tuple[str, ...]
    schedule_ids: tuple[str, ...]
    history: tuple[LongRunningReceipt, ...]
    closed: bool
    resident_leases: tuple[ResidentLease, ...] = ()
    task_authorities: tuple[TaskAuthority, ...] = ()
    attached_controller_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResidentLease:
    controller_id: str
    acquired_at_ms: int
    expires_at_ms: int

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.controller_id)
            or not _valid_time(self.acquired_at_ms)
            or not _valid_time(self.expires_at_ms)
            or self.expires_at_ms <= self.acquired_at_ms
        ):
            raise LongRunningError("resident lease is invalid")

    def to_mapping(self) -> Mapping[str, object]:
        return {
            "controller_id": self.controller_id,
            "acquired_at_ms": self.acquired_at_ms,
            "expires_at_ms": self.expires_at_ms,
        }


@dataclass(frozen=True)
class TaskAuthority:
    task_id: str
    started_at_ms: int
    expires_at_ms: int

    def __post_init__(self) -> None:
        if (
            not _valid_id(self.task_id)
            or not _valid_time(self.started_at_ms)
            or not _valid_time(self.expires_at_ms)
            or self.expires_at_ms <= self.started_at_ms
        ):
            raise LongRunningError("task authority is invalid")

    def to_mapping(self) -> Mapping[str, object]:
        return {
            "task_id": self.task_id,
            "started_at_ms": self.started_at_ms,
            "expires_at_ms": self.expires_at_ms,
        }


@dataclass(frozen=True)
class OrphanAudit:
    owned_process_count: int
    process_ids_digest: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.owned_process_count, bool)
            or not isinstance(self.owned_process_count, int)
            or self.owned_process_count < 0
            or len(self.process_ids_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.process_ids_digest
            )
        ):
            raise LongRunningError("orphan audit is invalid")


class _NoProcesses:
    def owned_process_ids(self) -> tuple[str, ...]:
        return ()

    def evict_controller(self, controller_id: str) -> None:
        if not _valid_id(controller_id):
            raise LongRunningError("controller eviction is invalid")


@dataclass(frozen=True)
class _Registration:
    spec: HeartbeatSpec | ScheduleSpec
    registered_at_ms: int


class LongRunningCoordinator:
    """Persist due intent before delegating an exact effect to the provider."""

    def __init__(
        self,
        *,
        journal: CanonicalJournal,
        clock_ms: Callable[[], int],
        effect_sender: Callable[[LongRunningIntent], LongRunningReceipt],
        cancellation_signal: CancellationSignal,
        process_observer: LongRunningProcessObserver | None = None,
    ) -> None:
        if (
            not callable(clock_ms)
            or not callable(effect_sender)
            or not isinstance(getattr(cancellation_signal, "cancelled", None), bool)
        ):
            raise LongRunningError("long-running coordinator is invalid")
        self._journal = journal
        self._clock_ms = clock_ms
        self._effect_sender = effect_sender
        self._cancellation_signal = cancellation_signal
        self._process_observer = process_observer or _NoProcesses()
        self._registrations: dict[str, _Registration] = {}
        self._intents: dict[str, LongRunningIntent] = {}
        self._receipts: dict[str, LongRunningReceipt] = {}
        self._resident_leases: dict[str, ResidentLease] = {}
        self._task_authorities: dict[str, TaskAuthority] = {}
        self._attached_controllers: set[str] = set()
        self._evicted_controllers: set[str] = set()
        self._reconciled_evictions: set[str] = set()
        self._closed = False
        self._hydrate()

    def register_heartbeat(self, spec: HeartbeatSpec) -> None:
        if not isinstance(spec, HeartbeatSpec):
            raise LongRunningError("heartbeat registration is invalid")
        if spec.owner_kind == "user" and any(
            isinstance(item.spec, HeartbeatSpec)
            and item.spec.owner_kind == "user"
            and item.spec.heartbeat_id != spec.heartbeat_id
            for item in self._registrations.values()
        ):
            raise LongRunningError("heartbeat registration is invalid")
        self._register(spec.heartbeat_id, spec)

    def register_schedule(self, spec: ScheduleSpec) -> None:
        if not isinstance(spec, ScheduleSpec):
            raise LongRunningError("schedule registration is invalid")
        existing = self._registrations.get(spec.schedule_id)
        if existing is not None:
            if existing.spec != spec:
                raise LongRunningError("long-running registration conflicts")
            return
        now_ms = self._now_ms()
        if spec.kind == "once" and spec.due_at_ms is not None and spec.due_at_ms <= now_ms:
            raise LongRunningError("schedule registration is invalid")
        self._register(spec.schedule_id, spec, now_ms=now_ms)

    def advance(self) -> tuple[LongRunningReceipt, ...]:
        if self._closed or self._cancelled():
            return ()
        results: list[LongRunningReceipt] = []
        for intent in self._due_intents(self._now_ms()):
            if intent.effect_id in self._receipts:
                continue
            if intent.effect_id in self._intents:
                receipt = LongRunningReceipt.uncertain(intent)
            else:
                self._append(
                    JournalRecord(
                        record_id=f"long-running-intent:{intent.effect_id}",
                        kind="long-running.intent",
                        payload=intent.to_mapping(),
                    )
                )
                self._intents[intent.effect_id] = intent
                if self._cancelled():
                    receipt = LongRunningReceipt.cancelled(intent)
                else:
                    try:
                        candidate = self._effect_sender(intent)
                        receipt = self._validated_receipt(candidate, intent)
                    except LongRunningTransportError:
                        receipt = LongRunningReceipt.uncertain(intent)
                    except Exception:
                        receipt = LongRunningReceipt.uncertain(intent)
            self._record_receipt(receipt)
            results.append(receipt)
        return tuple(results)

    def recover(self) -> LongRunningSnapshot:
        for effect_id, intent in tuple(self._intents.items()):
            if effect_id not in self._receipts:
                self._record_receipt(LongRunningReceipt.uncertain(intent))
        self._reconcile_evictions()
        return self.snapshot()

    def retain_controller(
        self,
        controller_id: str,
        *,
        until_ms: int,
    ) -> ResidentLease:
        existing = self._resident_leases.get(controller_id)
        if existing is not None:
            if existing.expires_at_ms != until_ms:
                raise LongRunningError("resident lease conflicts")
            return existing
        now_ms = self._now_ms()
        lease = ResidentLease(controller_id, now_ms, until_ms)
        if self._closed:
            raise LongRunningError("long-running coordinator is closed")
        self._append(
            JournalRecord(
                record_id=f"long-running-controller:{controller_id}",
                kind="long-running.controller-retained",
                payload=lease.to_mapping(),
            )
        )
        self._resident_leases[controller_id] = lease
        return lease

    def start_task(
        self,
        task_id: str,
        *,
        authority_expires_at_ms: int,
    ) -> TaskAuthority:
        existing = self._task_authorities.get(task_id)
        if existing is not None:
            if existing.expires_at_ms != authority_expires_at_ms:
                raise LongRunningError("task authority conflicts")
            return existing
        now_ms = self._now_ms()
        authority = TaskAuthority(task_id, now_ms, authority_expires_at_ms)
        if self._closed:
            raise LongRunningError("long-running coordinator is closed")
        self._append(
            JournalRecord(
                record_id=f"long-running-task:{task_id}",
                kind="long-running.task-started",
                payload=authority.to_mapping(),
            )
        )
        self._task_authorities[task_id] = authority
        return authority

    def attach(self, controller_id: str) -> bool:
        if self.controller_status(controller_id) != "resident":
            raise LongRunningError("resident controller is unavailable")
        if controller_id in self._attached_controllers:
            return False
        self._append(
            JournalRecord(
                record_id=f"long-running-attach:{controller_id}",
                kind="long-running.controller-attached",
                payload={
                    "controller_id": controller_id,
                    "attached_at_ms": self._now_ms(),
                },
            )
        )
        self._attached_controllers.add(controller_id)
        return True

    def controller_status(
        self, controller_id: str
    ) -> Literal["missing", "resident", "expired", "evicted"]:
        if not _valid_id(controller_id):
            raise LongRunningError("controller identity is invalid")
        lease = self._resident_leases.get(controller_id)
        if lease is None:
            return "missing"
        if controller_id in self._evicted_controllers:
            return "evicted"
        return "resident" if self._now_ms() < lease.expires_at_ms else "expired"

    def task_status(self, task_id: str) -> Literal["missing", "active", "expired"]:
        if not _valid_id(task_id):
            raise LongRunningError("task identity is invalid")
        authority = self._task_authorities.get(task_id)
        if authority is None:
            return "missing"
        return "active" if self._now_ms() < authority.expires_at_ms else "expired"

    def evict_expired(self) -> tuple[str, ...]:
        now_ms = self._now_ms()
        evicted: list[str] = []
        for controller_id, lease in sorted(self._resident_leases.items()):
            if (
                controller_id not in self._evicted_controllers
                and lease.expires_at_ms <= now_ms
            ):
                self._evict_controller(controller_id, now_ms)
                evicted.append(controller_id)
        return tuple(evicted)

    def audit_orphans(self) -> OrphanAudit:
        try:
            process_ids = tuple(sorted(self._process_observer.owned_process_ids()))
        except Exception:
            raise LongRunningError("orphan audit failed safely") from None
        if (
            len(set(process_ids)) != len(process_ids)
            or any(not _valid_id(process_id) for process_id in process_ids)
        ):
            raise LongRunningError("orphan audit failed safely")
        digest = hashlib.sha256("\0".join(process_ids).encode("utf-8")).hexdigest()
        return OrphanAudit(len(process_ids), digest)

    def close(self) -> None:
        if self._closed:
            return
        self._reconcile_evictions()
        now_ms = self._now_ms()
        for controller_id in sorted(self._resident_leases):
            if controller_id not in self._evicted_controllers:
                self._evict_controller(controller_id, now_ms)
        self._append(
            JournalRecord(
                record_id="long-running-closed",
                kind="long-running.closed",
                payload={"closed_at_ms": self._now_ms()},
            )
        )
        self._closed = True

    def snapshot(self) -> LongRunningSnapshot:
        return LongRunningSnapshot(
            heartbeat_ids=tuple(
                sorted(
                    source_id
                    for source_id, item in self._registrations.items()
                    if isinstance(item.spec, HeartbeatSpec)
                )
            ),
            schedule_ids=tuple(
                sorted(
                    source_id
                    for source_id, item in self._registrations.items()
                    if isinstance(item.spec, ScheduleSpec)
                )
            ),
            history=tuple(self._receipts.values()),
            closed=self._closed,
            resident_leases=tuple(
                self._resident_leases[key] for key in sorted(self._resident_leases)
            ),
            task_authorities=tuple(
                self._task_authorities[key] for key in sorted(self._task_authorities)
            ),
            attached_controller_ids=tuple(sorted(self._attached_controllers)),
        )

    def _evict_controller(self, controller_id: str, now_ms: int) -> None:
        self._append(
            JournalRecord(
                record_id=f"long-running-eviction:{controller_id}",
                kind="long-running.controller-evicted",
                payload={"controller_id": controller_id, "evicted_at_ms": now_ms},
            )
        )
        try:
            self._process_observer.evict_controller(controller_id)
        except Exception:
            raise LongRunningError("controller eviction failed safely") from None
        self._evicted_controllers.add(controller_id)
        self._reconciled_evictions.add(controller_id)

    def _reconcile_evictions(self) -> None:
        for controller_id in sorted(
            self._evicted_controllers - self._reconciled_evictions
        ):
            try:
                self._process_observer.evict_controller(controller_id)
            except Exception:
                raise LongRunningError("controller eviction failed safely") from None
            self._reconciled_evictions.add(controller_id)

    def _register(
        self,
        source_id: str,
        spec: HeartbeatSpec | ScheduleSpec,
        *,
        now_ms: int | None = None,
    ) -> None:
        if self._closed:
            raise LongRunningError("long-running coordinator is closed")
        registered_at_ms = self._now_ms() if now_ms is None else now_ms
        existing = self._registrations.get(source_id)
        registration = _Registration(spec, registered_at_ms)
        if existing is not None:
            if existing.spec != spec:
                raise LongRunningError("long-running registration conflicts")
            return
        self._append(
            JournalRecord(
                record_id=f"long-running-registration:{source_id}",
                kind="long-running.registered",
                payload={
                    "registered_at_ms": registered_at_ms,
                    "spec": spec.to_mapping(),
                },
            )
        )
        self._registrations[source_id] = registration

    def _due_intents(self, now_ms: int) -> tuple[LongRunningIntent, ...]:
        due: list[LongRunningIntent] = []
        for source_id, registration in self._registrations.items():
            spec = registration.spec
            if isinstance(spec, HeartbeatSpec):
                times = range(
                    registration.registered_at_ms + spec.interval_ms,
                    now_ms + 1,
                    spec.interval_ms,
                )
                source_kind: Literal["heartbeat", "schedule"] = "heartbeat"
            elif spec.kind == "once":
                assert spec.due_at_ms is not None
                times = (spec.due_at_ms,) if spec.due_at_ms <= now_ms else ()
                source_kind = "schedule"
            else:
                assert spec.cron_expression is not None
                times = _cron_times(
                    spec.cron_expression,
                    after_ms=registration.registered_at_ms,
                    through_ms=now_ms,
                )
                source_kind = "schedule"
            for due_at_ms in times:
                due.append(
                    LongRunningIntent(
                        _effect_id(source_kind, source_id, due_at_ms),
                        source_id,
                        source_kind,
                        due_at_ms,
                    )
                )
        return tuple(sorted(due, key=lambda item: (item.due_at_ms, item.source_id)))

    def _record_receipt(self, receipt: LongRunningReceipt) -> None:
        self._append(
            JournalRecord(
                record_id=f"long-running-receipt:{receipt.effect_id}",
                kind="long-running.receipted",
                payload=receipt.to_mapping(),
            )
        )
        self._receipts[receipt.effect_id] = receipt

    def _append(self, record: JournalRecord) -> None:
        try:
            self._journal.append(self._journal.position, record)
        except JournalConflictError:
            raise LongRunningError("long-running journal conflicts") from None

    def _hydrate(self) -> None:
        try:
            entries = self._journal.replay(JournalCursor(0))
            for entry in entries:
                record = entry.record
                if record.kind == "long-running.registered":
                    spec = _spec_from_mapping(record.payload["spec"])
                    source_id = (
                        spec.heartbeat_id
                        if isinstance(spec, HeartbeatSpec)
                        else spec.schedule_id
                    )
                    self._registrations[source_id] = _Registration(
                        spec,
                        _integer(record.payload["registered_at_ms"]),
                    )
                elif record.kind == "long-running.intent":
                    intent = _intent_from_mapping(record.payload)
                    self._intents[intent.effect_id] = intent
                elif record.kind == "long-running.receipted":
                    receipt = _receipt_from_mapping(record.payload)
                    self._receipts[receipt.effect_id] = receipt
                elif record.kind == "long-running.controller-retained":
                    lease = ResidentLease(
                        str(record.payload["controller_id"]),
                        _integer(record.payload["acquired_at_ms"]),
                        _integer(record.payload["expires_at_ms"]),
                    )
                    self._resident_leases[lease.controller_id] = lease
                elif record.kind == "long-running.task-started":
                    authority = TaskAuthority(
                        str(record.payload["task_id"]),
                        _integer(record.payload["started_at_ms"]),
                        _integer(record.payload["expires_at_ms"]),
                    )
                    self._task_authorities[authority.task_id] = authority
                elif record.kind == "long-running.controller-attached":
                    self._attached_controllers.add(
                        str(record.payload["controller_id"])
                    )
                elif record.kind == "long-running.controller-evicted":
                    self._evicted_controllers.add(
                        str(record.payload["controller_id"])
                    )
                elif record.kind == "long-running.closed":
                    self._closed = True
        except (JournalConflictError, KeyError, LongRunningError, TypeError, ValueError):
            raise LongRunningError("long-running recovery failed safely") from None

    def _now_ms(self) -> int:
        value = self._clock_ms()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LongRunningError("long-running clock is invalid")
        return value

    def _cancelled(self) -> bool:
        value = self._cancellation_signal.cancelled
        if not isinstance(value, bool):
            raise LongRunningError("long-running cancellation signal is invalid")
        return value

    @staticmethod
    def _validated_receipt(
        receipt: object,
        intent: LongRunningIntent,
    ) -> LongRunningReceipt:
        if (
            not isinstance(receipt, LongRunningReceipt)
            or receipt.effect_id != intent.effect_id
            or receipt.source_id != intent.source_id
            or receipt.source_kind != intent.source_kind
            or receipt.due_at_ms != intent.due_at_ms
        ):
            raise LongRunningError("long-running effect receipt is invalid")
        return receipt


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and OPAQUE_ID.fullmatch(value) is not None


def _valid_time(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _valid_cron(value: object) -> bool:
    if not isinstance(value, str):
        return False
    fields = value.split(" ")
    if len(fields) != 5 or " ".join(fields) != value:
        return False
    limits = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
    return all(
        field == "*" or field.isascii() and field.isdigit() and low <= int(field) <= high
        for field, (low, high) in zip(fields, limits, strict=True)
    )


def _cron_times(expression: str, *, after_ms: int, through_ms: int) -> tuple[int, ...]:
    fields = expression.split(" ")
    first_minute = (after_ms // 60_000 + 1) * 60_000
    matches: list[int] = []
    for candidate in range(first_minute, through_ms + 1, 60_000):
        moment = datetime.fromtimestamp(candidate / 1000, timezone.utc)
        values = (
            moment.minute,
            moment.hour,
            moment.day,
            moment.month,
            (moment.weekday() + 1) % 7,
        )
        if all(field == "*" or int(field) == value for field, value in zip(fields, values, strict=True)):
            matches.append(candidate)
    return tuple(matches)


def _effect_id(source_kind: str, source_id: str, due_at_ms: int) -> str:
    digest = hashlib.sha256(
        f"{source_kind}\0{source_id}\0{due_at_ms}".encode("utf-8")
    ).hexdigest()
    return f"long-running-effect:{digest}"


def _spec_from_mapping(value: object) -> HeartbeatSpec | ScheduleSpec:
    if not isinstance(value, Mapping):
        raise LongRunningError("long-running specification is invalid")
    if value.get("spec_type") == "heartbeat":
        return HeartbeatSpec(
            str(value["source_id"]),
            str(value["owner_kind"]),  # type: ignore[arg-type]
            value["owner_id"] if isinstance(value["owner_id"], str) else None,
            _integer(value["interval_ms"]),
        )
    if value.get("spec_type") == "schedule":
        return ScheduleSpec(
            str(value["source_id"]),
            str(value["schedule_kind"]),  # type: ignore[arg-type]
            value["due_at_ms"] if isinstance(value["due_at_ms"], int) else None,
            value["cron_expression"]
            if isinstance(value["cron_expression"], str)
            else None,
        )
    raise LongRunningError("long-running specification is invalid")


def _intent_from_mapping(value: Mapping[str, object]) -> LongRunningIntent:
    return LongRunningIntent(
        str(value["effect_id"]),
        str(value["source_id"]),
        str(value["source_kind"]),  # type: ignore[arg-type]
        _integer(value["due_at_ms"]),
    )


def _receipt_from_mapping(value: Mapping[str, object]) -> LongRunningReceipt:
    return LongRunningReceipt(
        str(value["effect_id"]),
        str(value["source_id"]),
        str(value["source_kind"]),  # type: ignore[arg-type]
        _integer(value["due_at_ms"]),
        str(value["status"]),  # type: ignore[arg-type]
    )


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LongRunningError("long-running integer is invalid")
    return value
