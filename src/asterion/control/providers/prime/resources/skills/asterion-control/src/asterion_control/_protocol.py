"""Closed private wire protocol for the Asterion Prime skill."""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from collections.abc import Mapping
from types import MappingProxyType


PROTOCOL = "asterion.skill-control/v1"
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 64 * 1024
MAX_INPUT_BYTES = 1024 * 1024

_TOKEN = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_VERSION = re.compile(r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")

_BUDGET_FIELDS = frozenset(
    {
        "controller_tokens",
        "application_tokens",
        "child_tokens",
        "aggregate_tokens",
        "cost_micros",
        "deadline_ms",
    }
)


class AsterionControlError(RuntimeError):
    """A private control request failed before a definitive safe result."""


class AsterionControlUncertainError(AsterionControlError):
    """An effect may have crossed the host boundary before transport failed."""


class _DefinitiveRequestError(AsterionControlError):
    pass


def require_opaque_id(value: object, field: str) -> str:
    if not isinstance(value, str) or _OPAQUE_ID.fullmatch(value) is None:
        raise ValueError(f"{field} is invalid")
    return value


def require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError(f"{field} is invalid")
    return value


def validate_budget(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != _BUDGET_FIELDS:
        raise ValueError("budget is invalid")
    budget: dict[str, int] = {}
    for field in sorted(_BUDGET_FIELDS):
        item = value[field]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ValueError("budget is invalid")
        budget[field] = item
    if budget["deadline_ms"] < 1:
        raise ValueError("budget is invalid")
    return budget


def validate_target(value: object) -> dict[str, str]:
    fields = {"kind", "provider_id", "application_id", "version", "runtime_id"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("application target is invalid")
    if value.get("kind") != "application":
        raise ValueError("application target is invalid")
    target = {field: str(value[field]) for field in fields}
    if (
        _IDENTIFIER.fullmatch(target["provider_id"]) is None
        or _IDENTIFIER.fullmatch(target["application_id"]) is None
        or _VERSION.fullmatch(target["version"]) is None
        or _IDENTIFIER.fullmatch(target["runtime_id"]) is None
    ):
        raise ValueError("application target is invalid")
    return target


def validate_identifiers(value: object, field: str) -> list[str]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} is invalid")
    items = list(value)
    if (
        any(not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None for item in items)
        or items != sorted(set(items))
    ):
        raise ValueError(f"{field} is invalid")
    return items


def effect_payload(
    *,
    idempotency_key: str,
    budget: Mapping[str, int],
    fields: Mapping[str, object],
) -> dict[str, object]:
    return {
        "idempotency_key": require_opaque_id(
            idempotency_key, "idempotency_key"
        ),
        "budget": validate_budget(budget),
        **fields,
    }


def _canonical_line(value: object, *, limit: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError):
        raise ValueError("control request is invalid") from None
    if len(encoded) > limit:
        raise ValueError("control request is invalid")
    return encoded


def _environment() -> tuple[str, str, str]:
    socket_path = os.environ.get("ASTERION_CONTROL_SOCKET")
    token = os.environ.get("ASTERION_CONTROL_TOKEN")
    session_id = os.environ.get("ASTERION_CONTROL_SESSION_ID")
    if (
        not isinstance(socket_path, str)
        or not socket_path
        or not isinstance(token, str)
        or _TOKEN.fullmatch(token) is None
        or not isinstance(session_id, str)
        or _OPAQUE_ID.fullmatch(session_id) is None
    ):
        raise AsterionControlError("Asterion control environment is unavailable")
    return socket_path, token, session_id


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _validate_response(value: object, request_id: str) -> object:
    if not isinstance(value, Mapping):
        raise AsterionControlError("Asterion control response is invalid")
    if (
        value.get("protocol") != PROTOCOL
        or value.get("request_id") != request_id
        or value.get("status") not in {"ok", "error"}
    ):
        raise AsterionControlError("Asterion control response is invalid")
    if value["status"] == "error":
        if set(value) != {"protocol", "request_id", "status", "code"}:
            raise AsterionControlError("Asterion control response is invalid")
        raise _DefinitiveRequestError("Asterion control request was rejected")
    if set(value) != {"protocol", "request_id", "status", "result"}:
        raise AsterionControlError("Asterion control response is invalid")
    return _freeze(value["result"])


async def exchange(
    operation: str,
    payload: Mapping[str, object],
    *,
    effectful: bool,
) -> object:
    socket_path, token, session_id = _environment()
    request_id = f"request-{uuid.uuid4().hex}"
    auth = _canonical_line(
        {
            "protocol": PROTOCOL,
            "type": "authenticate",
            "token": token,
            "session_id": session_id,
        },
        limit=1024,
    )
    request = _canonical_line(
        {
            "protocol": PROTOCOL,
            "request_id": request_id,
            "session_id": session_id,
            "operation": operation,
            "payload": dict(payload),
        },
        limit=MAX_REQUEST_BYTES,
    )
    writer: asyncio.StreamWriter | None = None
    sent = False
    try:
        reader, writer = await asyncio.open_unix_connection(
            socket_path,
            limit=MAX_RESPONSE_BYTES + 1,
        )
        writer.write(auth)
        writer.write(request)
        await writer.drain()
        sent = True
        response_line = await reader.readline()
        if not response_line or len(response_line) > MAX_RESPONSE_BYTES:
            raise AsterionControlError("Asterion control response is invalid")
        if not response_line.endswith(b"\n"):
            raise AsterionControlError("Asterion control response is invalid")
        try:
            response = json.loads(response_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AsterionControlError("Asterion control response is invalid") from None
        return _validate_response(response, request_id)
    except _DefinitiveRequestError:
        raise AsterionControlError("Asterion control request was rejected") from None
    except (ValueError, OSError, asyncio.IncompleteReadError, AsterionControlError):
        if effectful and sent:
            raise AsterionControlUncertainError(
                "Asterion control effect result is uncertain"
            ) from None
        raise AsterionControlError("Asterion control exchange failed") from None
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
