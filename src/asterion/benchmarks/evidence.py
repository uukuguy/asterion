"""Private local benchmark evidence persistence."""

from __future__ import annotations

import errno
import json
import os
import re
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

from asterion.benchmarks.model import ResolvedBenchmarkPlan, public_plan_dict
from asterion.capability_packages import CapabilityPackageRef


_JSON_MAX_BYTES = 1024 * 1024
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_STATUS = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_SECRET_FRAGMENTS = ("secret", "credential", "password", "token", "answer", "prompt")
_O_DIRECTORY = getattr(os, "O_DIRECTORY", None)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", None)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", None)
_SUPPORTS_DIR_FD = getattr(os, "supports_dir_fd", frozenset())
_SUPPORTS_FD = getattr(os, "supports_fd", frozenset())
_SECURE_FD_AVAILABLE = (
    isinstance(_O_DIRECTORY, int)
    and isinstance(_O_NOFOLLOW, int)
    and isinstance(_O_CLOEXEC, int)
    and os.open in _SUPPORTS_DIR_FD
    and os.mkdir in _SUPPORTS_DIR_FD
    and os.unlink in _SUPPORTS_DIR_FD
    and os.listdir in _SUPPORTS_FD
)


class BenchmarkEvidenceError(ValueError):
    """Raised when benchmark evidence cannot be safely persisted or resumed."""


@dataclass(frozen=True, slots=True)
class BenchmarkProgressEvent:
    sequence: int
    status: str
    task_id: str | None = None

    def __post_init__(self) -> None:
        _positive_int(self.sequence)
        _safe_status(self.status)
        if self.task_id is not None:
            _identifier(self.task_id)


@dataclass(frozen=True, slots=True)
class BenchmarkTaskResult:
    task_id: str
    status: str
    case_count: int
    artifact_ids: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        _identifier(self.task_id)
        _terminal_status(self.status)
        _nonnegative_int(self.case_count)
        artifact_ids = tuple(self.artifact_ids)
        if not all(_is_safe_identifier(artifact_id) for artifact_id in artifact_ids):
            _fail("benchmark task result is invalid")
        if tuple(sorted(set(artifact_ids))) != artifact_ids:
            _fail("benchmark task result is invalid")
        object.__setattr__(self, "artifact_ids", artifact_ids)


@dataclass(frozen=True, slots=True)
class BenchmarkRunResult:
    status: str
    tasks: tuple[BenchmarkTaskResult, ...]

    def __post_init__(self) -> None:
        if self.status != "completed":
            _fail("benchmark run result is invalid")
        tasks = tuple(self.tasks)
        if (
            not tasks
            or not all(isinstance(task, BenchmarkTaskResult) for task in tasks)
            or any(task.status != "completed" for task in tasks)
        ):
            _fail("benchmark run result is invalid")
        task_ids = tuple(task.task_id for task in tasks)
        if len(set(task_ids)) != len(task_ids):
            _fail("benchmark run result is invalid")
        object.__setattr__(self, "tasks", tasks)


