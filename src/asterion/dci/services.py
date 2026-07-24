"""DCI-owned host services with body-free public identities."""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from asterion.services.registry import (
    HostServiceFactoryBinding,
    HostServiceFactoryContext,
    HostServiceRegistryError,
)
from asterion.runtime.working_directory import (
    ProcessDirectoryAuthority,
    ProcessWorkingDirectory,
)
from asterion.runtime.cwd_exec import trusted_script_path


class LocalCorpusServiceError(ValueError):
    """Raised when the selected local corpus authority is unavailable."""


@runtime_checkable
class LocalCorpusService(ProcessDirectoryAuthority, Protocol):
    @property
    def root(self) -> Path:
        raise NotImplementedError

    @property
    def identity_sha256(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True, repr=False)
class _PinnedLocalCorpusService:
    _root: Path
    _descriptor: int
    _identity: tuple[int, int]
    _identity_sha256: str

    def __repr__(self) -> str:
        return "<LocalCorpusService pinned>"

    @property
    def root(self) -> Path:
        self._require_live_identity()
        return self._root

    @property
    def directory_path(self) -> Path:
        return self.root

    @property
    def identity_sha256(self) -> str:
        self._require_live_identity()
        return self._identity_sha256

    def close(self) -> None:
        descriptor = self._descriptor
        if descriptor < 0:
            return
        object.__setattr__(self, "_descriptor", -1)
        try:
            os.close(descriptor)
        except OSError:
            pass

    @contextmanager
    def open_process_working_directory(self):
        self._require_live_identity()
        descriptor = -1
        try:
            descriptor = os.dup(self._descriptor)
            details = os.fstat(descriptor)
            if (details.st_dev, details.st_ino) != self._identity:
                raise LocalCorpusServiceError(
                    "local corpus identity changed"
                )
            if sys.platform == "linux":
                cwd = _linux_process_cwd(descriptor, self._identity)
                command_prefix: tuple[str, ...] = ()
                pass_fds: tuple[int, ...] = ()
                transport_environment = False
            else:
                cwd = "/"
                command_prefix = (
                    sys.executable,
                    "-I",
                    "-S",
                    str(trusted_script_path()),
                    "--fd",
                    str(descriptor),
                )
                pass_fds = (descriptor,)
                transport_environment = True
            working = ProcessWorkingDirectory(
                identity_path=self._root,
                cwd=cwd,
                pass_fds=pass_fds,
                command_prefix=command_prefix,
                transport_environment=transport_environment,
            )
        except LocalCorpusServiceError:
            raise
        except (AttributeError, NotImplementedError, OSError, TypeError):
            raise LocalCorpusServiceError(
                "local corpus process binding is unavailable"
            ) from None
        try:
            yield working
        finally:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass

    def _require_live_identity(self) -> None:
        if self._descriptor < 0:
            raise LocalCorpusServiceError("local corpus service is unavailable")
        try:
            pinned = os.fstat(self._descriptor)
            current = _probe_directory(self._root)
            current_details = os.fstat(current)
        except (
            AttributeError,
            LocalCorpusServiceError,
            NotImplementedError,
            OSError,
            TypeError,
        ):
            raise LocalCorpusServiceError(
                "local corpus identity changed"
            ) from None
        finally:
            if "current" in locals():
                os.close(current)
        if (
            not stat.S_ISDIR(pinned.st_mode)
            or (pinned.st_dev, pinned.st_ino) != self._identity
            or not stat.S_ISDIR(current_details.st_mode)
            or (current_details.st_dev, current_details.st_ino) != self._identity
        ):
            raise LocalCorpusServiceError("local corpus identity changed")


def create_local_corpus_service_factory() -> HostServiceFactoryBinding:
    """Return the exact factory binding for ``corpus.local-root``."""

    return HostServiceFactoryBinding(
        capability_id="corpus.local-root",
        option_names=("root",),
        factory=_open_local_corpus_service,
    )


