"""P3 private gateway with the closed recursive-operation vocabulary."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .p2_development_gateway import PrimeP2DevelopmentGateway

_KINDS = frozenset({"rlm.spawn", "rlm.wait", "rlm.follow_up", "rlm.list", "rlm.delete"})


class PrimeP3DevelopmentGatewayError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P3 development gateway is unavailable")


class PrimeP3DevelopmentGateway(PrimeP2DevelopmentGateway):
    """P3 uses the P1 transport mechanics but only five nested RLM commands."""
    def __init__(self, **kwargs: object) -> None:
        try:
            super().__init__(**kwargs)
            self._protocol = "asterion.prime-p3-development-gateway/v1"
            self._nested_command_kinds = _KINDS
            if kwargs.get("entrypoint") is None:
                self._entrypoint = (self._entrypoint[0], str(Path(__file__).resolve().parents[5] / "packages/typescript/prime-gateway/dist/src/p3-development-main.js"))
        except BaseException:
            raise PrimeP3DevelopmentGatewayError() from None

    async def request_nested(self, kind: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        try:
            return await super().request_nested(kind, payload)
        except BaseException:
            raise PrimeP3DevelopmentGatewayError() from None


__all__ = ("PrimeP3DevelopmentGateway", "PrimeP3DevelopmentGatewayError")
