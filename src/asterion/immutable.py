"""Small immutable value helpers shared across framework boundaries."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Generic, TypeVar


_Value = TypeVar("_Value")


class RedactedImmutableMapping(Mapping[str, _Value], Generic[_Value]):
    """Immutable mapping whose representation never renders stored values."""

    def __init__(self, values: Mapping[str, _Value]) -> None:
        self._values = MappingProxyType(dict(values))

    def __getitem__(self, key: str) -> _Value:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Mapping) and dict(self.items()) == dict(other.items())

    def __repr__(self) -> str:
        return "<immutable redacted mapping>"
