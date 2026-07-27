"""Private descriptor-bound evidence for generic benchmark execution."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from asterion.benchmarks.model import (
    ResolvedBenchmarkPlan,
    ResolvedBenchmarkTask,
)


_EVIDENCE_SCHEMA = "asterion.benchmark-evidence/v1"
_EVIDENCE_NAME = "evidence.json"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_MEMBER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SELECTOR = re.compile(
    r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*@"
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)$"
)
_PROGRESS_PHASES = frozenset({"preparing", "executing", "finalizing"})
_TASK_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled"}
)
_RUN_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled"}
)
_RUN_STATUSES = _RUN_TERMINAL_STATUSES | {"initialized", "running"}
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_READ_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_WRITE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_MAX_EVIDENCE_BYTES = 64 * 1024 * 1024


class BenchmarkEvidenceError(RuntimeError):
    """Stable path- and body-free evidence failure."""


@dataclass(frozen=True, slots=True)
class BenchmarkProgressEvent:
    """One allowlisted progress descriptor with a private runtime payload."""

    task_id: str
    sequence: int
    phase: str
    completed_cases: int
    total_cases: int
    content_digest: str | None
    private_payload: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not _identifier(self.task_id)
            or type(self.sequence) is not int
            or self.sequence <= 0
            or self.phase not in _PROGRESS_PHASES
            or type(self.completed_cases) is not int
            or self.completed_cases < 0
            or type(self.total_cases) is not int
            or self.total_cases <= 0
            or self.completed_cases > self.total_cases
            or (
                self.content_digest is not None
                and not _digest(self.content_digest)
            )
        ):
            raise ValueError("benchmark progress event is invalid")


@dataclass(frozen=True, slots=True)
class BenchmarkTaskResult:
    """One terminal task descriptor with private result material excluded."""

    task_id: str
    status: str
    completed_cases: int
    content_digests: tuple[str, ...]
    private_payload: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        digests = _digest_tuple(
            self.content_digests,
            "benchmark task result is invalid",
        )
        if (
            not _identifier(self.task_id)
            or self.status not in _TASK_TERMINAL_STATUSES
            or type(self.completed_cases) is not int
            or self.completed_cases < 0
        ):
            raise ValueError("benchmark task result is invalid")
        object.__setattr__(self, "content_digests", digests)


@dataclass(frozen=True, slots=True)
class BenchmarkRunResult:
    """One terminal run descriptor with private result material excluded."""

    run_id: str
    status: str
    completed_task_ids: tuple[str, ...]
    content_digests: tuple[str, ...]
    private_payload: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        task_ids = _string_tuple(
            self.completed_task_ids,
            "benchmark run result is invalid",
        )
        digests = _digest_tuple(
            self.content_digests,
            "benchmark run result is invalid",
        )
        if (
            not _member_name(self.run_id)
            or self.status not in _RUN_TERMINAL_STATUSES
            or any(not _identifier(task_id) for task_id in task_ids)
            or len(set(task_ids)) != len(task_ids)
        ):
            raise ValueError("benchmark run result is invalid")
        object.__setattr__(self, "completed_task_ids", task_ids)
        object.__setattr__(self, "content_digests", digests)


@runtime_checkable
class BenchmarkEvidenceStore(Protocol):
    """Injected benchmark evidence boundary consumed by the runner."""

    def initialize(self, plan: ResolvedBenchmarkPlan) -> None: ...

    def start_task(self, task: ResolvedBenchmarkTask) -> None: ...

    def append_progress(self, event: BenchmarkProgressEvent) -> None: ...

    def finish_task(self, result: BenchmarkTaskResult) -> None: ...

    def finish_run(self, result: BenchmarkRunResult) -> None: ...

    def compatible_completed_tasks(
        self, plan: ResolvedBenchmarkPlan
    ) -> frozenset[str]: ...


@dataclass(slots=True)
class _DirectoryBinding:
    path: Path
    descriptor: int
    identity: tuple[int, int]
    private: bool
    parent: _DirectoryBinding | None = None
    name: str | None = None

    def close(self) -> None:
        if self.descriptor < 0:
            return
        try:
            os.close(self.descriptor)
        except OSError:
            pass
        self.descriptor = -1


class LocalPrivateBenchmarkEvidenceStore:
    """Local evidence rooted in private no-follow directory descriptors."""

    def __init__(self, evidence_root: Path) -> None:
        _require_descriptor_primitives()
        try:
            root = Path(evidence_root)
        except TypeError:
            raise BenchmarkEvidenceError(
                "benchmark evidence root is invalid"
            ) from None
        if not root.is_absolute():
            root = Path.cwd() / root
        root = Path(os.path.normpath(root))
        if not _member_name(root.name):
            raise BenchmarkEvidenceError("benchmark evidence root is invalid")
        self._root = root
        self._run_id: str | None = None

    def initialize(self, plan: ResolvedBenchmarkPlan) -> None:
        identity = _plan_identity(plan)
        self._assert_run_selection(plan.plan.run_id)
        with self._open_run(plan.plan.run_id, create=True) as run:
            document = _read_document_if_present(run)
            if document is None:
                _atomic_write(run, _initial_document(plan, identity))
            else:
                _validate_document(document)
                _assert_compatible(document, plan, identity)
        self._bind_run(plan.plan.run_id)

    def start_task(self, task: ResolvedBenchmarkTask) -> None:
        if not isinstance(task, ResolvedBenchmarkTask):
            raise BenchmarkEvidenceError(
                "benchmark evidence update is invalid"
            )
        run_id = self._selected_run()
        with self._open_run(run_id, create=False) as run:
            document = _load_document(run)
            if document["status"] in _RUN_TERMINAL_STATUSES:
                raise BenchmarkEvidenceError(
                    "benchmark evidence transition is invalid"
                )
            ordinal = task.planned.ordinal
            task_id = task.planned.task.task_id
            row = _task_row(document, ordinal, task_id)
            if row["status"] == "running":
                return
            if row["status"] != "pending" or any(
                previous["status"] != "completed"
                for previous in document["tasks"][: ordinal - 1]
            ):
                raise BenchmarkEvidenceError(
                    "benchmark evidence transition is invalid"
                )
            row["status"] = "running"
            document["status"] = "running"
            _persist_document(run, document)

    def append_progress(self, event: BenchmarkProgressEvent) -> None:
        if not isinstance(event, BenchmarkProgressEvent):
            raise BenchmarkEvidenceError(
                "benchmark evidence update is invalid"
            )
        run_id = self._selected_run()
        with self._open_run(run_id, create=False) as run:
            document = _load_document(run)
            row = _task_row_by_id(document, event.task_id)
            progress = row["progress"]
            if (
                document["status"] != "running"
                or row["status"] != "running"
                or event.sequence != len(progress) + 1
                or event.total_cases != document["identity"]["case_limit"]
                or (
                    progress
                    and event.completed_cases
                    < progress[-1]["completed_cases"]
                )
            ):
                raise BenchmarkEvidenceError(
                    "benchmark evidence transition is invalid"
                )
            progress.append(_progress_projection(event))
            _persist_document(run, document)

    def finish_task(self, result: BenchmarkTaskResult) -> None:
        if not isinstance(result, BenchmarkTaskResult):
            raise BenchmarkEvidenceError(
                "benchmark evidence update is invalid"
            )
        run_id = self._selected_run()
        with self._open_run(run_id, create=False) as run:
            document = _load_document(run)
            row = _task_row_by_id(document, result.task_id)
            if (
                document["status"] != "running"
                or row["status"] != "running"
                or result.completed_cases
                > document["identity"]["case_limit"]
            ):
                raise BenchmarkEvidenceError(
                    "benchmark evidence transition is invalid"
                )
            row["status"] = result.status
            row["result"] = _task_result_projection(result)
            _persist_document(run, document)

    def finish_run(self, result: BenchmarkRunResult) -> None:
        if not isinstance(result, BenchmarkRunResult):
            raise BenchmarkEvidenceError(
                "benchmark evidence update is invalid"
            )
        run_id = self._selected_run()
        if result.run_id != run_id:
            raise BenchmarkEvidenceError(
                "benchmark evidence update is invalid"
            )
        with self._open_run(run_id, create=False) as run:
            document = _load_document(run)
            completed = tuple(
                row["task_id"]
                for row in document["tasks"]
                if row["status"] == "completed"
            )
            statuses = tuple(row["status"] for row in document["tasks"])
            if (
                document["run_id"] != result.run_id
                or document["status"] in _RUN_TERMINAL_STATUSES
                or completed != result.completed_task_ids
                or (
                    result.status == "completed"
                    and any(status != "completed" for status in statuses)
                )
                or (
                    result.status == "failed"
                    and (
                        "failed" not in statuses
                        or "cancelled" in statuses
                    )
                )
                or (
                    result.status == "cancelled"
                    and (
                        "failed" in statuses
                        or "running" in statuses
                    )
                )
            ):
                raise BenchmarkEvidenceError(
                    "benchmark evidence transition is invalid"
                )
            document["status"] = result.status
            document["run_result"] = _run_result_projection(result)
            _persist_document(run, document)

    def compatible_completed_tasks(
        self, plan: ResolvedBenchmarkPlan
    ) -> frozenset[str]:
        identity = _plan_identity(plan)
        self._assert_run_selection(plan.plan.run_id)
        with self._open_run(plan.plan.run_id, create=False) as run:
            document = _load_document(run)
            _assert_compatible(document, plan, identity)
            completed = frozenset(
                row["task_id"]
                for row in document["tasks"]
                if row["status"] == "completed"
            )
        self._bind_run(plan.plan.run_id)
        return completed

    def _bind_run(self, run_id: str) -> None:
        self._assert_run_selection(run_id)
        self._run_id = run_id

    def _assert_run_selection(self, run_id: str) -> None:
        if self._run_id is not None and self._run_id != run_id:
            raise BenchmarkEvidenceError(
                "benchmark evidence run identity is ambiguous"
            )

    def _selected_run(self) -> str:
        if self._run_id is None:
            raise BenchmarkEvidenceError(
                "benchmark evidence is unavailable"
            )
        return self._run_id

    @contextmanager
    def _open_run(
        self,
        run_id: str,
        *,
        create: bool,
    ) -> Iterator[_DirectoryBinding]:
        if not _member_name(run_id):
            raise BenchmarkEvidenceError(
                "benchmark evidence run identity is invalid"
            )
        parent: _DirectoryBinding | None = None
        root: _DirectoryBinding | None = None
        run: _DirectoryBinding | None = None
        try:
            parent = _open_parent(self._root.parent)
            root = _open_private_child(
                parent,
                self._root.name,
                create=create,
            )
            run = _open_private_child(root, run_id, create=create)
            yield run
        finally:
            if run is not None:
                run.close()
            if root is not None:
                root.close()
            if parent is not None:
                parent.close()


def _require_descriptor_primitives() -> None:
    required = (os.open, os.mkdir, os.stat, os.unlink)
    if (
        not getattr(os, "O_DIRECTORY", 0)
        or not getattr(os, "O_NOFOLLOW", 0)
        or any(function not in os.supports_dir_fd for function in required)
        or os.stat not in os.supports_follow_symlinks
    ):
        raise BenchmarkEvidenceError(
            "benchmark evidence filesystem is unsupported"
        )


def _open_parent(path: Path) -> _DirectoryBinding:
    descriptor = -1
    try:
        canonical = path.resolve(strict=True)
        metadata = canonical.lstat()
        if not stat.S_ISDIR(metadata.st_mode):
            raise BenchmarkEvidenceError(
                "benchmark evidence directory is unsafe"
            )
        descriptor = os.open(canonical, _DIRECTORY_FLAGS)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            raise BenchmarkEvidenceError(
                "benchmark evidence directory is unsafe"
            )
        return _DirectoryBinding(
            path=canonical,
            descriptor=descriptor,
            identity=(opened.st_dev, opened.st_ino),
            private=False,
        )
    except BenchmarkEvidenceError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except (OSError, RuntimeError):
        if descriptor >= 0:
            os.close(descriptor)
        raise BenchmarkEvidenceError(
            "benchmark evidence is unavailable"
        ) from None


def _open_private_child(
    parent: _DirectoryBinding,
    name: str,
    *,
    create: bool,
) -> _DirectoryBinding:
    if not _member_name(name):
        raise BenchmarkEvidenceError("benchmark evidence directory is unsafe")
    descriptor = -1
    _assert_directory(parent)
    try:
        try:
            metadata = os.stat(
                name,
                dir_fd=parent.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            if not create:
                raise BenchmarkEvidenceError(
                    "benchmark evidence is unavailable"
                ) from None
            os.mkdir(name, mode=0o700, dir_fd=parent.descriptor)
            metadata = os.stat(
                name,
                dir_fd=parent.descriptor,
                follow_symlinks=False,
            )
        if not _private_directory(metadata):
            raise BenchmarkEvidenceError(
                "benchmark evidence directory is unsafe"
            )
        descriptor = os.open(
            name,
            _DIRECTORY_FLAGS,
            dir_fd=parent.descriptor,
        )
        os.fchmod(descriptor, 0o700)
        opened = os.fstat(descriptor)
        if (
            not _private_directory(opened)
            or (opened.st_dev, opened.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            raise BenchmarkEvidenceError(
                "benchmark evidence directory is unsafe"
            )
        binding = _DirectoryBinding(
            path=parent.path / name,
            descriptor=descriptor,
            identity=(opened.st_dev, opened.st_ino),
            private=True,
            parent=parent,
            name=name,
        )
        _assert_directory(binding)
        return binding
    except BenchmarkEvidenceError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        raise BenchmarkEvidenceError(
            "benchmark evidence directory is unsafe"
        ) from None


def _assert_directory(binding: _DirectoryBinding) -> None:
    try:
        opened = os.fstat(binding.descriptor)
        if binding.parent is None:
            metadata = binding.path.lstat()
        else:
            _assert_directory(binding.parent)
            if binding.name is None:
                raise OSError
            metadata = os.stat(
                binding.name,
                dir_fd=binding.parent.descriptor,
                follow_symlinks=False,
            )
    except BenchmarkEvidenceError:
        raise
    except OSError:
        raise BenchmarkEvidenceError(
            "benchmark evidence directory changed"
        ) from None
    valid = (
        _private_directory
        if binding.private
        else lambda value: stat.S_ISDIR(value.st_mode)
    )
    if (
        not valid(opened)
        or not valid(metadata)
        or (opened.st_dev, opened.st_ino) != binding.identity
        or (metadata.st_dev, metadata.st_ino) != binding.identity
    ):
        raise BenchmarkEvidenceError(
            "benchmark evidence directory changed"
        )


def _read_document_if_present(
    run: _DirectoryBinding,
) -> dict[str, Any] | None:
    _assert_directory(run)
    metadata = _member_metadata(run, _EVIDENCE_NAME)
    if metadata is None:
        return None
    if not _private_file(metadata):
        raise BenchmarkEvidenceError("benchmark evidence file is unsafe")
    descriptor = -1
    try:
        descriptor = os.open(
            _EVIDENCE_NAME,
            _READ_FLAGS,
            dir_fd=run.descriptor,
        )
        opened = os.fstat(descriptor)
        identity = (opened.st_dev, opened.st_ino)
        _assert_private_file(
            run,
            _EVIDENCE_NAME,
            descriptor,
            identity,
        )
        if opened.st_size > _MAX_EVIDENCE_BYTES:
            raise BenchmarkEvidenceError(
                "benchmark evidence file is unsafe"
            )
        chunks: list[bytes] = []
        remaining = _MAX_EVIDENCE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining <= 0 and os.read(descriptor, 1):
            raise BenchmarkEvidenceError(
                "benchmark evidence file is unsafe"
            )
        _assert_private_file(
            run,
            _EVIDENCE_NAME,
            descriptor,
            identity,
        )
        try:
            value = json.loads(b"".join(chunks).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise BenchmarkEvidenceError(
                "benchmark evidence is invalid"
            ) from None
        if not isinstance(value, dict):
            raise BenchmarkEvidenceError("benchmark evidence is invalid")
        return value
    except BenchmarkEvidenceError:
        raise
    except OSError:
        raise BenchmarkEvidenceError(
            "benchmark evidence file is unsafe"
        ) from None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _load_document(run: _DirectoryBinding) -> dict[str, Any]:
    document = _read_document_if_present(run)
    if document is None:
        raise BenchmarkEvidenceError("benchmark evidence is unavailable")
    _validate_document(document)
    return document


def _atomic_write(run: _DirectoryBinding, document: dict[str, Any]) -> None:
    _validate_document(document)
    try:
        payload = (
            json.dumps(
                document,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise BenchmarkEvidenceError("benchmark evidence is invalid") from None
    if len(payload) > _MAX_EVIDENCE_BYTES:
        raise BenchmarkEvidenceError("benchmark evidence file is unsafe")

    existing = _member_metadata(run, _EVIDENCE_NAME)
    if existing is not None and not _private_file(existing):
        raise BenchmarkEvidenceError("benchmark evidence file is unsafe")
    temporary = f".evidence.{secrets.token_hex(16)}.tmp"
    descriptor = -1
    temporary_identity: tuple[int, int] | None = None
    promoted = False
    try:
        descriptor = os.open(
            temporary,
            _WRITE_FLAGS,
            0o600,
            dir_fd=run.descriptor,
        )
        os.fchmod(descriptor, 0o600)
        opened = os.fstat(descriptor)
        temporary_identity = (opened.st_dev, opened.st_ino)
        if not _private_file(opened):
            raise BenchmarkEvidenceError(
                "benchmark evidence file is unsafe"
            )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError
            view = view[written:]
        os.fsync(descriptor)
        _assert_directory(run)
        _assert_private_file(
            run,
            temporary,
            descriptor,
            temporary_identity,
        )
        current = _member_metadata(run, _EVIDENCE_NAME)
        if current is not None and not _private_file(current):
            raise BenchmarkEvidenceError(
                "benchmark evidence file is unsafe"
            )
        os.replace(
            temporary,
            _EVIDENCE_NAME,
            src_dir_fd=run.descriptor,
            dst_dir_fd=run.descriptor,
        )
        promoted = True
        _assert_directory(run)
        _assert_private_file(
            run,
            _EVIDENCE_NAME,
            descriptor,
            temporary_identity,
        )
        os.fsync(run.descriptor)
        _assert_directory(run)
    except BenchmarkEvidenceError:
        if not promoted:
            _unlink_owned(run, temporary, temporary_identity)
        raise
    except (OSError, TypeError, ValueError):
        if not promoted:
            _unlink_owned(run, temporary, temporary_identity)
        raise BenchmarkEvidenceError(
            "benchmark evidence write failed"
        ) from None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _persist_document(
    run: _DirectoryBinding,
    document: dict[str, Any],
) -> None:
    _validate_document(document)
    _atomic_write(run, document)


def _member_metadata(
    parent: _DirectoryBinding,
    name: str,
) -> os.stat_result | None:
    _assert_directory(parent)
    try:
        return os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except OSError:
        raise BenchmarkEvidenceError(
            "benchmark evidence file is unsafe"
        ) from None


def _assert_private_file(
    parent: _DirectoryBinding,
    name: str,
    descriptor: int,
    identity: tuple[int, int],
) -> None:
    try:
        _assert_directory(parent)
        opened = os.fstat(descriptor)
        named = os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except BenchmarkEvidenceError:
        raise
    except OSError:
        raise BenchmarkEvidenceError(
            "benchmark evidence file is unsafe"
        ) from None
    if (
        not _private_file(opened)
        or not _private_file(named)
        or (opened.st_dev, opened.st_ino) != identity
        or (named.st_dev, named.st_ino) != identity
    ):
        raise BenchmarkEvidenceError("benchmark evidence file is unsafe")


def _unlink_owned(
    parent: _DirectoryBinding,
    name: str,
    identity: tuple[int, int] | None,
) -> None:
    if identity is None:
        return
    try:
        metadata = os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
        if (metadata.st_dev, metadata.st_ino) == identity:
            os.unlink(name, dir_fd=parent.descriptor)
    except OSError:
        pass


def _private_directory(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _private_file(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1
    )


def _plan_identity(plan: ResolvedBenchmarkPlan) -> dict[str, Any]:
    if not isinstance(plan, ResolvedBenchmarkPlan):
        raise BenchmarkEvidenceError("benchmark evidence plan is invalid")
    entries = tuple(
        entry
        for lock in plan.plan.package_locks
        for entry in lock.entries
    )
    return {
        "application_ref": (
            f"{plan.plan.application_ref.application_id}@"
            f"{plan.plan.application_ref.version}"
        ),
        "suite_ref": plan.plan.suite.suite_ref.selector,
        "package_refs": [
            entry.package_ref.selector for entry in entries
        ],
        "payload_digests": [
            entry.payload_sha256 for entry in entries
        ],
        "source_locks": [
            {
                "package_ref": entry.package_ref.selector,
                "payload_sha256": entry.payload_sha256,
                "source_id": entry.source_id,
            }
            for entry in entries
        ],
        "ordered_task_ids": [
            task.planned.task.task_id for task in plan.tasks
        ],
        "case_limit": plan.plan.case_limit,
    }


def _initial_document(
    plan: ResolvedBenchmarkPlan,
    identity: dict[str, Any],
) -> dict[str, Any]:
    document = {
        "schema": _EVIDENCE_SCHEMA,
        "run_id": plan.plan.run_id,
        "identity": identity,
        "status": "initialized",
        "tasks": [
            {
                "ordinal": task.planned.ordinal,
                "task_id": task.planned.task.task_id,
                "status": "pending",
                "progress": [],
                "result": None,
            }
            for task in plan.tasks
        ],
        "run_result": None,
    }
    _validate_document(document)
    return document


def _assert_compatible(
    document: dict[str, Any],
    plan: ResolvedBenchmarkPlan,
    identity: dict[str, Any],
) -> None:
    if (
        document["run_id"] != plan.plan.run_id
        or document["identity"] != identity
    ):
        raise BenchmarkEvidenceError("benchmark evidence is incompatible")


def _validate_document(document: object) -> None:
    if (
        type(document) is not dict
        or set(document)
        != {
            "schema",
            "run_id",
            "identity",
            "status",
            "tasks",
            "run_result",
        }
        or document["schema"] != _EVIDENCE_SCHEMA
        or not _member_name(document["run_id"])
        or document["status"] not in _RUN_STATUSES
    ):
        raise BenchmarkEvidenceError("benchmark evidence is invalid")
    identity = document["identity"]
    if not _valid_identity(identity):
        raise BenchmarkEvidenceError("benchmark evidence is invalid")
    tasks = document["tasks"]
    ordered_task_ids = identity["ordered_task_ids"]
    case_limit = identity["case_limit"]
    if (
        type(tasks) is not list
        or len(tasks) != len(ordered_task_ids)
        or not tasks
    ):
        raise BenchmarkEvidenceError("benchmark evidence is invalid")

    blocked = False
    completed_ids: list[str] = []
    for ordinal, (row, expected_task_id) in enumerate(
        zip(tasks, ordered_task_ids, strict=True),
        start=1,
    ):
        if not _valid_task_row(
            row,
            ordinal=ordinal,
            expected_task_id=expected_task_id,
            case_limit=case_limit,
        ):
            raise BenchmarkEvidenceError("benchmark evidence is invalid")
        status = row["status"]
        if blocked and status != "pending":
            raise BenchmarkEvidenceError("benchmark evidence is invalid")
        if status == "completed":
            completed_ids.append(row["task_id"])
        else:
            blocked = True

    status = document["status"]
    run_result = document["run_result"]
    task_statuses = tuple(row["status"] for row in tasks)
    if status == "initialized":
        if run_result is not None or any(
            task_status != "pending" for task_status in task_statuses
        ):
            raise BenchmarkEvidenceError("benchmark evidence is invalid")
        return
    if status == "running":
        if run_result is not None or all(
            task_status == "pending" for task_status in task_statuses
        ):
            raise BenchmarkEvidenceError("benchmark evidence is invalid")
        return
    if not _valid_run_result(
        run_result,
        status=status,
        completed_ids=tuple(completed_ids),
    ):
        raise BenchmarkEvidenceError("benchmark evidence is invalid")
    if status == "completed" and any(
        task_status != "completed" for task_status in task_statuses
    ):
        raise BenchmarkEvidenceError("benchmark evidence is invalid")
    if status == "failed" and (
        "failed" not in task_statuses
        or "cancelled" in task_statuses
        or "running" in task_statuses
    ):
        raise BenchmarkEvidenceError("benchmark evidence is invalid")
    if status == "cancelled" and any(
        task_status in {"failed", "running"}
        for task_status in task_statuses
    ):
        raise BenchmarkEvidenceError("benchmark evidence is invalid")


def _valid_identity(value: object) -> bool:
    if (
        type(value) is not dict
        or set(value)
        != {
            "application_ref",
            "suite_ref",
            "package_refs",
            "payload_digests",
            "source_locks",
            "ordered_task_ids",
            "case_limit",
        }
        or not _selector(value["application_ref"])
        or not _selector(value["suite_ref"])
        or type(value["package_refs"]) is not list
        or type(value["payload_digests"]) is not list
        or type(value["source_locks"]) is not list
        or type(value["ordered_task_ids"]) is not list
        or type(value["case_limit"]) is not int
        or value["case_limit"] <= 0
    ):
        return False
    package_refs = value["package_refs"]
    payload_digests = value["payload_digests"]
    source_locks = value["source_locks"]
    task_ids = value["ordered_task_ids"]
    if (
        not package_refs
        or len(package_refs) != len(payload_digests)
        or len(package_refs) != len(source_locks)
        or len(set(package_refs)) != len(package_refs)
        or package_refs != sorted(package_refs)
        or any(not _selector(item) for item in package_refs)
        or any(not _digest(item) for item in payload_digests)
        or not task_ids
        or any(not _identifier(item) for item in task_ids)
        or len(set(task_ids)) != len(task_ids)
    ):
        return False
    for package_ref, payload_digest, lock in zip(
        package_refs,
        payload_digests,
        source_locks,
        strict=True,
    ):
        if (
            type(lock) is not dict
            or set(lock)
            != {"package_ref", "payload_sha256", "source_id"}
            or lock["package_ref"] != package_ref
            or lock["payload_sha256"] != payload_digest
            or not _identifier(lock["source_id"])
        ):
            return False
    return True


def _valid_task_row(
    value: object,
    *,
    ordinal: int,
    expected_task_id: str,
    case_limit: int,
) -> bool:
    if (
        type(value) is not dict
        or set(value)
        != {"ordinal", "task_id", "status", "progress", "result"}
        or value["ordinal"] != ordinal
        or value["task_id"] != expected_task_id
        or value["status"]
        not in {"pending", "running"} | _TASK_TERMINAL_STATUSES
        or type(value["progress"]) is not list
    ):
        return False
    progress = value["progress"]
    completed_cases = -1
    for sequence, event in enumerate(progress, start=1):
        if (
            type(event) is not dict
            or set(event)
            != {
                "sequence",
                "phase",
                "completed_cases",
                "total_cases",
                "content_digest",
            }
            or event["sequence"] != sequence
            or event["phase"] not in _PROGRESS_PHASES
            or type(event["completed_cases"]) is not int
            or event["completed_cases"] < completed_cases
            or event["completed_cases"] > case_limit
            or event["total_cases"] != case_limit
            or (
                event["content_digest"] is not None
                and not _digest(event["content_digest"])
            )
        ):
            return False
        completed_cases = event["completed_cases"]
    status = value["status"]
    result = value["result"]
    if status in {"pending", "running"}:
        return result is None and (status != "pending" or not progress)
    return _valid_task_result(
        result,
        status=status,
        case_limit=case_limit,
        minimum_completed_cases=max(completed_cases, 0),
    )


def _valid_task_result(
    value: object,
    *,
    status: str,
    case_limit: int,
    minimum_completed_cases: int,
) -> bool:
    return (
        type(value) is dict
        and set(value)
        == {"status", "completed_cases", "content_digests"}
        and value["status"] == status
        and type(value["completed_cases"]) is int
        and minimum_completed_cases
        <= value["completed_cases"]
        <= case_limit
        and _valid_digest_list(value["content_digests"])
    )


def _valid_run_result(
    value: object,
    *,
    status: str,
    completed_ids: tuple[str, ...],
) -> bool:
    return (
        type(value) is dict
        and set(value)
        == {"status", "completed_task_ids", "content_digests"}
        and value["status"] == status
        and value["completed_task_ids"] == list(completed_ids)
        and _valid_digest_list(value["content_digests"])
    )


def _valid_digest_list(value: object) -> bool:
    return (
        type(value) is list
        and all(_digest(item) for item in value)
        and len(set(value)) == len(value)
        and value == sorted(value)
    )


def _task_row(
    document: dict[str, Any],
    ordinal: int,
    task_id: str,
) -> dict[str, Any]:
    if (
        type(ordinal) is not int
        or ordinal <= 0
        or ordinal > len(document["tasks"])
    ):
        raise BenchmarkEvidenceError(
            "benchmark evidence update is invalid"
        )
    row = document["tasks"][ordinal - 1]
    if row["ordinal"] != ordinal or row["task_id"] != task_id:
        raise BenchmarkEvidenceError(
            "benchmark evidence update is invalid"
        )
    return row


def _task_row_by_id(
    document: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    matches = [
        row for row in document["tasks"] if row["task_id"] == task_id
    ]
    if len(matches) != 1:
        raise BenchmarkEvidenceError(
            "benchmark evidence update is invalid"
        )
    return matches[0]


def _progress_projection(
    event: BenchmarkProgressEvent,
) -> dict[str, object]:
    return {
        "sequence": event.sequence,
        "phase": event.phase,
        "completed_cases": event.completed_cases,
        "total_cases": event.total_cases,
        "content_digest": event.content_digest,
    }


def _task_result_projection(
    result: BenchmarkTaskResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "completed_cases": result.completed_cases,
        "content_digests": list(result.content_digests),
    }


def _run_result_projection(
    result: BenchmarkRunResult,
) -> dict[str, object]:
    return {
        "status": result.status,
        "completed_task_ids": list(result.completed_task_ids),
        "content_digests": list(result.content_digests),
    }


def _identifier(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


def _member_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and value not in {".", ".."}
        and _MEMBER_NAME.fullmatch(value) is not None
    )


def _selector(value: object) -> bool:
    return isinstance(value, str) and _SELECTOR.fullmatch(value) is not None


def _digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _string_tuple(value: object, error: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(error)
    try:
        values = tuple(value)  # type: ignore[arg-type]
    except TypeError:
        raise ValueError(error) from None
    if any(not isinstance(item, str) for item in values):
        raise ValueError(error)
    return values


def _digest_tuple(value: object, error: str) -> tuple[str, ...]:
    values = _string_tuple(value, error)
    if (
        any(not _digest(item) for item in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(error)
    return tuple(sorted(values))
