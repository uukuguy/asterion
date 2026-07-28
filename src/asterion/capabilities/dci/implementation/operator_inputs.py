"""Private, operator-supplied DCI benchmark values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType


@dataclass(frozen=True, slots=True, eq=False)
class DciBenchmarkOperatorInputs:
    """Immutable paths and values injected by the DCI benchmark host."""

    dataset_roots: Mapping[str, Path] = field(repr=False)
    corpus_roots: Mapping[str, Path] = field(repr=False)
    private_environment: Mapping[str, str] = field(repr=False)
    amount: Decimal | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.amount is not None and type(self.amount) is not Decimal:
            raise ValueError("DCI benchmark operator input is invalid")
        object.__setattr__(
            self,
            "dataset_roots",
            _path_mapping(self.dataset_roots),
        )
        object.__setattr__(
            self,
            "corpus_roots",
            _path_mapping(self.corpus_roots),
        )
        object.__setattr__(
            self,
            "private_environment",
            _text_mapping(self.private_environment),
        )


def _path_mapping(value: object) -> Mapping[str, Path]:
    if not isinstance(value, Mapping):
        raise ValueError("DCI benchmark operator input is invalid")
    resolved: dict[str, Path] = {}
    for key, path in value.items():
        if (
            not isinstance(key, str)
            or not key
            or not isinstance(path, Path)
        ):
            raise ValueError("DCI benchmark operator input is invalid")
        resolved[key] = Path(path)
    return MappingProxyType(dict(sorted(resolved.items())))


def _text_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("DCI benchmark operator input is invalid")
    resolved: dict[str, str] = {}
    for key, text in value.items():
        if not isinstance(key, str) or not key or not isinstance(text, str):
            raise ValueError("DCI benchmark operator input is invalid")
        resolved[key] = text
    return MappingProxyType(dict(sorted(resolved.items())))
