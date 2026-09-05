"""Private role-partitioned P3 provider admission counters."""

from __future__ import annotations
from types import MappingProxyType
from .p3_development_workload import P3_ROLE_MODEL_CALLBACKS


class PrimeP3DevelopmentSdkProviderError(ValueError):
    def __init__(self, *_: object) -> None:
        super().__init__("prime P3 development SDK provider is unavailable")


class PrimeP3DevelopmentSdkProvider:
    def __init__(self) -> None:
        self._calls = {"root": 0, "implementation": 0, "review": 0}
        self._histories = {"root": [], "implementation": [], "review": []}

    def admit(self, role: object, body: object) -> None:
        if (
            role not in P3_ROLE_MODEL_CALLBACKS
            or type(body) is not bytes
            or not body
            or self._calls[role] >= P3_ROLE_MODEL_CALLBACKS[role]
        ):
            raise PrimeP3DevelopmentSdkProviderError()
        self._calls[role] += 1
        self._histories[role].append(bytes(body))

    @property
    def calls(self):
        return MappingProxyType(dict(self._calls))

    def terminal(self) -> bool:
        return self._calls == dict(P3_ROLE_MODEL_CALLBACKS)

    @property
    def histories(self):
        return MappingProxyType(
            {role: tuple(values) for role, values in self._histories.items()}
        )

    def __repr__(self) -> str:
        return "PrimeP3DevelopmentSdkProvider(redacted)"


__all__ = ("PrimeP3DevelopmentSdkProvider", "PrimeP3DevelopmentSdkProviderError")