def create_answer_judge_service_factory() -> HostServiceFactoryBinding:
    """Return Task 6's identity as a structurally loadable fail-closed boundary."""

    return HostServiceFactoryBinding(
        capability_id="evaluation.answer-judge",
        option_names=(),
        factory=_unavailable_answer_judge_service,
    )


@asynccontextmanager
async def _open_local_corpus_service(context: HostServiceFactoryContext):
    if not _secure_local_corpus_available():
        raise LocalCorpusServiceError(
            "secure local corpus service is unavailable"
        )
    if (
        context.capability_id != "corpus.local-root"
        or set(context.options) != {"root"}
    ):
        raise LocalCorpusServiceError("local corpus configuration is invalid")
    raw_root = context.options["root"]
    if type(raw_root) is not str:
        raise LocalCorpusServiceError("local corpus configuration is invalid")
    root = Path(raw_root)
    if (
        not root.is_absolute()
        or str(root) != raw_root
        or any(component in {"", ".", ".."} for component in root.parts[1:])
    ):
        raise LocalCorpusServiceError("local corpus configuration is invalid")
    descriptor = _open_directory(root)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode):
            raise LocalCorpusServiceError("local corpus root is invalid")
        identity = (details.st_dev, details.st_ino)
        digest = hashlib.sha256()
        encoded = os.fsencode(str(root))
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(details.st_dev.to_bytes(16, "big", signed=False))
        digest.update(details.st_ino.to_bytes(16, "big", signed=False))
        service = _PinnedLocalCorpusService(
            _root=root,
            _descriptor=descriptor,
            _identity=identity,
            _identity_sha256=digest.hexdigest(),
        )
    except LocalCorpusServiceError:
        os.close(descriptor)
        raise
    except (AttributeError, NotImplementedError, OSError, TypeError):
        os.close(descriptor)
        raise LocalCorpusServiceError("local corpus root is unavailable") from None
    try:
        yield service
    finally:
        service.close()


@asynccontextmanager
async def _unavailable_answer_judge_service(
    context: HostServiceFactoryContext,
):
    del context
    raise HostServiceRegistryError(
        "answer judge service is unavailable until Task 6"
    )
    yield object()


def _open_directory(path: Path) -> int:
    try:
        return _probe_directory(path)
    except (AttributeError, NotImplementedError, OSError, TypeError):
        raise LocalCorpusServiceError("local corpus root is unavailable") from None


def _secure_local_corpus_available() -> bool:
    try:
        return (
            sys.platform in {"darwin", "linux"}
            and isinstance(os.O_DIRECTORY, int)
            and isinstance(os.O_NOFOLLOW, int)
            and callable(os.dup)
            and callable(os.fstat)
            and os.open in os.supports_dir_fd
            and os.stat in os.supports_dir_fd
            and os.stat in os.supports_follow_symlinks
            and (
                (
                    sys.platform == "linux"
                    and Path(f"/proc/{os.getpid()}/fd").is_dir()
                )
                or (
                    sys.platform == "darwin"
                    and callable(os.fchdir)
                    and callable(os.execvpe)
                    and bool(sys.executable)
                    and trusted_script_path().is_file()
                )
            )
        )
    except (AttributeError, OSError, TypeError):
        return False


def _linux_process_cwd(
    descriptor: int,
    identity: tuple[int, int],
) -> str:
    path = f"/proc/{os.getpid()}/fd/{descriptor}"
    try:
        details = os.stat(path, follow_symlinks=True)
    except (AttributeError, NotImplementedError, OSError, TypeError):
        raise LocalCorpusServiceError(
            "local corpus process binding is unavailable"
        ) from None
    if (
        not stat.S_ISDIR(details.st_mode)
        or (details.st_dev, details.st_ino) != identity
    ):
        raise LocalCorpusServiceError(
            "local corpus process binding is unavailable"
        )
    return path


def _probe_directory(path: Path) -> int:
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptors: list[int] = []
    try:
        current = os.open(path.anchor, flags)
        descriptors.append(current)
        for component in path.parts[1:]:
            current = os.open(component, flags, dir_fd=current)
            descriptors.append(current)
        final = descriptors.pop()
        return final
    except OSError:
        raise
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
