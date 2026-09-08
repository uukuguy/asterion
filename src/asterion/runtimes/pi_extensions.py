"""Exact host-resolved extension bindings for Pi runtimes."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from asterion.immutable import RedactedImmutableMapping


_IDENTITY = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*")


@dataclass(frozen=True, repr=False, slots=True)
class PiExtensionBinding:
    extension_id: str
    path: Path
    capabilities: tuple[str, ...]
    inherited_fds: tuple[int, ...]
    environment: Mapping[str, str]

    def __post_init__(self) -> None:
        if (
            type(self.extension_id) is not str
            or _IDENTITY.fullmatch(self.extension_id) is None
            or not isinstance(self.path, Path)
            or not self.path.is_absolute()
        ):
            raise ValueError("Pi extension binding is invalid")
        try:
            resolved = self.path.resolve(strict=True)
        except OSError:
            raise ValueError("Pi extension binding is invalid") from None
        if resolved != self.path or not self.path.is_file():
            raise ValueError("Pi extension binding is invalid")
        if (
            type(self.capabilities) is not tuple
            or not self.capabilities
            or any(
                type(capability) is not str
                or _IDENTITY.fullmatch(capability) is None
                for capability in self.capabilities
            )
            or tuple(sorted(set(self.capabilities))) != self.capabilities
        ):
            raise ValueError("Pi extension binding is invalid")
        if (
            type(self.inherited_fds) is not tuple
            or any(type(fd) is not int or fd < 3 for fd in self.inherited_fds)
            or tuple(sorted(set(self.inherited_fds))) != self.inherited_fds
        ):
            raise ValueError("Pi extension binding is invalid")
        if not isinstance(self.environment, Mapping):
            raise ValueError("Pi extension binding is invalid")
        environment = dict(self.environment)
        environment_prefix = (
            "ASTERION_"
            + re.sub(r"[.-]", "_", self.extension_id).upper()
            + "_"
        )
        if any(
            type(name) is not str
            or not name.startswith(environment_prefix)
            or re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None
            or type(value) is not str
            or "\x00" in value
            for name, value in environment.items()
        ):
            raise ValueError("Pi extension binding is invalid")
        object.__setattr__(
            self,
            "environment",
            RedactedImmutableMapping(environment),
        )

    def __repr__(self) -> str:
        return "<PiExtensionBinding redacted>"

    def command_args(self) -> tuple[str, str]:
        return ("--extension", str(self.path))

    def preflight(self) -> None:
        """Revalidate process resources immediately before runtime construction."""

        try:
            if self.path.resolve(strict=True) != self.path or not self.path.is_file():
                raise OSError
            for fd in self.inherited_fds:
                os.fstat(fd)
        except OSError:
            raise ValueError("Pi extension binding is unavailable") from None
