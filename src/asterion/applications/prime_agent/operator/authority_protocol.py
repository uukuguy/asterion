"""Strict, non-authoritative parsing for the separately launched Prime P1 authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from types import MappingProxyType
from typing import NoReturn, Protocol, cast

PROTOCOL = "asterion.prime-p1-authority-ipc/v1"
_DOMAIN = b"asterion.prime-p1-authority-ipc/v1\0"
_RECEIPT_FORMAT = "asterion.prime-p1-authority-receipt/v1"
_RECEIPT_DOMAIN = b"asterion.prime-p1-authority-receipt/v1\0"
_MAX_PACKET_BYTES, _MAX_RUN_ID = 8192, 128
_SESSION_ID, _SHA256 = re.compile(r"[0-9a-f]{64}\Z"), re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID, _REASON = (
    re.compile(r"[a-z][a-z0-9.-]{0,127}\Z"),
    re.compile(r"[a-z][a-z0-9-]{0,63}\Z"),
)
_FRAME_KEYS = frozenset(
    {"protocol", "session_id", "sequence", "kind", "payload", "frame_hmac_sha256"}
)
_RECEIPT_KEYS = frozenset(
    {
        "format",
        "status",
        "reason_code",
        "run_id",
        "session_id",
        "request_contract_sha256",
        "application_request_sha256",
        "authority",
        "identity",
        "model_accounting",
        "worker_evidence",
        "causal_evidence",
        "evidence_id",
        "receipt_sha256",
        "receipt_hmac_sha256",
    }
)


class PrimeP1AuthorityProtocolError(ValueError):
    """Single public-safe authority IPC failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 authority IPC is unavailable")


@dataclass(frozen=True, repr=False)
class AuthorityFrame:
    session_id: str
    sequence: int
    kind: str
    payload: Mapping[str, object]

    def __repr__(self) -> str:
        return "AuthorityFrame(redacted)"


@dataclass(frozen=True, repr=False)
class TerminalReceipt:
    """Immutable parsed syntax, deliberately not an execution grant or PASS constructor."""

    status: str
    receipt_sha256: str
    values: Mapping[str, object]

    def __repr__(self) -> str:
        return "TerminalReceipt(redacted)"


class ReplayLedger(Protocol):
    def claim(self, session_id: str, sequence: int) -> bool: ...


class InMemoryReplayLedger:
    """Test-only atomic replay seam; production receives no default durable ledger."""

    def __init__(self) -> None:
        self._claims: set[tuple[str, int]] = set()

    def claim(self, session_id: str, sequence: int) -> bool:
        claim = (session_id, sequence)
        if claim in self._claims:
            return False
        self._claims.add(claim)
        return True


