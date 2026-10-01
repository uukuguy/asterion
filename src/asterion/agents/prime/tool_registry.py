"""Immutable registration metadata for Prime application tools."""

from __future__ import annotations

from dataclasses import dataclass
import re

from asterion.runtime.protocol import IDENTIFIER, ProtocolError


_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_.:-]{0,255}$")


@dataclass(frozen=True, slots=True)
class PrimeApplicationToolRegistry:
    """Validated names and capability identity for one Prime tool module."""

    module_id: str
    capability_id: str
    tool_names: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.module_id) is not str
            or IDENTIFIER.fullmatch(self.module_id) is None
            or type(self.capability_id) is not str
            or IDENTIFIER.fullmatch(self.capability_id) is None
            or type(self.tool_names) is not tuple
            or not self.tool_names
            or any(
                type(name) is not str or _TOOL_NAME.fullmatch(name) is None
                for name in self.tool_names
            )
            or self.tool_names != tuple(sorted(set(self.tool_names)))
        ):
            raise ProtocolError("Prime application tool registry is invalid")

    @property
    def allowed_tool_names(self) -> tuple[str, ...]:
        return self.tool_names

    def matches(self, module_id: str, capability_id: str) -> bool:
        return (
            type(module_id) is str
            and type(capability_id) is str
            and self.module_id == module_id
            and self.capability_id == capability_id
        )


__all__ = ("PrimeApplicationToolRegistry",)
