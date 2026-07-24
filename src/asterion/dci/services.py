"""DCI-owned host services with body-free public identities."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import sys
from collections.abc import Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from asterion.dci.judge import (
    JudgeConfig,
    judge_answer_async,
    judge_public_identity,
)
from asterion.immutable import RedactedImmutableMapping
from asterion.runtime.host import CancellationSignal
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


class AnswerJudgeServiceError(RuntimeError):
    """Raised when the selected answer Judge cannot return safe evidence."""


@runtime_checkable
class AnswerJudgeService(Protocol):
    @property
    def public_identity(self) -> Mapping[str, object]:
        raise NotImplementedError

    async def judge(
        self,
        *,
        question: str,
        gold_answer: str,
        predicted_answer: str,
        signal: CancellationSignal | None,
    ) -> Mapping[str, object]:
        raise NotImplementedError


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


@dataclass(frozen=True, repr=False)
class _DciAnswerJudgeService:
    _config: JudgeConfig

    def __repr__(self) -> str:
        return "<AnswerJudgeService configured>"

    @property
    def public_identity(self) -> Mapping[str, object]:
        return RedactedImmutableMapping(judge_public_identity(self._config))

    async def judge(
        self,
        *,
        question: str,
        gold_answer: str,
        predicted_answer: str,
        signal: CancellationSignal | None,
    ) -> Mapping[str, object]:
        if (
            type(question) is not str
            or not question.strip()
            or type(gold_answer) is not str
            or not gold_answer.strip()
            or type(predicted_answer) is not str
            or not predicted_answer.strip()
        ):
            raise AnswerJudgeServiceError("answer judge request is invalid")
        work = asyncio.create_task(
            judge_answer_async(
                config=self._config,
                question=question,
                gold_answer=gold_answer,
                predicted_answer=predicted_answer,
            )
        )
        try:
            while not work.done():
                if signal is not None and signal.cancelled:
                    work.cancel()
                    await _drain_judge(work)
                    raise AnswerJudgeServiceError(
                        "answer judge request was cancelled"
                    )
                await asyncio.wait({work}, timeout=0.05)
            verdict = work.result()
        except asyncio.CancelledError:
            work.cancel()
            await _drain_judge(work)
            raise
        except AnswerJudgeServiceError:
            raise
        except Exception:
            raise AnswerJudgeServiceError("answer judge request failed") from None
        if (
            not isinstance(verdict, Mapping)
            or not isinstance(verdict.get("is_correct"), bool)
            or type(verdict.get("judge_request_fingerprint")) is not str
        ):
            raise AnswerJudgeServiceError("answer judge evidence is invalid")
        return RedactedImmutableMapping(_freeze_judge_mapping(verdict))


def create_local_corpus_service_factory() -> HostServiceFactoryBinding:
    """Return the exact factory binding for ``corpus.local-root``."""

    return HostServiceFactoryBinding(
        capability_id="corpus.local-root",
        option_names=("root",),
        factory=_open_local_corpus_service,
    )


def create_answer_judge_service_factory() -> HostServiceFactoryBinding:
    """Return the exact DCI-owned factory for ``evaluation.answer-judge``."""

    return HostServiceFactoryBinding(
        capability_id="evaluation.answer-judge",
        option_names=(),
        factory=_open_answer_judge_service,
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
async def _open_answer_judge_service(
    context: HostServiceFactoryContext,
):
    if (
        context.provider_id != "dci-agent-lite"
        or context.application_id != "dci.complete-application"
        or context.application_version != "1.0.0"
        or context.capability_id != "evaluation.answer-judge"
        or context.options
    ):
        raise HostServiceRegistryError("answer judge service is unavailable")
    try:
        config = JudgeConfig.from_env()
    except Exception:
        raise HostServiceRegistryError("answer judge service is unavailable") from None
    if not config.api_key:
        raise HostServiceRegistryError("answer judge service is unavailable")
    yield _DciAnswerJudgeService(config)


async def _drain_judge(work: asyncio.Task[object]) -> None:
    while not work.done():
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
        try:
            await asyncio.wait({work})
        except asyncio.CancelledError:
            continue
    try:
        work.result()
    except BaseException:
        pass


def _freeze_judge_mapping(
    value: Mapping[str, object],
) -> Mapping[str, object]:
    return MappingProxyType(
        {str(key): _freeze_judge_value(item) for key, item in value.items()}
    )


def _freeze_judge_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_judge_mapping(value)
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_judge_value(item) for item in value)
    return value


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