class AuthoritySession:
    """Authority-side state: ready, one execute, optional cancel, one terminal."""

    def __init__(
        self,
        session_id: str,
        session_key: bytes,
        request_contract_sha256: str,
        resource_set_sha256: str,
        *,
        replay_ledger: ReplayLedger | None = None,
    ) -> None:
        if not (
            _is_session_id(session_id)
            and _is_key(session_key)
            and _is_sha256(request_contract_sha256)
            and _is_sha256(resource_set_sha256)
        ):
            _unavailable()
        (
            self._session_id,
            self._session_key,
            self._contract,
            self._resource,
            self._ledger,
            self._state,
        ) = (
            session_id,
            session_key,
            request_contract_sha256,
            resource_set_sha256,
            replay_ledger,
            "await-execute",
        )

    def ready_packet(self) -> bytes:
        if self._state != "await-execute":
            _unavailable()
        return encode_frame(
            self._session_key,
            self._session_id,
            0,
            "ready",
            {
                "request_contract_sha256": self._contract,
                "resource_set_sha256": self._resource,
            },
        )

    def accept_supervisor_packet(self, packet: bytes) -> AuthorityFrame:
        frame = decode_frame(packet, self._session_key)
        if frame.session_id != self._session_id:
            _unavailable()
        if self._state == "await-execute":
            valid, next_state = (
                frame.sequence == 0
                and frame.kind == "execute"
                and _execute(frame.payload, self._contract),
                "await-cancel-or-terminal",
            )
        elif self._state == "await-cancel-or-terminal":
            valid, next_state = (
                frame.sequence == 1 and frame.kind == "cancel" and not frame.payload,
                "cancelled",
            )
        else:
            valid, next_state = False, self._state
        if not valid:
            _unavailable()
        self._claim(frame)
        self._state = next_state
        return frame

    def terminal_packet(self, receipt: Mapping[str, object]) -> bytes:
        if self._state not in {"await-cancel-or-terminal", "cancelled"}:
            _unavailable()
        _receipt(receipt, self._session_id, self._contract, None)
        self._state = "terminal-emitted"
        return encode_frame(self._session_key, self._session_id, 1, "terminal", receipt)

    def _claim(self, frame: AuthorityFrame) -> None:
        if self._ledger is None:
            return
        try:
            claimed = self._ledger.claim(frame.session_id, frame.sequence)
        except Exception:
            _unavailable()
        if claimed is not True:
            _unavailable()


class SupervisorSession:
    """Supervisor-side direction and sequence validation; parsed data grants no authority."""

    def __init__(
        self,
        session_id: str,
        session_key: bytes,
        request_contract_sha256: str,
        *,
        receipt_hmac_key: bytes | None = None,
    ) -> None:
        if not (
            _is_session_id(session_id)
            and _is_key(session_key)
            and _is_sha256(request_contract_sha256)
            and (receipt_hmac_key is None or _is_key(receipt_hmac_key))
        ):
            _unavailable()
        (
            self._session_id,
            self._session_key,
            self._contract,
            self._receipt_key,
            self._state,
        ) = (
            session_id,
            session_key,
            request_contract_sha256,
            receipt_hmac_key,
            "await-ready",
        )

    def accept_authority_packet(self, packet: bytes) -> TerminalReceipt | None:
        frame = decode_frame(packet, self._session_key)
        if frame.session_id != self._session_id:
            _unavailable()
        if self._state == "await-ready":
            if (
                frame.sequence != 0
                or frame.kind != "ready"
                or not _ready(frame.payload, self._contract)
            ):
                _unavailable()
            self._state = "ready"
            return None
        if self._state in {"await-terminal", "cancel-sent"}:
            if frame.sequence != 1 or frame.kind != "terminal":
                _unavailable()
            result = _receipt(
                frame.payload, self._session_id, self._contract, self._receipt_key
            )
            self._state = "terminal-received"
            return result
        _unavailable()

    def execute_packet(self, run_id: str, application_request_sha256: str) -> bytes:
        if (
            self._state != "ready"
            or not _is_run_id(run_id)
            or not _is_sha256(application_request_sha256)
        ):
            _unavailable()
        self._state = "await-terminal"
        return encode_frame(
            self._session_key,
            self._session_id,
            0,
            "execute",
            {
                "run_id": run_id,
                "request_contract_sha256": self._contract,
                "application_request_sha256": application_request_sha256,
            },
        )

    def cancel_packet(self) -> bytes:
        if self._state != "await-terminal":
            _unavailable()
        self._state = "cancel-sent"
        return encode_frame(self._session_key, self._session_id, 1, "cancel", {})


