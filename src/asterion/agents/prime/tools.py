"""Private immutable tool accounting for the Asterion-prime session."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from asterion.runtime.protocol import ProtocolError


def _freeze_json(value: object, active: set[int] | None = None) -> object:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ProtocolError("Asterion-prime tool payload is invalid")
        return value
    if active is None:
        active = set()
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ProtocolError("Asterion-prime tool payload is invalid")
        identity = id(value)
        if identity in active:
            raise ProtocolError("Asterion-prime tool payload is invalid")
        active.add(identity)
        try:
            return MappingProxyType(
                {key: _freeze_json(item, active) for key, item in value.items()}
            )
        finally:
            active.remove(identity)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        identity = id(value)
        if identity in active:
            raise ProtocolError("Asterion-prime tool payload is invalid")
        active.add(identity)
        try:
            return tuple(_freeze_json(item, active) for item in value)
        finally:
            active.remove(identity)
    raise ProtocolError("Asterion-prime tool payload is invalid")


def _snapshot_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    failed = False
    frozen: object = None
    try:
        frozen = _freeze_json(dict(value))
    except Exception:
        failed = True
    if failed or not isinstance(frozen, Mapping):
        raise ProtocolError("Asterion-prime tool payload is invalid")
    return frozen


@dataclass(frozen=True, repr=False, slots=True)
class PrimeToolCall:
    call_id: str
    name: str
    arguments: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.call_id) is not str or not self.call_id:
            raise ProtocolError("Asterion-prime tool call is invalid")
        if type(self.name) is not str or not self.name:
            raise ProtocolError("Asterion-prime tool call is invalid")
        if not isinstance(self.arguments, Mapping):
            raise ProtocolError("Asterion-prime tool call is invalid")
        object.__setattr__(self, "arguments", _snapshot_mapping(self.arguments))

    def __repr__(self) -> str:
        return "<PrimeToolCall redacted>"


@dataclass(frozen=True, repr=False, slots=True)
class PrimeToolResult:
    call_id: str
    status: Literal["ok", "error", "uncertain"]
    content: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        if type(self.call_id) is not str or not self.call_id:
            raise ProtocolError("Asterion-prime tool result is invalid")
        if self.status not in {"ok", "error", "uncertain"}:
            raise ProtocolError("Asterion-prime tool result is invalid")
        if type(self.content) is not tuple or any(
            not isinstance(item, Mapping) for item in self.content
        ):
            raise ProtocolError("Asterion-prime tool result is invalid")
        frozen_content: list[Mapping[str, object]] = []
        for item in self.content:
            frozen_content.append(_snapshot_mapping(item))
        object.__setattr__(self, "content", tuple(frozen_content))

    def __repr__(self) -> str:
        return "<PrimeToolResult redacted>"


class PrimeToolLedger:
    """Match each accepted tool call to one certain terminal result."""

    __slots__ = ("_calls", "_max_callbacks", "_results", "_sealed")

    def __init__(self, *, max_callbacks: int) -> None:
        if (
            isinstance(max_callbacks, bool)
            or not isinstance(max_callbacks, int)
            or max_callbacks <= 0
        ):
            raise ValueError("Asterion-prime tool callback limit is invalid")
        self._max_callbacks = max_callbacks
        self._calls: dict[str, PrimeToolCall] = {}
        self._results: dict[str, PrimeToolResult] = {}
        self._sealed = False

    @property
    def callback_count(self) -> int:
        return len(self._calls)

    @property
    def calls(self) -> tuple[PrimeToolCall, ...]:
        return tuple(self._calls.values())

    @property
    def results(self) -> tuple[PrimeToolResult, ...]:
        return tuple(self._results.values())

    def record_call(self, call: PrimeToolCall) -> None:
        if self._sealed:
            raise ProtocolError("Asterion-prime tool ledger is sealed")
        if type(call) is not PrimeToolCall:
            raise ProtocolError("Asterion-prime tool call is invalid")
        if call.call_id in self._calls:
            raise ProtocolError("Asterion-prime emitted a duplicate tool call")
        if len(self._calls) >= self._max_callbacks:
            raise ProtocolError("Asterion-prime tool callback limit exceeded")
        self._calls[call.call_id] = call

    def record_result(self, result: PrimeToolResult) -> None:
        if self._sealed:
            raise ProtocolError("Asterion-prime tool ledger is sealed")
        if type(result) is not PrimeToolResult:
            raise ProtocolError("Asterion-prime tool result is invalid")
        if result.call_id not in self._calls:
            raise ProtocolError("Asterion-prime tool result has no matching call")
        if result.call_id in self._results:
            raise ProtocolError("Asterion-prime emitted a duplicate tool result")
        self._results[result.call_id] = result

    def seal(self) -> None:
        if self._sealed:
            raise ProtocolError("Asterion-prime tool ledger is already sealed")
        if self._calls.keys() != self._results.keys():
            raise ProtocolError("Asterion-prime has an unmatched tool call")
        if any(result.status == "uncertain" for result in self._results.values()):
            raise ProtocolError("Asterion-prime has an uncertain tool effect")
        self._sealed = True


__all__ = ("PrimeToolCall", "PrimeToolLedger", "PrimeToolResult")
