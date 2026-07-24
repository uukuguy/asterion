"""Descriptor-backed process working-directory authority contract."""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, repr=False)
class ProcessWorkingDirectory:
    """One process-start token backed by inherited pinned descriptors."""

    identity_path: Path
    cwd: str
    pass_fds: tuple[int, ...]
    command_prefix: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return "<ProcessWorkingDirectory pinned>"


@runtime_checkable
class ProcessDirectoryAuthority(Protocol):
    """Structural authority able to bind a child to one pinned directory."""

    @property
    def directory_path(self) -> Path:
        raise NotImplementedError

    def open_process_working_directory(
        self,
    ) -> AbstractContextManager[ProcessWorkingDirectory]:
        raise NotImplementedError


@contextmanager
def bind_process_working_directory(
    *,
    cwd: Path | None,
    authority: ProcessDirectoryAuthority | None,
):
    """Yield the one directory token valid for the duration of process start."""

    if (cwd is None) == (authority is None):
        raise ValueError("process working directory authority is invalid")
    if authority is None:
        assert cwd is not None
        yield ProcessWorkingDirectory(
            identity_path=cwd,
            cwd=str(cwd),
            pass_fds=(),
        )
        return
    with authority.open_process_working_directory() as working:
        authority_path = authority.directory_path
        if (
            not isinstance(working, ProcessWorkingDirectory)
            or not isinstance(authority_path, Path)
            or working.identity_path != authority_path
            or not working.cwd
            or any(type(item) is not int or item < 0 for item in working.pass_fds)
            or len(set(working.pass_fds)) != len(working.pass_fds)
            or any(type(item) is not str or not item for item in working.command_prefix)
        ):
            raise ValueError("process working directory authority is invalid")
        yield working