def encode_frame(
    key: bytes, session_id: str, sequence: int, kind: str, payload: Mapping[str, object]
) -> bytes:
    """Serialize an authenticated frame; serialization itself confers no authority."""
    try:
        if (
            not _is_key(key)
            or not _is_session_id(session_id)
            or type(sequence) is not int
            or sequence < 0
            or type(payload) is not dict
        ):
            raise ValueError
        body: dict[str, object] = {
            "kind": kind,
            "payload": dict(payload),
            "protocol": PROTOCOL,
            "sequence": sequence,
            "session_id": session_id,
        }
        _body(body)
        body["frame_hmac_sha256"] = hmac.new(
            key, _DOMAIN + _json(body), "sha256"
        ).hexdigest()
        packet = _json(body)
        if len(packet) > _MAX_PACKET_BYTES:
            raise ValueError
        return packet
    except (TypeError, ValueError, UnicodeError):
        _unavailable()


def decode_frame(packet: bytes, key: bytes) -> AuthorityFrame:
    try:
        if (
            not _is_key(key)
            or type(packet) is not bytes
            or not 1 <= len(packet) <= _MAX_PACKET_BYTES
        ):
            raise ValueError
        value = json.loads(packet.decode("utf-8"))
        if type(value) is not dict or set(value) != _FRAME_KEYS:
            raise ValueError
        supplied = value.pop("frame_hmac_sha256")
        _body(value)
        if (
            not _is_sha256(supplied)
            or _json({**value, "frame_hmac_sha256": supplied}) != packet
        ):
            raise ValueError
        if not hmac.compare_digest(
            supplied, hmac.new(key, _DOMAIN + _json(value), "sha256").hexdigest()
        ):
            raise ValueError
        return AuthorityFrame(
            value["session_id"],
            value["sequence"],
            value["kind"],
            _freeze(value["payload"]),
        )
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        _unavailable()


def _body(value: Mapping[str, object]) -> None:
    if (
        set(value) != {"protocol", "session_id", "sequence", "kind", "payload"}
        or value["protocol"] != PROTOCOL
        or not _is_session_id(value["session_id"])
        or type(value["sequence"]) is not int
        or value["sequence"] < 0
        or type(value["kind"]) is not str
        or type(value["payload"]) is not dict
    ):
        raise ValueError
    kind, payload = value["kind"], value["payload"]
    if not (
        (kind == "ready" and _ready(payload, None))
        or (kind == "execute" and _execute(payload, None))
        or (kind == "cancel" and not payload)
        or (kind == "terminal")
    ):
        raise ValueError


def _ready(value: Mapping[str, object], contract: str | None) -> bool:
    return (
        set(value) == {"request_contract_sha256", "resource_set_sha256"}
        and all(_is_sha256(x) for x in value.values())
        and (contract is None or value["request_contract_sha256"] == contract)
    )


def _execute(value: Mapping[str, object], contract: str | None) -> bool:
    return (
        set(value)
        == {"run_id", "request_contract_sha256", "application_request_sha256"}
        and _is_run_id(value.get("run_id"))
        and _is_sha256(value.get("request_contract_sha256"))
        and _is_sha256(value.get("application_request_sha256"))
        and (contract is None or value["request_contract_sha256"] == contract)
    )


