"""Bounded three-prompt Prime SDK gateway for P6."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from .p5_development_gateway import PrimeP5DevelopmentGateway


class PrimeP6DevelopmentGatewayError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P6 development gateway is unavailable")


class PrimeP6DevelopmentGateway(PrimeP5DevelopmentGateway):
    """One reaped bridge session; P6 accepts exactly three prompt transcripts."""

    def __init__(self, *, node_bin: str | os.PathLike[str] | None = None, entrypoint: str | os.PathLike[str] | None = None, deadline_seconds: float = 180.0) -> None:
        try:
            super().__init__(node_bin=node_bin, entrypoint=entrypoint or Path(__file__).resolve().parents[5] / "packages/typescript/prime-gateway/dist/src/p6-development-main.js", deadline_seconds=deadline_seconds)
        except ValueError:
            raise PrimeP6DevelopmentGatewayError() from None

    async def open(self, *, run_id: str, session_id: str, generation: int, **_: object) -> None:
        await super().open(run_id=run_id, session_id=session_id, generation=generation, prime_source_root="/workspace", workspace="/workspace")

    def terminal_witness(self) -> Mapping[str, object]:
        if self._prompts != 3 or self._terminal_witness is None or self._state not in {"open", "closed"}:
            raise PrimeP6DevelopmentGatewayError()
        identity = self._identity
        if type(identity) is not dict:
            raise PrimeP6DevelopmentGatewayError()
        return MappingProxyType({"identity": MappingProxyType(dict(identity)), "cumulative": MappingProxyType({"model_callback_count": 6, "tool_callback_count": 3})})


__all__ = ("PrimeP6DevelopmentGateway", "PrimeP6DevelopmentGatewayError")
