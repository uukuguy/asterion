"""Provider-free verified Native feature record reduction."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import NoReturn

from asterion.control.host import ControlCommand
from asterion.control.protocol import OPAQUE_ID
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NativeControllerState,
    NativeEntry,
    _json_value,
)


VERIFIED_FEATURE_IDS = frozenset(
    {
        "session.delivery",
        "session.persistence-naming",
        "session.resume-delete",
        "session.usage-status",
        "rlm.environment",
        "rlm.recovery",
        "rlm.usage-cost",
    }
)


class NativeVerifiedFeatureError(ValueError):
    """Raised when verified Native feature records cannot be safely reduced."""

    def __init__(self, *_: object) -> None:
        super().__init__("native verified feature is invalid")
        self.__cause__ = None
        self.__context__ = None


def _raise_verified_error() -> NoReturn:
    try:
        raise NativeVerifiedFeatureError from None
    except NativeVerifiedFeatureError as error:
        error.__context__ = None
        raise


@dataclass(frozen=True, repr=False)
class NativeVerifiedFeatureRecord:
    feature_id: str
    record_id: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        try:
            if self.feature_id not in VERIFIED_FEATURE_IDS:
                raise NativeVerifiedFeatureError
            _require_opaque(self.record_id)
            payload = _freeze_safe_payload(self.payload)
            _validate_feature_payload(self.feature_id, payload)
            expected = native_verified_record_id(self.feature_id, payload)
            if self.record_id != expected:
                raise NativeVerifiedFeatureError
            object.__setattr__(self, "payload", payload)
        except NativeVerifiedFeatureError:
            _raise_verified_error()
        except Exception:
            _raise_verified_error()

    @property
    def digest(self) -> str:
        return _digest(
            {
                "feature_id": self.feature_id,
                "record_id": self.record_id,
                "payload": self.payload,
            }
        )

    def __repr__(self) -> str:
        return (
            "NativeVerifiedFeatureRecord("
            f"feature_id={self.feature_id!r}, record_id={self.record_id!r}, "
            f"digest={self.digest!r})"
        )


@dataclass(frozen=True)
class NativeVerifiedState:
    _sessions: Mapping[str, Mapping[str, object]]
    _rlm_environments: Mapping[str, Mapping[str, object]]

    def __post_init__(self) -> None:
        sessions = {
            session_id: MappingProxyType(dict(projection))
            for session_id, projection in self._sessions.items()
        }
        rlm_environments = {
            environment_id: MappingProxyType(dict(projection))
            for environment_id, projection in self._rlm_environments.items()
        }
        object.__setattr__(self, "_sessions", MappingProxyType(sessions))
        object.__setattr__(self, "_rlm_environments", MappingProxyType(rlm_environments))

    @property
    def session_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._sessions))

    @property
    def feature_ids(self) -> tuple[str, ...]:
        return tuple(sorted(VERIFIED_FEATURE_IDS))

    @property
    def rlm_environment_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._rlm_environments))

    def session_projection(self, session_id: str) -> Mapping[str, object]:
        try:
            _require_opaque(session_id)
            return self._sessions[session_id]
        except KeyError:
            _raise_verified_error()

    def rlm_projection(self, environment_id: str) -> Mapping[str, object]:
        try:
            _require_opaque(environment_id)
            return self._rlm_environments[environment_id]
        except KeyError:
            _raise_verified_error()


def native_verified_record_id(feature_id: str, payload: Mapping[str, object]) -> str:
    try:
        if feature_id not in VERIFIED_FEATURE_IDS:
            raise NativeVerifiedFeatureError
        frozen = _freeze_safe_payload(payload)
        _validate_feature_payload(feature_id, frozen)
        record_id = f"{feature_id}:{_digest({'feature_id': feature_id, 'payload': frozen})}"
        _require_opaque(record_id)
        return record_id
    except NativeVerifiedFeatureError:
        _raise_verified_error()
    except Exception:
        _raise_verified_error()


def reduce_verified_feature_records(
    records: Sequence[NativeVerifiedFeatureRecord],
) -> NativeVerifiedState:
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes, bytearray))
    ):
        _raise_verified_error()
    state = _MutableReduction.empty()
    seen_records: dict[str, str] = {}
    try:
        for record in tuple(records):
            if type(record) is not NativeVerifiedFeatureRecord:
                raise NativeVerifiedFeatureError
            previous = seen_records.get(record.record_id)
            if previous is not None:
                if previous != record.digest:
                    raise NativeVerifiedFeatureError
                continue
            state.apply(record)
            seen_records[record.record_id] = record.digest
        return state.freeze()
    except NativeVerifiedFeatureError:
        _raise_verified_error()
    except Exception:
        _raise_verified_error()


def native_verified_records_from_controller_state(
    state: NativeControllerState,
    entries: Iterable[NativeEntry],
) -> tuple[NativeVerifiedFeatureRecord, ...]:
    if type(state) is not NativeControllerState:
        _raise_verified_error()
    if state.session_id is None or state.generation is None:
        return ()
    active_continuation_id = _bounded_hash_id(
        "continuation",
        {
            "domain": "asterion.native-verified-continuation/v1",
            "session_id": state.session_id,
            "generation": state.generation,
        },
    )
    transcript_id = _bounded_hash_id(
        "transcript",
        {
            "domain": "asterion.native-verified-transcript/v1",
            "session_id": state.session_id,
            "generation": state.generation,
        },
    )
    records: list[NativeVerifiedFeatureRecord] = []
    records.append(
        _feature_record(
            "session.persistence-naming",
            {
                "session_id": state.session_id,
                "generation": state.generation,
                "name_digest": _digest(
                    {
                        "session_id": state.session_id,
                        "generation": state.generation,
                        "initial_create_command_digest": (
                            state.initial_create_command_digest
                        ),
                    }
                ),
                "active_continuation_id": active_continuation_id,
                "transcript_id": transcript_id,
            },
        )
    )
    records.append(
        _feature_record(
            "session.resume-delete",
            {
                "session_id": state.session_id,
                "generation": state.generation,
                "operation": "resume",
                "selector_digest": _digest(
                    _selector_identity(
                        state.session_id,
                        state.generation,
                        active_continuation_id,
                    )
                ),
                "continuation_id": active_continuation_id,
            },
        )
    )
    ordinal = 1
    try:
        for entry in entries:
            if type(entry) is not NativeEntry:
                raise NativeVerifiedFeatureError
            if entry.record.kind != "command.committed":
                continue
            command = ControlCommand.from_mapping(_mapping(entry.record.payload["command"]))
            if command.type != "input.submit":
                continue
            records.append(
                _feature_record(
                    "session.delivery",
                    {
                        "session_id": state.session_id,
                        "generation": state.generation,
                        "input_id": str(command.payload["input_id"]),
                        "delivery": str(command.payload["delivery"]),
                        "ordinal": ordinal,
                    },
                )
            )
            ordinal += 1
    except NativeVerifiedFeatureError:
        _raise_verified_error()
    except Exception:
        _raise_verified_error()
    records.append(
        _feature_record(
            "session.usage-status",
            {
                "session_id": state.session_id,
                "generation": state.generation,
                "status": _status_from_lifecycle(state.lifecycle),
                "total_tokens": state.usage.aggregate_tokens,
                "controller_tokens": state.usage.controller_tokens,
                "cost_micros": state.usage.cost_micros,
            },
        )
    )
    return tuple(records)


@dataclass
class _SessionReduction:
    session_id: str
    generation: int
    name_digest: str | None = None
    active_continuation_id: str | None = None
    transcript_id: str | None = None
    selector_continuations: dict[str, str] | None = None
    resumed_continuations: tuple[str, ...] = ()
    deleted_continuations: tuple[str, ...] = ()
    deliveries: tuple[str, ...] = ()
    delivery_modes: tuple[str, ...] = ()
    last_delivery_ordinal: int = 0
    last_delivery_rank: int = 0
    status: str | None = None
    total_tokens: int = 0
    controller_tokens: int = 0
    cost_micros: int = 0

    def __post_init__(self) -> None:
        if self.selector_continuations is None:
            self.selector_continuations = {}

    def projection(self) -> Mapping[str, object]:
        return {
            "session_id": self.session_id,
            "generation": self.generation,
            "name_digest": self.name_digest,
            "active_continuation_id": self.active_continuation_id,
            "transcript_id": self.transcript_id,
            "resumed_continuations": tuple(sorted(self.resumed_continuations)),
            "deleted_continuations": tuple(sorted(self.deleted_continuations)),
            "deliveries": self.deliveries,
            "delivery_modes": self.delivery_modes,
            "status": self.status,
            "total_tokens": self.total_tokens,
            "controller_tokens": self.controller_tokens,
            "cost_micros": self.cost_micros,
        }


@dataclass
class _RlmEnvironmentReduction:
    environment_id: str
    environment_digest: str
    child_tokens: int = 0
    cost_micros: int = 0

    def projection(self) -> Mapping[str, object]:
        return {
            "environment_id": self.environment_id,
            "environment_digest": self.environment_digest,
            "child_tokens": self.child_tokens,
            "cost_micros": self.cost_micros,
        }

    def snapshot_digest(self) -> str:
        return _digest(
            {
                "domain": "asterion.native-verified-rlm-snapshot/v1",
                **self.projection(),
            }
        )


@dataclass
class _MutableReduction:
    sessions: dict[str, _SessionReduction]
    rlm_environments: dict[str, _RlmEnvironmentReduction]

    @classmethod
    def empty(cls) -> _MutableReduction:
        return cls({}, {})

    def apply(self, record: NativeVerifiedFeatureRecord) -> None:
        if record.feature_id == "session.persistence-naming":
            self._apply_persistence_naming(record.payload)
            return
        if record.feature_id == "session.resume-delete":
            self._apply_resume_delete(record.payload)
            return
        if record.feature_id == "session.delivery":
            self._apply_delivery(record.payload)
            return
        if record.feature_id == "session.usage-status":
            self._apply_usage_status(record.payload)
            return
        if record.feature_id == "rlm.environment":
            self._apply_rlm_environment(record.payload)
            return
        if record.feature_id == "rlm.usage-cost":
            self._apply_rlm_usage(record.payload)
            return
        if record.feature_id == "rlm.recovery":
            self._apply_rlm_recovery(record.payload)
            return
        raise NativeVerifiedFeatureError

    def freeze(self) -> NativeVerifiedState:
        return NativeVerifiedState(
            {
                session_id: session.projection()
                for session_id, session in self.sessions.items()
            },
            {
                environment_id: environment.projection()
                for environment_id, environment in self.rlm_environments.items()
            },
        )

    def _session(self, payload: Mapping[str, object]) -> _SessionReduction:
        session_id = str(payload["session_id"])
        generation = _positive_int(payload["generation"])
        existing = self.sessions.get(session_id)
        if existing is None:
            existing = _SessionReduction(session_id, generation)
            self.sessions[session_id] = existing
            return existing
        if existing.generation != generation:
            raise NativeVerifiedFeatureError
        return existing

    def _apply_persistence_naming(self, payload: Mapping[str, object]) -> None:
        session = self._session(payload)
        name_digest = str(payload["name_digest"])
        active_continuation_id = str(payload["active_continuation_id"])
        transcript_id = str(payload["transcript_id"])
        if session.name_digest is None:
            session.name_digest = name_digest
            session.active_continuation_id = active_continuation_id
            session.transcript_id = transcript_id
            return
        if (
            session.name_digest != name_digest
            or session.active_continuation_id != active_continuation_id
            or session.transcript_id != transcript_id
        ):
            raise NativeVerifiedFeatureError

    def _apply_resume_delete(self, payload: Mapping[str, object]) -> None:
        session = self._session(payload)
        operation = str(payload["operation"])
        selector_digest = str(payload["selector_digest"])
        continuation_id = str(payload["continuation_id"])
        assert session.selector_continuations is not None
        existing = session.selector_continuations.get(selector_digest)
        if existing is not None and existing != continuation_id:
            raise NativeVerifiedFeatureError
        session.selector_continuations[selector_digest] = continuation_id
        if operation == "resume":
            session.resumed_continuations = _append_unique(
                session.resumed_continuations, continuation_id
            )
            return
        if operation == "delete":
            if (
                session.active_continuation_id is None
                or session.active_continuation_id == continuation_id
            ):
                raise NativeVerifiedFeatureError
            session.deleted_continuations = _append_unique(
                session.deleted_continuations, continuation_id
            )
            return
        raise NativeVerifiedFeatureError

    def _apply_delivery(self, payload: Mapping[str, object]) -> None:
        session = self._session(payload)
        ordinal = _positive_int(payload["ordinal"])
        delivery = str(payload["delivery"])
        rank = _DELIVERY_RANKS[delivery]
        if ordinal <= session.last_delivery_ordinal or rank < session.last_delivery_rank:
            raise NativeVerifiedFeatureError
        input_id = str(payload["input_id"])
        if input_id in session.deliveries:
            raise NativeVerifiedFeatureError
        session.deliveries = (*session.deliveries, input_id)
        session.delivery_modes = (*session.delivery_modes, delivery)
        session.last_delivery_ordinal = ordinal
        session.last_delivery_rank = rank

    def _apply_usage_status(self, payload: Mapping[str, object]) -> None:
        session = self._session(payload)
        total_tokens = _nonnegative_int(payload["total_tokens"])
        controller_tokens = _nonnegative_int(payload["controller_tokens"])
        cost_micros = _nonnegative_int(payload["cost_micros"])
        if (
            total_tokens < session.total_tokens
            or controller_tokens < session.controller_tokens
            or cost_micros < session.cost_micros
            or total_tokens < controller_tokens
        ):
            raise NativeVerifiedFeatureError
        session.status = str(payload["status"])
        session.total_tokens = total_tokens
        session.controller_tokens = controller_tokens
        session.cost_micros = cost_micros

    def _apply_rlm_environment(self, payload: Mapping[str, object]) -> None:
        environment_id = str(payload["environment_id"])
        environment_digest = str(payload["environment_digest"])
        existing = self.rlm_environments.get(environment_id)
        if existing is None:
            self.rlm_environments[environment_id] = _RlmEnvironmentReduction(
                environment_id,
                environment_digest,
            )
            return
        if existing.environment_digest != environment_digest:
            raise NativeVerifiedFeatureError

    def _apply_rlm_usage(self, payload: Mapping[str, object]) -> None:
        environment = self._rlm_environment(payload)
        child_tokens = _nonnegative_int(payload["child_tokens"])
        cost_micros = _nonnegative_int(payload["cost_micros"])
        if (
            child_tokens > MAX_SAFE_JSON_INTEGER - environment.child_tokens
            or cost_micros > MAX_SAFE_JSON_INTEGER - environment.cost_micros
        ):
            raise NativeVerifiedFeatureError
        environment.child_tokens += child_tokens
        environment.cost_micros += cost_micros

    def _apply_rlm_recovery(self, payload: Mapping[str, object]) -> None:
        environment = self._rlm_environment(payload)
        if payload["snapshot_digest"] != environment.snapshot_digest():
            raise NativeVerifiedFeatureError

    def _rlm_environment(
        self, payload: Mapping[str, object]
    ) -> _RlmEnvironmentReduction:
        try:
            return self.rlm_environments[str(payload["environment_id"])]
        except KeyError:
            raise NativeVerifiedFeatureError from None


def _feature_record(
    feature_id: str, payload: Mapping[str, object]
) -> NativeVerifiedFeatureRecord:
    return NativeVerifiedFeatureRecord(
        feature_id=feature_id,
        record_id=native_verified_record_id(feature_id, payload),
        payload=payload,
    )


def _validate_feature_payload(feature_id: str, payload: Mapping[str, object]) -> None:
    if feature_id == "session.persistence-naming":
        _require_fields(
            payload,
            {
                "session_id",
                "generation",
                "name_digest",
                "active_continuation_id",
                "transcript_id",
            },
        )
        _require_session(payload)
        _require_sha256(payload["name_digest"])
        _require_opaque(payload["active_continuation_id"])
        _require_opaque(payload["transcript_id"])
        return
    if feature_id == "session.resume-delete":
        _require_fields(
            payload,
            {
                "session_id",
                "generation",
                "operation",
                "selector_digest",
                "continuation_id",
            },
        )
        _require_session(payload)
        if payload["operation"] not in {"resume", "delete"}:
            raise NativeVerifiedFeatureError
        _require_sha256(payload["selector_digest"])
        _require_opaque(payload["continuation_id"])
        if payload["selector_digest"] != _digest(
            _selector_identity(
                str(payload["session_id"]),
                _positive_int(payload["generation"]),
                str(payload["continuation_id"]),
            )
        ):
            raise NativeVerifiedFeatureError
        return
    if feature_id == "session.delivery":
        _require_fields(
            payload,
            {"session_id", "generation", "input_id", "delivery", "ordinal"},
        )
        _require_session(payload)
        _require_opaque(payload["input_id"])
        if payload["delivery"] not in _DELIVERY_RANKS:
            raise NativeVerifiedFeatureError
        _positive_int(payload["ordinal"])
        return
    if feature_id == "session.usage-status":
        _require_fields(
            payload,
            {
                "session_id",
                "generation",
                "status",
                "total_tokens",
                "controller_tokens",
                "cost_micros",
            },
        )
        _require_session(payload)
        if payload["status"] not in _SAFE_SESSION_STATUSES:
            raise NativeVerifiedFeatureError
        total_tokens = _nonnegative_int(payload["total_tokens"])
        controller_tokens = _nonnegative_int(payload["controller_tokens"])
        _nonnegative_int(payload["cost_micros"])
        if total_tokens < controller_tokens:
            raise NativeVerifiedFeatureError
        return
    if feature_id == "rlm.environment":
        _require_fields(payload, {"environment_id", "environment_digest"})
        _require_opaque(payload["environment_id"])
        _require_sha256(payload["environment_digest"])
        return
    if feature_id == "rlm.usage-cost":
        _require_fields(payload, {"environment_id", "child_tokens", "cost_micros"})
        _require_opaque(payload["environment_id"])
        _nonnegative_int(payload["child_tokens"])
        _nonnegative_int(payload["cost_micros"])
        return
    if feature_id == "rlm.recovery":
        _require_fields(payload, {"environment_id", "snapshot_digest"})
        _require_opaque(payload["environment_id"])
        _require_sha256(payload["snapshot_digest"])
        return
    raise NativeVerifiedFeatureError


def _require_session(payload: Mapping[str, object]) -> None:
    _require_opaque(payload["session_id"])
    _positive_int(payload["generation"])


def _freeze_safe_payload(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise NativeVerifiedFeatureError
    frozen = _freeze_json_value(value)
    if not isinstance(frozen, Mapping):
        raise NativeVerifiedFeatureError
    return frozen


def _freeze_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise NativeVerifiedFeatureError
            frozen[key] = _freeze_json_value(item)
        return MappingProxyType(frozen)
    if isinstance(value, tuple):
        return tuple(_freeze_json_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_freeze_json_value(item) for item in value)
    if value is None or type(value) in {str, bool}:
        return value
    if type(value) is int and 0 <= value <= MAX_SAFE_JSON_INTEGER:
        return value
    raise NativeVerifiedFeatureError


def _mapping(value: object) -> Mapping[str, object]:
    converted = _json_value(value)
    if not isinstance(converted, Mapping):
        raise NativeVerifiedFeatureError
    return converted


def _require_fields(value: Mapping[str, object], fields: set[str]) -> None:
    if set(value) != fields:
        raise NativeVerifiedFeatureError


def _require_opaque(value: object) -> None:
    if not isinstance(value, str) or OPAQUE_ID.fullmatch(value) is None:
        raise NativeVerifiedFeatureError


def _require_sha256(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise NativeVerifiedFeatureError


def _positive_int(value: object) -> int:
    if (
        isinstance(value, bool)
        or type(value) is not int
        or value < 1
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeVerifiedFeatureError
    return value


def _nonnegative_int(value: object) -> int:
    if (
        isinstance(value, bool)
        or type(value) is not int
        or value < 0
        or value > MAX_SAFE_JSON_INTEGER
    ):
        raise NativeVerifiedFeatureError
    return value


def _append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
    if value in values:
        return values
    return (*values, value)


def _status_from_lifecycle(lifecycle: str) -> str:
    status = lifecycle.replace("-", "_")
    if status == "bound":
        return "initializing"
    if status not in _SAFE_SESSION_STATUSES:
        raise NativeVerifiedFeatureError
    return status


def _bounded_hash_id(prefix: str, payload: Mapping[str, object]) -> str:
    record_id = f"{prefix}:{_digest(payload)}"
    _require_opaque(record_id)
    return record_id


def _selector_identity(
    session_id: str,
    generation: int,
    continuation_id: str,
) -> Mapping[str, object]:
    return {
        "domain": "asterion.native-verified-selector/v1",
        "session_id": session_id,
        "generation": generation,
        "continuation_id": continuation_id,
    }


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_value(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


_DELIVERY_RANKS = MappingProxyType({"direct": 0, "steer": 1, "follow_up": 2})
_SAFE_SESSION_STATUSES = frozenset(
    {
        "initializing",
        "created",
        "running",
        "paused",
        "recovery_required",
        "budget_limited",
        "cancelled",
        "completed",
        "failed",
    }
)