class LocalPrivateBenchmarkEvidenceStore:
    """Descriptor-relative private evidence store under one local root."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def prepare_run(self, plan: ResolvedBenchmarkPlan) -> None:
        try:
            _plan_manifest(plan)
            with _root_fd(self._root, create=True) as root:
                runs = _ensure_dir(root, "runs")
                try:
                    run = _ensure_dir(runs, plan.run_id)
                    try:
                        progress = _ensure_dir(run, "progress")
                        os.close(progress)
                        tasks = _ensure_dir(run, "tasks")
                        try:
                            for task in plan.tasks:
                                task_fd = _ensure_dir(tasks, task.task.task_id)
                                os.close(task_fd)
                        finally:
                            os.close(tasks)
                        _atomic_write_json(run, "manifest.json", _plan_manifest(plan))
                    finally:
                        os.close(run)
                finally:
                    os.close(runs)
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence is invalid")

    def write_progress(
        self,
        plan: ResolvedBenchmarkPlan,
        event: BenchmarkProgressEvent,
    ) -> None:
        try:
            if not isinstance(event, BenchmarkProgressEvent):
                _fail("benchmark progress event is invalid")
            with _run_fd(self._root, plan) as run:
                progress = _open_dir(run, "progress")
                try:
                    _atomic_write_json(
                        progress,
                        f"{event.sequence:06d}.json",
                        _progress_event_dict(event),
                    )
                finally:
                    os.close(progress)
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence is invalid")

    def write_task_result(
        self,
        plan: ResolvedBenchmarkPlan,
        result: BenchmarkTaskResult,
    ) -> None:
        try:
            _validate_task_result_for_plan(plan, result)
            with _run_fd(self._root, plan) as run:
                tasks = _open_dir(run, "tasks")
                try:
                    task = _open_dir(tasks, result.task_id)
                    try:
                        _atomic_write_json(
                            task,
                            "result.json",
                            _task_result_dict(result),
                        )
                    finally:
                        os.close(task)
                finally:
                    os.close(tasks)
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence is invalid")

    def write_run_result(
        self,
        plan: ResolvedBenchmarkPlan,
        result: BenchmarkRunResult,
    ) -> None:
        try:
            _validate_run_result_for_plan(plan, result)
            with _run_fd(self._root, plan) as run:
                _atomic_write_json(run, "result.json", _run_result_dict(result))
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence is invalid")

    def resume_completed_run(self, plan: ResolvedBenchmarkPlan) -> BenchmarkRunResult:
        try:
            expected_manifest = _plan_manifest(plan)
            with _run_fd(self._root, plan, verify_manifest=False) as run:
                manifest = _read_json(run, "manifest.json")
                if manifest != expected_manifest:
                    _fail("benchmark evidence resume is invalid")
                result = _run_result_from_json(_read_json(run, "result.json"))
                _validate_run_result_for_plan(plan, result)
                return result
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence resume is invalid")


class _FdContext:
    def __init__(self, fd: int) -> None:
        self._fd = fd

    def __enter__(self) -> int:
        return self._fd

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        os.close(self._fd)


def _root_fd(root: Path, *, create: bool) -> _FdContext:
    if not _SECURE_FD_AVAILABLE:
        _fail("secure benchmark evidence storage is unavailable")
    try:
        path = Path(os.path.abspath(os.fspath(root)))
        if not path.is_absolute():
            _fail("benchmark evidence root is invalid")
        parts = path.parts
        fd = _open_absolute_anchor(parts)
        try:
            for part in parts[1:]:
                if create:
                    next_fd = _ensure_dir(fd, part)
                else:
                    next_fd = _open_dir(fd, part)
                os.close(fd)
                fd = next_fd
        except Exception:
            os.close(fd)
            raise
        return _FdContext(fd)
    except BenchmarkEvidenceError:
        raise
    except Exception:
        _fail("benchmark evidence root is invalid")


def _run_fd(
    root: Path,
    plan: ResolvedBenchmarkPlan,
    *,
    verify_manifest: bool = True,
) -> _FdContext:
    _plan_manifest(plan)
    with _root_fd(root, create=False) as root_fd:
        runs = _open_dir(root_fd, "runs")
        try:
            run = _open_dir(runs, plan.run_id)
        finally:
            os.close(runs)
        if verify_manifest and _read_json(run, "manifest.json") != _plan_manifest(plan):
            os.close(run)
            _fail("benchmark evidence resume is invalid")
        return _FdContext(run)


def _open_absolute_anchor(parts: tuple[str, ...]) -> int:
    if not parts or parts[0] != "/":
        _fail("benchmark evidence root is invalid")
    return os.open("/", _directory_flags())


def _ensure_dir(parent_fd: int, name: str) -> int:
    _member_name(name)
    try:
        return _open_dir(parent_fd, name)
    except BenchmarkEvidenceError:
        raise
    except Exception:
        _fail("benchmark evidence directory is invalid")


def _open_dir(parent_fd: int, name: str) -> int:
    _member_name(name)
    try:
        return _open_existing_dir(parent_fd, name)
    except BenchmarkEvidenceError:
        raise
    except OSError as error:
        if error.errno != errno.ENOENT:
            _fail("benchmark evidence directory is invalid")
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        fd = _open_existing_dir(parent_fd, name)
        _fsync_dir(parent_fd)
        return fd
    except Exception:
        _fail("benchmark evidence directory is invalid")


def _open_existing_dir(parent_fd: int, name: str) -> int:
    fd = -1
    try:
        fd = os.open(name, _directory_flags(), dir_fd=parent_fd)
        details = os.fstat(fd)
        if not stat.S_ISDIR(details.st_mode):
            _fail("benchmark evidence directory is invalid")
        return fd
    except Exception:
        if fd >= 0:
            os.close(fd)
        raise


def _atomic_write_json(
    dir_fd: int,
    name: str,
    value: Mapping[str, object],
) -> None:
    _member_name(name)
    data = _canonical_json(value)
    _reject_existing_special(dir_fd, name)
    temp_name = f".{name}.tmp-{uuid.uuid4().hex}"
    temp_fd = -1
    try:
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC_INT(),
            0o600,
            dir_fd=dir_fd,
        )
        _write_all(temp_fd, data)
        os.fsync(temp_fd)
        details = os.fstat(temp_fd)
        if not stat.S_ISREG(details.st_mode):
            _fail("benchmark evidence file is invalid")
        os.close(temp_fd)
        temp_fd = -1
        os.replace(temp_name, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
        _verify_replaced_file(dir_fd, name, data)
        _fsync_dir(dir_fd)
    except BenchmarkEvidenceError:
        raise
    except Exception:
        _fail("benchmark evidence file is invalid")
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        try:
            os.unlink(temp_name, dir_fd=dir_fd)
        except OSError:
            pass


def _reject_existing_special(dir_fd: int, name: str) -> None:
    try:
        fd = os.open(name, _file_flags(), dir_fd=dir_fd)
    except OSError as error:
        if error.errno == errno.ENOENT:
            return
        _fail("benchmark evidence file is invalid")
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            _fail("benchmark evidence file is invalid")
    finally:
        os.close(fd)


def _verify_replaced_file(dir_fd: int, name: str, expected: bytes) -> None:
    fd = os.open(name, _file_flags(), dir_fd=dir_fd)
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size != len(expected):
            _fail("benchmark evidence file is invalid")
        if _read_fd(fd, len(expected)) != expected:
            _fail("benchmark evidence file is invalid")
    finally:
        os.close(fd)


def _read_json(dir_fd: int, name: str) -> Mapping[str, object]:
    _member_name(name)
    try:
        fd = os.open(name, _file_flags(), dir_fd=dir_fd)
    except Exception:
        _fail("benchmark evidence file is invalid")
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size > _JSON_MAX_BYTES:
            _fail("benchmark evidence file is invalid")
        data = _read_fd(fd, min(details.st_size, _JSON_MAX_BYTES))
    finally:
        os.close(fd)
    try:
        value = json.loads(data.decode("utf-8", errors="strict"))
    except Exception:
        _fail("benchmark evidence file is invalid")
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _fail("benchmark evidence file is invalid")
    return value


def _read_fd(fd: int, expected_size: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(65536, _JSON_MAX_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _JSON_MAX_BYTES:
            _fail("benchmark evidence file is invalid")
    data = b"".join(chunks)
    if len(data) != expected_size:
        _fail("benchmark evidence file is invalid")
    return data


def _write_all(fd: int, data: bytes) -> None:
    total = 0
    while total < len(data):
        total += os.write(fd, data[total:])


def _canonical_json(value: Mapping[str, object]) -> bytes:
    data = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(data) > _JSON_MAX_BYTES:
        _fail("benchmark evidence file is invalid")
    return data


def _plan_manifest(plan: ResolvedBenchmarkPlan) -> Mapping[str, object]:
    if not isinstance(plan, ResolvedBenchmarkPlan):
        _fail("benchmark evidence plan is invalid")
    value = public_plan_dict(plan)
    value["package_locks"] = [
        {
            "package": _package_selector(entry.package_ref),
            "payload_sha256": entry.payload_sha256,
            "source_id": entry.source_id,
        }
        for lock in plan.package_locks
        for entry in lock.entries
    ]
    return value


def _progress_event_dict(event: BenchmarkProgressEvent) -> Mapping[str, object]:
    value: dict[str, object] = {
        "sequence": event.sequence,
        "status": event.status,
    }
    if event.task_id is not None:
        value["task_id"] = event.task_id
    return value


def _task_result_dict(result: BenchmarkTaskResult) -> Mapping[str, object]:
    return {
        "task_id": result.task_id,
        "status": result.status,
        "case_count": result.case_count,
        "artifact_ids": list(result.artifact_ids),
    }


def _run_result_dict(result: BenchmarkRunResult) -> Mapping[str, object]:
    return {
        "status": result.status,
        "tasks": [_task_result_dict(task) for task in result.tasks],
    }


def _run_result_from_json(value: Mapping[str, object]) -> BenchmarkRunResult:
    status = value.get("status")
    tasks = value.get("tasks")
    if not isinstance(status, str) or not isinstance(tasks, list):
        _fail("benchmark evidence resume is invalid")
    return BenchmarkRunResult(
        status=status,
        tasks=tuple(_task_result_from_json(task) for task in tasks),
    )


def _task_result_from_json(value: object) -> BenchmarkTaskResult:
    if not isinstance(value, Mapping):
        _fail("benchmark evidence resume is invalid")
    task_id = value.get("task_id")
    status = value.get("status")
    case_count = value.get("case_count")
    artifact_ids = value.get("artifact_ids")
    if (
        not isinstance(task_id, str)
        or not isinstance(status, str)
        or type(case_count) is not int
        or not isinstance(artifact_ids, list)
        or not all(isinstance(artifact_id, str) for artifact_id in artifact_ids)
    ):
        _fail("benchmark evidence resume is invalid")
    return BenchmarkTaskResult(
        task_id=task_id,
        status=status,
        case_count=case_count,
        artifact_ids=tuple(artifact_ids),
    )


def _validate_task_result_for_plan(
    plan: ResolvedBenchmarkPlan,
    result: BenchmarkTaskResult,
) -> None:
    if not isinstance(result, BenchmarkTaskResult):
        _fail("benchmark task result is invalid")
    if result.task_id not in {task.task.task_id for task in plan.tasks}:
        _fail("benchmark task result is invalid")


def _validate_run_result_for_plan(
    plan: ResolvedBenchmarkPlan,
    result: BenchmarkRunResult,
) -> None:
    if not isinstance(result, BenchmarkRunResult):
        _fail("benchmark run result is invalid")
    if tuple(task.task_id for task in result.tasks) != tuple(
        task.task.task_id for task in plan.tasks
    ):
        _fail("benchmark run result is invalid")


def _directory_flags() -> int:
    if not _SECURE_FD_AVAILABLE:
        _fail("secure benchmark evidence storage is unavailable")
    return os.O_RDONLY | _O_DIRECTORY_INT() | _O_NOFOLLOW_INT() | _O_CLOEXEC_INT()


def _file_flags() -> int:
    if not _SECURE_FD_AVAILABLE:
        _fail("secure benchmark evidence storage is unavailable")
    return os.O_RDONLY | _O_NOFOLLOW_INT() | _O_CLOEXEC_INT()


def _O_DIRECTORY_INT() -> int:
    if not isinstance(_O_DIRECTORY, int):
        _fail("secure benchmark evidence storage is unavailable")
    return _O_DIRECTORY


def _O_NOFOLLOW_INT() -> int:
    if not isinstance(_O_NOFOLLOW, int):
        _fail("secure benchmark evidence storage is unavailable")
    return _O_NOFOLLOW


def _O_CLOEXEC_INT() -> int:
    if not isinstance(_O_CLOEXEC, int):
        _fail("secure benchmark evidence storage is unavailable")
    return _O_CLOEXEC


def _member_name(name: str) -> None:
    if (
        type(name) is not str
        or name in {"", ".", ".."}
        or "/" in name
        or "\\" in name
    ):
        _fail("benchmark evidence member is invalid")


def _identifier(value: object) -> None:
    if not _is_safe_identifier(value):
        _fail("benchmark evidence identifier is invalid")


def _safe_status(value: object) -> None:
    if not _is_safe_status(value):
        _fail("benchmark progress event is invalid")


def _terminal_status(value: object) -> None:
    if value not in {"completed", "failed", "cancelled"}:
        _fail("benchmark task result is invalid")


def _positive_int(value: object) -> None:
    if type(value) is not int or value < 1:
        _fail("benchmark progress event is invalid")


def _nonnegative_int(value: object) -> None:
    if type(value) is not int or value < 0:
        _fail("benchmark task result is invalid")


def _is_safe_identifier(value: object) -> bool:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        return False
    lowered = value.lower()
    return not any(fragment in lowered for fragment in _SECRET_FRAGMENTS)


def _is_safe_status(value: object) -> bool:
    if type(value) is not str or _STATUS.fullmatch(value) is None:
        return False
    lowered = value.lower()
    return not any(fragment in lowered for fragment in _SECRET_FRAGMENTS)


def _package_selector(ref: CapabilityPackageRef) -> str:
    return f"{ref.package_id}@{ref.version}"


def _fsync_dir(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError:
        pass


def _fail(message: str) -> NoReturn:
    raise BenchmarkEvidenceError(message) from None


__all__ = (
    "BenchmarkEvidenceError",
    "BenchmarkProgressEvent",
    "BenchmarkRunResult",
    "BenchmarkTaskResult",
    "LocalPrivateBenchmarkEvidenceStore",
)
