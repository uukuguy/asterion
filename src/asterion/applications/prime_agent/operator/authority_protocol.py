"""Strict wire parsing for the separately launched Prime P1 authority.

This module is deliberately only a protocol implementation.  It neither opens
sockets nor grants execution authority; the operator-owned process and its OS
identity supply that boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hmac
import json
import re
from typing import NoReturn, Protocol


PROTOCOL = "asterion.prime-p1-authority-ipc/v1"
_DOMAIN = b"asterion.prime-p1-authority-ipc/v1\0"
_MAX_PACKET_BYTES = 8192
_SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID = re.compile(r"[a-z][a-z0-9.-]*\Z")
_FRAME_KEYS = frozenset(
    {"protocol", "session_id", "sequence", "kind", "payload", "frame_hmac_sha256"}
)


class PrimeP1AuthorityProtocolError(ValueError):
    """Single public-safe IPC failure category."""

    def __init__(self, *_: object) -> None:
        super().__init__("prime P1 authority IPC is unavailable")


@dataclass(frozen=True, repr=False)
class AuthorityFrame:
    session_id: str
    sequence: int
    kind: str
    payload: Mapping[str, str]

    def __repr__(self) -> str:
        return "AuthorityFrame(redacted)"


class ReplayLedger(Protocol):
    """Host-owned durable replay state; application code must not provide it."""

    def claim(self, session_id: str, sequence: int) -> bool: ...


class InMemoryReplayLedger:
    """Test/development ledger; production injects process-owned durable state."""

    def __init__(self) -> None:
        self._claims: set[tuple[str, int]] = set()

    def claim(self, session_id: str, sequence: int) -> bool:
        claim = (session_id, sequence)
        if claim in self._claims:
            return False
        self._claims.add(claim)
        return True


class AuthoritySession:
    """Closed authority-side state machine for one supervisor connection."""

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
        self._session_id = session_id
        self._session_key = session_key
        self._request_contract_sha256 = request_contract_sha256
        self._resource_set_sha256 = resource_set_sha256
        self._ledger = replay_ledger if replay_ledger is not None else InMemoryReplayLedger()
        self._state = "await-execute"

    def ready_packet(self) -> bytes:
        return encode_frame(
            self._session_key,
            self._session_id,
            0,
            "ready",
            {
                "request_contract_sha256": self._request_contract_sha256,
                "resource_set_sha256": self._resource_set_sha256,
            },
        )

    def accept_supervisor_packet(self, packet: bytes) -> AuthorityFrame:
        frame = decode_frame(packet, self._session_key)
        if frame.session_id != self._session_id or not self._ledger.claim(frame.session_id, frame.sequence):
            _unavailable()
        if self._state == "await-execute":
            if frame.sequence != 0 or frame.kind != "execute" or not _is_execute_payload(frame.payload, self._request_contract_sha256):
                _unavailable()
            self._state = "await-cancel-or-terminal"
            return frame
        if self._state == "await-cancel-or-terminal":
            if frame.sequence != 1 or frame.kind != "cancel" or dict(frame.payload):
                _unavailable()
            self._state = "cancelled"
            return frame
        _unavailable()


def encode_frame(
    key: bytes, session_id: str, sequence: int, kind: str, payload: Mapping[str, str]
) -> bytes:
    """Produce exactly one canonical authenticated frame for a trusted endpoint."""
    try:
        if not _is_key(key) or not _is_session_id(session_id) or type(sequence) is not int or sequence < 0:
            raise ValueError
        body: dict[str, object] = {
            "kind": kind,
            "payload": dict(payload),
            "protocol": PROTOCOL,
            "sequence": sequence,
            "session_id": session_id,
        }
        _validate_body(body)
        mac = hmac.new(key, _DOMAIN + _canonical_json(body), "sha256").hexdigest()
        body["frame_hmac_sha256"] = mac
        return _canonical_json(body)
    except (TypeError, ValueError, UnicodeError):
        _unavailable()


def decode_frame(packet: bytes, key: bytes) -> AuthorityFrame:
    """Authenticate and strictly parse one packet without exposing its contents on error."""
    try:
        if not _is_key(key) or type(packet) is not bytes or not 1 <= len(packet) <= _MAX_PACKET_BYTES:
            raise ValueError
        value = json.loads(packet.decode("utf-8"))
        if type(value) is not dict or set(value) != _FRAME_KEYS:
            raise ValueError
        supplied = value.pop("frame_hmac_sha256")
        _validate_body(value)
        if type(supplied) is not str or _SHA256.fullmatch(supplied) is None:
            raise ValueError
        canonical = _canonical_json(value)
        if _canonical_json({**value, "frame_hmac_sha256": supplied}) != packet:
            raise ValueError
        expected = hmac.new(key, _DOMAIN + canonical, "sha256").hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        return AuthorityFrame(
            session_id=value["session_id"],
            sequence=value["sequence"],
            kind=value["kind"],
            payload=dict(value["payload"]),
        )
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        _unavailable()


def _validate_body(value: Mapping[str, object]) -> None:
    if set(value) != {"protocol", "session_id", "sequence", "kind", "payload"}:
        raise ValueError
    if value["protocol"] != PROTOCOL or not _is_session_id(value["session_id"]):
        raise ValueError
    if type(value["sequence"]) is not int or value["sequence"] < 0 or type(value["kind"]) is not str:
        raise ValueError
    payload = value["payload"]
    if type(payload) is not dict or any(type(key) is not str or type(item) is not str for key, item in payload.items()):
        raise ValueError
    kind = value["kind"]
    if kind == "ready":
        valid = set(payload) == {"request_contract_sha256", "resource_set_sha256"} and all(_is_sha256(item) for item in payload.values())
    elif kind == "execute":
        valid = set(payload) == {"run_id", "request_contract_sha256", "application_request_sha256"} and _RUN_ID.fullmatch(payload.get("run_id", "")) is not None and _is_sha256(payload.get("request_contract_sha256", "")) and _is_sha256(payload.get("application_request_sha256", ""))
    elif kind == "cancel":
        valid = not payload
    else:
        valid = False
    if not valid:
        raise ValueError


def _is_execute_payload(payload: Mapping[str, str], contract: str) -> bool:
    return payload.get("request_contract_sha256") == contract


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _is_key(value: object) -> bool:
    return type(value) is bytes and len(value) == 32


def _is_session_id(value: object) -> bool:
    return type(value) is str and _SESSION_ID.fullmatch(value) is not None


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _unavailable() -> NoReturn:
    raise PrimeP1AuthorityProtocolError()
