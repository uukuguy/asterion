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
from typing import NoReturn, Protocol, runtime_checkable

from asterion.benchmarks.model import (
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
    public_plan_dict,
)
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
        if self.status not in {"completed", "failed", "cancelled"}:
            _fail("benchmark run result is invalid")
        tasks = tuple(self.tasks)
        if (
            not all(isinstance(task, BenchmarkTaskResult) for task in tasks)
        ):
            _fail("benchmark run result is invalid")
        task_ids = tuple(task.task_id for task in tasks)
        if len(set(task_ids)) != len(task_ids):
            _fail("benchmark run result is invalid")
        object.__setattr__(self, "tasks", tasks)


@runtime_checkable
class BenchmarkEvidenceStore(Protocol):
    def initialize(self, plan: ResolvedBenchmarkPlan) -> None: ...

    def start_task(self, task: ResolvedBenchmarkTask) -> None: ...

    def append_progress(self, event: BenchmarkProgressEvent) -> None: ...

    def finish_task(self, result: BenchmarkTaskResult) -> None: ...

    def finish_run(self, result: BenchmarkRunResult) -> None: ...

    def compatible_completed_tasks(
        self, plan: ResolvedBenchmarkPlan
    ) -> frozenset[str]: ...


class LocalPrivateBenchmarkEvidenceStore:
    """Descriptor-relative private evidence store under one local root."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._plan: ResolvedBenchmarkPlan | None = None
        self._completed_task_ids: tuple[str, ...] = ()
        self._active_task_id: str | None = None
        self._next_sequence = 1
        self._run_finished = False

    def initialize(self, plan: ResolvedBenchmarkPlan) -> None:
        try:
            manifest = _plan_manifest(plan)
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
                        if _json_member_exists(run, "manifest.json"):
                            if _read_json(run, "manifest.json") != manifest:
                                _fail("benchmark evidence resume is invalid")
                        else:
                            _atomic_write_json(run, "manifest.json", manifest)
                        self._load_existing_state(plan, run)
                    finally:
                        os.close(run)
                finally:
                    os.close(runs)
            self._plan = plan
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence is invalid")

    def start_task(self, task: ResolvedBenchmarkTask) -> None:
        try:
            plan = self._require_plan()
            expected_ids = _plan_task_ids(plan)
            if self._run_finished or self._active_task_id is not None:
                _fail("benchmark task lifecycle is invalid")
            if not isinstance(task, ResolvedBenchmarkTask):
                _fail("benchmark task lifecycle is invalid")
            task_id = task.task.task_id
            completed_count = len(self._completed_task_ids)
            if (
                completed_count >= len(expected_ids)
                or task_id != expected_ids[completed_count]
            ):
                _fail("benchmark task lifecycle is invalid")
            self._active_task_id = task_id
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark task lifecycle is invalid")

    def append_progress(self, event: BenchmarkProgressEvent) -> None:
        try:
            if not isinstance(event, BenchmarkProgressEvent):
                _fail("benchmark progress event is invalid")
            plan = self._require_plan()
            if event.task_id is not None and event.task_id not in set(
                _plan_task_ids(plan)
            ):
                _fail("benchmark progress event is invalid")
            if event.sequence != self._next_sequence:
                _fail("benchmark progress event is invalid")
            with _run_fd(self._root, plan) as run:
                progress = _open_required_dir(run, "progress")
                try:
                    _atomic_write_json(
                        progress,
                        f"{event.sequence:06d}.json",
                        _progress_event_dict(event),
                    )
                finally:
                    os.close(progress)
            self._next_sequence += 1
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence is invalid")

    def finish_task(self, result: BenchmarkTaskResult) -> None:
        try:
            plan = self._require_plan()
            _validate_task_result_for_plan(plan, result)
            if self._run_finished or self._active_task_id != result.task_id:
                _fail("benchmark task lifecycle is invalid")
            if result.case_count > plan.case_limit:
                _fail("benchmark task result is invalid")
            with _run_fd(self._root, plan) as run:
                tasks = _open_required_dir(run, "tasks")
                try:
                    task = _open_required_dir(tasks, result.task_id)
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
            self._completed_task_ids = (*self._completed_task_ids, result.task_id)
            self._active_task_id = None
            if result.status != "completed":
                self._run_finished = True
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence is invalid")

    def finish_run(self, result: BenchmarkRunResult) -> None:
        try:
            plan = self._require_plan()
            _validate_run_result_for_plan(plan, result)
            if self._active_task_id is not None:
                _fail("benchmark run result is invalid")
            if tuple(task.task_id for task in result.tasks) != self._completed_task_ids:
                _fail("benchmark run result is invalid")
            with _run_fd(self._root, plan) as run:
                _atomic_write_json(run, "result.json", _run_result_dict(result))
            self._run_finished = True
        except BenchmarkEvidenceError:
            raise
        except Exception:
            _fail("benchmark evidence is invalid")

    def compatible_completed_tasks(
        self, plan: ResolvedBenchmarkPlan
    ) -> frozenset[str]:
        try:
            expected_manifest = _plan_manifest(plan)
            if not _root_exists(self._root):
                return frozenset()
            with _run_fd(self._root, plan, verify_manifest=False) as run:
                manifest = _read_json(run, "manifest.json")
                if manifest != expected_manifest:
                    _fail("benchmark evidence resume is invalid")
                completed = _completed_prefix_from_evidence(plan, run)
                _load_optional_run_result(plan, run, completed)
                return frozenset(completed)
        except BenchmarkEvidenceError:
            raise
        except FileNotFoundError:
            return frozenset()
        except Exception:
            _fail("benchmark evidence resume is invalid")

    def _require_plan(self) -> ResolvedBenchmarkPlan:
        if self._plan is None:
            _fail("benchmark evidence is uninitialized")
        return self._plan

    def _load_existing_state(self, plan: ResolvedBenchmarkPlan, run_fd: int) -> None:
        completed = _completed_prefix_from_evidence(plan, run_fd)
        result = _load_optional_run_result(plan, run_fd, completed)
        self._completed_task_ids = completed
        self._active_task_id = None
        self._next_sequence = _next_progress_sequence(run_fd, plan)
        self._run_finished = result is not None and result.status in {
            "completed",
            "failed",
            "cancelled",
        }


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
                    next_fd = _open_required_dir(fd, part)
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
        runs = _open_required_dir(root_fd, "runs")
        try:
            run = _open_required_dir(runs, plan.run_id)
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


def _open_required_dir(parent_fd: int, name: str) -> int:
    _member_name(name)
    try:
        return _open_existing_dir(parent_fd, name)
    except BenchmarkEvidenceError:
        raise
    except FileNotFoundError:
        raise
    except OSError as error:
        if error.errno == errno.ENOENT:
            raise FileNotFoundError from None
        _fail("benchmark evidence directory is invalid")
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
    _reject_existing_member(dir_fd, name)
    temp_name = f".{name}.tmp-{uuid.uuid4().hex}"
    temp_fd = -1
    temp_created = False
    try:
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_CLOEXEC_INT(),
            0o600,
            dir_fd=dir_fd,
        )
        temp_created = True
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
        if temp_created:
            try:
                os.unlink(temp_name, dir_fd=dir_fd)
            except OSError:
                pass


def _reject_existing_member(dir_fd: int, name: str) -> None:
    try:
        fd = os.open(name, _file_flags(), dir_fd=dir_fd)
    except OSError as error:
        if error.errno == errno.ENOENT:
            return
        _fail("benchmark evidence file is invalid")
    os.close(fd)
    _fail("benchmark evidence file is invalid")


def _json_member_exists(dir_fd: int, name: str) -> bool:
    try:
        fd = os.open(name, _file_flags(), dir_fd=dir_fd)
    except OSError as error:
        if error.errno == errno.ENOENT:
            return False
        _fail("benchmark evidence file is invalid")
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode):
            _fail("benchmark evidence file is invalid")
    finally:
        os.close(fd)
    return True


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
        value = json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except Exception:
        _fail("benchmark evidence file is invalid")
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        _fail("benchmark evidence file is invalid")
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            _fail("benchmark evidence file is invalid")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> NoReturn:
    del value
    _fail("benchmark evidence file is invalid")


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
        written = os.write(fd, data[total:])
        if written <= 0:
            _fail("benchmark evidence file is invalid")
        total += written


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
    if set(value) != {"status", "tasks"}:
        _fail("benchmark evidence resume is invalid")
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
    if set(value) != {"artifact_ids", "case_count", "status", "task_id"}:
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


def _progress_event_from_json(value: Mapping[str, object]) -> BenchmarkProgressEvent:
    if set(value) not in ({"sequence", "status"}, {"sequence", "status", "task_id"}):
        _fail("benchmark evidence resume is invalid")
    sequence = value.get("sequence")
    status = value.get("status")
    task_id = value.get("task_id")
    if (
        type(sequence) is not int
        or not isinstance(status, str)
        or (task_id is not None and not isinstance(task_id, str))
    ):
        _fail("benchmark evidence resume is invalid")
    return BenchmarkProgressEvent(sequence=sequence, status=status, task_id=task_id)


def _root_exists(root: Path) -> bool:
    return os.path.lexists(os.path.abspath(os.fspath(root)))


def _plan_task_ids(plan: ResolvedBenchmarkPlan) -> tuple[str, ...]:
    return tuple(task.task.task_id for task in plan.tasks)


def _completed_prefix_from_evidence(
    plan: ResolvedBenchmarkPlan,
    run_fd: int,
) -> tuple[str, ...]:
    task_ids = _plan_task_ids(plan)
    tasks_fd = _open_required_dir(run_fd, "tasks")
    completed: list[str] = []
    stopped = False
    try:
        members = set(os.listdir(tasks_fd))
        if members != set(task_ids):
            _fail("benchmark evidence resume is invalid")
        for task_id in task_ids:
            task_fd = _open_required_dir(tasks_fd, task_id)
            try:
                if not _json_member_exists(task_fd, "result.json"):
                    stopped = True
                    continue
                if stopped:
                    _fail("benchmark evidence resume is invalid")
                result = _task_result_from_json(_read_json(task_fd, "result.json"))
                _validate_task_result_for_plan(plan, result)
                if result.task_id != task_id or result.case_count > plan.case_limit:
                    _fail("benchmark evidence resume is invalid")
                if result.status == "completed":
                    completed.append(task_id)
                    continue
                stopped = True
            finally:
                os.close(task_fd)
    finally:
        os.close(tasks_fd)
    return tuple(completed)


def _load_optional_run_result(
    plan: ResolvedBenchmarkPlan,
    run_fd: int,
    completed: tuple[str, ...],
) -> BenchmarkRunResult | None:
    if not _json_member_exists(run_fd, "result.json"):
        if _has_noncompleted_task_result(plan, run_fd):
            _fail("benchmark evidence resume is invalid")
        return None
    result = _run_result_from_json(_read_json(run_fd, "result.json"))
    _validate_run_result_for_plan(plan, result)
    result_ids = tuple(task.task_id for task in result.tasks)
    persisted = _persisted_task_results(plan, run_fd, result_ids)
    if persisted != result.tasks:
        _fail("benchmark evidence resume is invalid")
    if result.status == "completed":
        if result_ids != _plan_task_ids(plan) or completed != _plan_task_ids(plan):
            _fail("benchmark evidence resume is invalid")
    else:
        completed_in_result = tuple(
            task.task_id for task in result.tasks if task.status == "completed"
        )
        if completed_in_result != completed:
            _fail("benchmark evidence resume is invalid")
    return result


def _has_noncompleted_task_result(plan: ResolvedBenchmarkPlan, run_fd: int) -> bool:
    tasks_fd = _open_required_dir(run_fd, "tasks")
    try:
        for task_id in _plan_task_ids(plan):
            task_fd = _open_required_dir(tasks_fd, task_id)
            try:
                if not _json_member_exists(task_fd, "result.json"):
                    continue
                result = _task_result_from_json(_read_json(task_fd, "result.json"))
                _validate_task_result_for_plan(plan, result)
                if result.status != "completed":
                    return True
            finally:
                os.close(task_fd)
    finally:
        os.close(tasks_fd)
    return False


def _persisted_task_results(
    plan: ResolvedBenchmarkPlan,
    run_fd: int,
    task_ids: tuple[str, ...],
) -> tuple[BenchmarkTaskResult, ...]:
    tasks_fd = _open_required_dir(run_fd, "tasks")
    results: list[BenchmarkTaskResult] = []
    try:
        for task_id in task_ids:
            task_fd = _open_required_dir(tasks_fd, task_id)
            try:
                if not _json_member_exists(task_fd, "result.json"):
                    _fail("benchmark evidence resume is invalid")
                task_result = _task_result_from_json(_read_json(task_fd, "result.json"))
                _validate_task_result_for_plan(plan, task_result)
                results.append(task_result)
            finally:
                os.close(task_fd)
    finally:
        os.close(tasks_fd)
    return tuple(results)


def _next_progress_sequence(run_fd: int, plan: ResolvedBenchmarkPlan) -> int:
    progress_fd = _open_required_dir(run_fd, "progress")
    try:
        names = sorted(os.listdir(progress_fd))
        expected = 1
        for name in names:
            if re.fullmatch(r"[0-9]{6}\.json", name) is None:
                _fail("benchmark evidence resume is invalid")
            event = _progress_event_from_json(_read_json(progress_fd, name))
            if (
                event.sequence != expected
                or name != f"{event.sequence:06d}.json"
                or (event.task_id is not None and event.task_id not in _plan_task_ids(plan))
            ):
                _fail("benchmark evidence resume is invalid")
            expected += 1
        return expected
    finally:
        os.close(progress_fd)


def _validate_task_result_for_plan(
    plan: ResolvedBenchmarkPlan,
    result: BenchmarkTaskResult,
) -> None:
    if not isinstance(result, BenchmarkTaskResult):
        _fail("benchmark task result is invalid")
    if result.task_id not in {task.task.task_id for task in plan.tasks}:
        _fail("benchmark task result is invalid")
    if result.case_count > plan.case_limit:
        _fail("benchmark task result is invalid")


def _validate_run_result_for_plan(
    plan: ResolvedBenchmarkPlan,
    result: BenchmarkRunResult,
) -> None:
    if not isinstance(result, BenchmarkRunResult):
        _fail("benchmark run result is invalid")
    plan_task_ids = _plan_task_ids(plan)
    result_task_ids = tuple(task.task_id for task in result.tasks)
    if result_task_ids != plan_task_ids[: len(result_task_ids)]:
        _fail("benchmark run result is invalid")
    for task in result.tasks:
        _validate_task_result_for_plan(plan, task)
    if result.status == "completed":
        if result_task_ids != plan_task_ids or any(
            task.status != "completed" for task in result.tasks
        ):
            _fail("benchmark run result is invalid")
        return
    if result.status == "failed":
        if not result.tasks or any(
            task.status != "completed" for task in result.tasks[:-1]
        ):
            _fail("benchmark run result is invalid")
        if result.tasks[-1].status != "failed":
            _fail("benchmark run result is invalid")
        return
    if result.status == "cancelled":
        if any(task.status != "completed" for task in result.tasks[:-1]):
            _fail("benchmark run result is invalid")
        if result.tasks and result.tasks[-1].status not in {"completed", "cancelled"}:
            _fail("benchmark run result is invalid")
        return
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
        _fail("benchmark evidence file is invalid")


def _fail(message: str) -> NoReturn:
    raise BenchmarkEvidenceError(message) from None


__all__ = (
    "BenchmarkEvidenceStore",
    "BenchmarkEvidenceError",
    "BenchmarkProgressEvent",
    "BenchmarkRunResult",
    "BenchmarkTaskResult",
    "LocalPrivateBenchmarkEvidenceStore",
)