def _receipt(
    value: Mapping[str, object], session: str, contract: str, key: bytes | None
) -> TerminalReceipt:
    try:
        if (
            not isinstance(value, Mapping)
            or set(value) != _RECEIPT_KEYS
            or value.get("format") != _RECEIPT_FORMAT
            or value.get("status") not in {"PASS", "FAIL", "CANCELLED", "UNAVAILABLE"}
            or not _is_reason(value.get("reason_code"))
            or value.get("session_id") != session
            or value.get("request_contract_sha256") != contract
            or not _is_run_id(value.get("run_id"))
        ):
            raise ValueError
        _exact(
            value["authority"],
            {
                "authority_version",
                "authority_executable_sha256",
                "operator_config_binding_hmac_sha256",
                "production_resource_set_sha256",
                "receipt_key_id",
            },
        )
        _exact(
            value["identity"],
            {
                "provider_id",
                "application_id",
                "application_version",
                "assembly_ref",
                "assembly_sha256",
                "package_ref",
                "package_manifest_sha256",
                "implementation_ref",
                "runtime_id",
                "prime_sdk_ref",
                "source_sha256",
                "build_input_sha256",
                "image_config_digest",
                "workload_sha256",
                "starter_sha256",
                "oracle_sha256",
                "seccomp_sha256",
            },
        )
        _exact(
            value["model_accounting"],
            {
                "request_count",
                "input_bytes",
                "output_bytes",
                "provider_reported_input_tokens",
                "provider_reported_output_tokens",
                "charged_cost_microunits",
                "cost_basis",
                "max_requests",
                "max_input_bytes",
                "max_output_bytes",
                "max_input_tokens",
                "max_output_tokens",
                "max_cost_microunits",
                "deadline_milliseconds",
                "request_sha256",
                "response_sha256",
                "broker_receipt_sha256",
                "transport_reaped",
            },
        )
        _exact(
            value["worker_evidence"],
            {
                "worker_count",
                "container_id_sha256",
                "model_tool_calls",
                "ipython_tool_calls",
                "sent_cell_sha256",
                "initial_workspace_sha256",
                "post_workspace_sha256",
                "initial_oracle_passed",
                "final_oracle_passed",
                "mutation_after_model_response",
                "broker_quiesced",
                "container_removed",
                "daemon_absence_verified",
            },
        )
        _exact(
            value["causal_evidence"],
            {
                "event_count",
                "first_sequence",
                "last_sequence",
                "event_chain_sha256",
                "result_projection_sha256",
            },
        )
        _receipt_values(value)
        unsigned = {
            name: item
            for name, item in value.items()
            if name not in {"evidence_id", "receipt_sha256", "receipt_hmac_sha256"}
        }
        digest = hashlib.sha256(_RECEIPT_DOMAIN + _json(unsigned)).hexdigest()
        if (
            value.get("receipt_sha256") != digest
            or value.get("evidence_id") != "prime-p1-" + digest
            or not _is_sha256(value.get("receipt_hmac_sha256"))
        ):
            raise ValueError
        receipt_hmac = value["receipt_hmac_sha256"]
        status = value["status"]
        assert isinstance(receipt_hmac, str) and isinstance(status, str)
        signed = {
            **unsigned,
            "evidence_id": value["evidence_id"],
            "receipt_sha256": digest,
        }
        if key is not None and not hmac.compare_digest(
            receipt_hmac,
            hmac.new(key, _RECEIPT_DOMAIN + _json(signed), "sha256").hexdigest(),
        ):
            raise ValueError
        return TerminalReceipt(status, digest, _freeze(value))
    except (KeyError, TypeError, ValueError, UnicodeError):
        _unavailable()


