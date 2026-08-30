"""Deterministic provider-free native controller turns."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from asterion.control.providers.native.model import (
    NativeActionResultReference,
    NativeInputReference,
    NativeTurnRequest,
    NativeTurnResult,
)


class NativeTurnError(ValueError):
    """Raised when a native turn script or result is invalid."""

    def __init__(self, *_: object) -> None:
        super().__init__("native turn is unavailable")
        self.__cause__ = None
        self.__context__ = None


class NativeTurnAdapter(Protocol):
    @property
    def adapter_id(self) -> str:
        raise NotImplementedError

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        raise NotImplementedError


class DeterministicNativeTurnAdapter:
    def __init__(
        self,
        scripts: Mapping[str, NativeTurnResult],
        *,
        adapter_id: str = "native.fake-turn/v1",
    ) -> None:
        if not isinstance(scripts, Mapping) or not isinstance(adapter_id, str):
            raise NativeTurnError
        if not adapter_id:
            raise NativeTurnError
        frozen: dict[str, NativeTurnResult] = {}
        for key, result in scripts.items():
            if not isinstance(key, str) or type(result) is not NativeTurnResult:
                raise NativeTurnError
            frozen[key] = result
        self._scripts = MappingProxyType(frozen)
        self._adapter_id = adapter_id

    @property
    def adapter_id(self) -> str:
        return self._adapter_id

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        if type(request) is not NativeTurnRequest:
            raise NativeTurnError
        try:
            result = self._scripts[_turn_script_key(request)]
        except KeyError:
            raise NativeTurnError from None
        if result.turn_id != request.turn_id:
            raise NativeTurnError
        return result

    def __repr__(self) -> str:
        return (
            f"DeterministicNativeTurnAdapter(adapter_id={self._adapter_id!r}, "
            f"scripts={len(self._scripts)!r})"
        )


def _turn_script_key(request: NativeTurnRequest) -> str:
    if type(request) is not NativeTurnRequest:
        raise NativeTurnError
    if request.inputs and request.action_results:
        raise NativeTurnError
    if request.inputs:
        selected_input = request.inputs[0]
        if type(selected_input) is not NativeInputReference:
            raise NativeTurnError
        return f"input:{selected_input.content_ref}"
    if request.action_results:
        result = request.action_results[0]
        if type(result) is not NativeActionResultReference:
            raise NativeTurnError
        return f"action:{result.action_id}:{result.resolution}"
    raise NativeTurnError
