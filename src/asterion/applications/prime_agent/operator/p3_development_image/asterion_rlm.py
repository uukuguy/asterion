"""Root-only client for P3's closed local RLM RPC vocabulary."""

from __future__ import annotations

import json
import socket
from typing import Final

_SOCKET: Final = "/run/asterion-rlm/rlm.sock"
_CAP: Final = 4096
_ROLES: Final = frozenset(("implementation", "review"))


class RlmRequestError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("RLM request is unavailable")


def spawn(role: object) -> dict[str, object]:
    return _request({"kind": "spawn", "role": _role(role)})


def wait(role: object) -> dict[str, object]:
    return _request({"kind": "wait", "role": _role(role)})


def follow_up() -> dict[str, object]:
    return _request({"kind": "follow_up"})


def list_children() -> dict[str, object]:
    return _request({"kind": "list"})


def delete(role: object) -> dict[str, object]:
    return _request({"kind": "delete", "role": _role(role)})


def _role(value: object) -> str:
    if type(value) is not str or value not in _ROLES:
        raise RlmRequestError()
    return value


def _request(value: dict[str, object]) -> dict[str, object]:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    if len(encoded) > _CAP:
        raise RlmRequestError()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5.0)
            client.connect(_SOCKET)
            client.sendall(encoded)
            response = _read(client)
        decoded = json.loads(response)
        if type(decoded) is not dict or set(decoded) != {"ok", "result"} or decoded["ok"] is not True or type(decoded["result"]) is not dict:
            raise ValueError
        return decoded["result"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise RlmRequestError() from None


def _read(client: socket.socket) -> bytes:
    data = bytearray()
    while len(data) <= _CAP:
        chunk = client.recv(min(1024, _CAP + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if data.endswith(b"\n"):
            break
    if not data.endswith(b"\n") or len(data) > _CAP:
        raise RlmRequestError()
    return bytes(data[:-1])