def _exact(value: object, keys: set[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError


def _receipt_values(v: Mapping[str, object]) -> None:
    a, i, m, w, c = (
        v[n]
        for n in (
            "authority",
            "identity",
            "model_accounting",
            "worker_evidence",
            "causal_evidence",
        )
    )
    if not all(isinstance(item, Mapping) for item in (a, i, m, w, c)):
        raise ValueError
    a = cast(Mapping[str, object], a)
    i = cast(Mapping[str, object], i)
    m = cast(Mapping[str, object], m)
    w = cast(Mapping[str, object], w)
    c = cast(Mapping[str, object], c)
    if not all(
        _is_sha256(a[n])
        for n in (
            "authority_executable_sha256",
            "operator_config_binding_hmac_sha256",
            "production_resource_set_sha256",
        )
    ) or not all(
        type(a[n]) is str and a[n] for n in ("authority_version", "receipt_key_id")
    ):
        raise ValueError
    if tuple(
        i[n]
        for n in (
            "provider_id",
            "application_id",
            "application_version",
            "assembly_ref",
            "package_ref",
            "implementation_ref",
            "runtime_id",
            "prime_sdk_ref",
        )
    ) != (
        "prime-agent",
        "prime.ipython-coding",
        "1.0.0",
        "prime.ipython-coding@1.0.0",
        "prime-agent@1.0.0",
        "prime.ipython-coding@1.0.0",
        "prime.agent",
        "prime-agent@0.7.1",
    ):
        raise ValueError
    if (
        not all(
            _is_sha256(i[n])
            for n in (
                "assembly_sha256",
                "package_manifest_sha256",
                "source_sha256",
                "build_input_sha256",
                "workload_sha256",
                "starter_sha256",
                "oracle_sha256",
                "seccomp_sha256",
            )
        )
        or type(i["image_config_digest"]) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", i["image_config_digest"]) is None
    ):
        raise ValueError
    ints = (
        "request_count",
        "input_bytes",
        "output_bytes",
        "provider_reported_input_tokens",
        "provider_reported_output_tokens",
        "charged_cost_microunits",
        "max_requests",
        "max_input_bytes",
        "max_output_bytes",
        "max_input_tokens",
        "max_output_tokens",
        "max_cost_microunits",
        "deadline_milliseconds",
    )
    if (
        m["cost_basis"] != "reserved-ceiling"
        or not all(_nonnegative_int(m[n]) for n in ints)
        or not all(
            _is_sha256(m[n])
            for n in ("request_sha256", "response_sha256", "broker_receipt_sha256")
        )
        or type(m["transport_reaped"]) is not bool
    ):
        raise ValueError
    if (
        not all(
            _nonnegative_int(w[n])
            for n in ("worker_count", "model_tool_calls", "ipython_tool_calls")
        )
        or not all(
            _is_sha256(w[n])
            for n in (
                "container_id_sha256",
                "sent_cell_sha256",
                "initial_workspace_sha256",
                "post_workspace_sha256",
            )
        )
        or not all(
            type(w[n]) is bool
            for n in (
                "initial_oracle_passed",
                "final_oracle_passed",
                "mutation_after_model_response",
                "broker_quiesced",
                "container_removed",
                "daemon_absence_verified",
            )
        )
    ):
        raise ValueError
    if (
        not all(
            _positive_int(c[n])
            for n in ("event_count", "first_sequence", "last_sequence")
        )
        or c["first_sequence"] != 1
        or c["last_sequence"] != c["event_count"]
        or not all(
            _is_sha256(c[n]) for n in ("event_chain_sha256", "result_projection_sha256")
        )
    ):
        raise ValueError
    if v["status"] == "PASS" and not (
        m["request_count"] == m["max_requests"] == 1
        and m["transport_reaped"] is True
        and w["worker_count"] == w["model_tool_calls"] == w["ipython_tool_calls"] == 1
        and w["initial_oracle_passed"] is False
        and all(
            w[n] is True
            for n in (
                "final_oracle_passed",
                "mutation_after_model_response",
                "broker_quiesced",
                "container_removed",
                "daemon_absence_verified",
            )
        )
    ):
        raise ValueError


def _freeze(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError
    return MappingProxyType(
        {
            key: _freeze(item)
            if isinstance(item, Mapping)
            else tuple(item)
            if isinstance(item, list)
            else item
            for key, item in value.items()
        }
    )


def _json(value: object) -> bytes:
    return json.dumps(
        _thaw(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _is_key(value: object) -> bool:
    return type(value) is bytes and len(value) == 32


def _is_session_id(value: object) -> bool:
    return type(value) is str and _SESSION_ID.fullmatch(value) is not None


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _is_run_id(value: object) -> bool:
    return (
        type(value) is str
        and len(value) <= _MAX_RUN_ID
        and _RUN_ID.fullmatch(value) is not None
    )


def _is_reason(value: object) -> bool:
    return type(value) is str and _REASON.fullmatch(value) is not None


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _positive_int(value: object) -> bool:
    return type(value) is int and value >= 1


def _unavailable() -> NoReturn:
    raise PrimeP1AuthorityProtocolError()
