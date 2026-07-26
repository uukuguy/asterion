"""Provider-safe orchestration for the repository DCI benchmark launchers."""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, TextIO

from dotenv import dotenv_values


SuiteName = Literal["github", "paper-main", "all"]

PROJECT = Path(__file__).resolve().parents[1]
_SECRET_NAME = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)
CommandExecutor = Callable[..., int]
_CHILD_FAILURE_EXIT = 2
_CHILD_STOP_TIMEOUT_SECONDS = 5.0
_KILL_SIGNAL = getattr(signal, "SIGKILL", signal.SIGTERM)
_EXPECTED_OUTPUT_DEVICE = "ASTERION_DCI_EXPECTED_OUTPUT_DEVICE"
_EXPECTED_OUTPUT_INODE = "ASTERION_DCI_EXPECTED_OUTPUT_INODE"
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_PATH_NAME = re.compile(r"(?:^HOME$|PATH|DIR|FILE|ROOT)", re.IGNORECASE)


class OrchestratorError(RuntimeError):
    """Stable body-free coordinator failure."""


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    task_id: str
    suites: tuple[str, ...]
    profile: str
    launcher: str | None
    dataset: str | None
    corpus: str | None
    selection_variant: str
    note: str
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class RunOptions:
    suite: SuiteName = "all"
    limit: int = 1
    max_concurrency: int = 1
    output_root: Path | None = None
    env_file: Path = field(default_factory=lambda: PROJECT / ".env")
    execute: bool = False

    def validate(self) -> None:
        if self.suite not in ("github", "paper-main", "all"):
            raise OrchestratorError("DCI benchmark suite is invalid")
        if type(self.limit) is not int or self.limit < 1:
            raise OrchestratorError("DCI benchmark limit is invalid")
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise OrchestratorError("DCI benchmark concurrency is invalid")


@dataclass(frozen=True, slots=True)
class RunPlan:
    options: RunOptions
    tasks: tuple[BenchmarkTask, ...]
    environment: Mapping[str, str]
    private_values: tuple[str, ...]
    resource_root: Path
    output_base: Path
    run_label: str


_ASTERION_IR_NOTE = (
    "Asterion-defined deduplicated nDCG@10 semantics; "
    "not a paper-reported duplicate-handling method"
)

_TASKS = (
    BenchmarkTask(
        "bcplus.level3", ("github",), "bcplus.level3",
        "scripts/bcplus_eval/run_L3.sh", None, None, "github-level3", "",
    ),
    BenchmarkTask(
        "bcplus.main", ("github", "paper-main"), "bcplus.openai",
        "scripts/bcplus_eval/run_bcplus_eval_openai.sh", None, None,
        "main", "",
    ),
    BenchmarkTask(
        "beir.arguana", ("paper-main",), "beir.arguana",
        "scripts/beir/benchmark_arguana.sh", None, None, "paper-main",
        _ASTERION_IR_NOTE,
    ),
    BenchmarkTask(
        "beir.scifact", ("paper-main",), "beir.scifact",
        "scripts/beir/benchmark_scifact.sh", None, None, "paper-main",
        _ASTERION_IR_NOTE,
    ),
    BenchmarkTask(
        "bright.biology", ("github", "paper-main"), "bright.biology",
        "scripts/bright/run_bio.sh", None, None, "main", _ASTERION_IR_NOTE,
    ),
    BenchmarkTask(
        "bright.earth-science", ("github", "paper-main"),
        "bright.earth-science", "scripts/bright/run_earth_science.sh",
        None, None, "main", _ASTERION_IR_NOTE,
    ),
    BenchmarkTask(
        "bright.economics", ("github", "paper-main"), "bright.economics",
        "scripts/bright/run_economics.sh", None, None, "main",
        _ASTERION_IR_NOTE,
    ),
    BenchmarkTask(
        "bright.robotics", ("github", "paper-main"), "bright.robotics",
        "scripts/bright/run_robotics.sh", None, None, "main",
        _ASTERION_IR_NOTE,
    ),
    BenchmarkTask(
        "qa.2wikimultihopqa", ("github", "paper-main"),
        "qa.2wikimultihopqa",
        "scripts/qa/run_2wikimultihopqa_dev_sample50.sh",
        None, None, "main", "",
    ),
    BenchmarkTask(
        "qa.bamboogle.github-sample50", ("github",), "qa.bamboogle",
        "scripts/qa/run_bamboogle_test_sample50.sh", None, None,
        "github-sample50", "",
    ),
    BenchmarkTask(
        "qa.bamboogle.paper-full125", ("paper-main",), "qa.bamboogle",
        None, "paper-full/data/bamboogle/test-125.jsonl",
        "corpus/wiki_corpus", "paper-full125", "",
    ),
    BenchmarkTask(
        "qa.hotpotqa", ("github", "paper-main"), "qa.hotpotqa",
        "scripts/qa/run_hotpotqa_dev_sample50.sh", None, None, "main", "",
    ),
    BenchmarkTask(
        "qa.musique", ("github", "paper-main"), "qa.musique",
        "scripts/qa/run_musique_dev_sample50.sh", None, None, "main", "",
    ),
    BenchmarkTask(
        "qa.nq", ("github", "paper-main"), "qa.nq",
        "scripts/qa/run_nq_test_sample50.sh", None, None, "main", "",
    ),
    BenchmarkTask(
        "qa.triviaqa", ("github", "paper-main"), "qa.triviaqa",
        "scripts/qa/run_triviaqa_test_sample50.sh", None, None, "main", "",
    ),
)


def select_tasks(suite: SuiteName) -> tuple[BenchmarkTask, ...]:
    if suite == "all":
        return _TASKS
    if suite not in ("github", "paper-main"):
        raise ValueError("DCI benchmark suite is invalid")
    return tuple(task for task in _TASKS if suite in task.suites)


def _configured_path(value: str, *, base: Path) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def build_plan(
    options: RunOptions,
    *,
    process_environment: Mapping[str, str] | None = None,
    invocation_cwd: Path | None = None,
    run_label: str,
) -> RunPlan:
    options.validate()
    cwd = Path.cwd() if invocation_cwd is None else invocation_cwd.resolve()
    env_file = options.env_file.expanduser().resolve()
    if not env_file.is_file():
        raise OrchestratorError("DCI benchmark env file is unavailable")
    try:
        loaded = dotenv_values(env_file)
    except (OSError, ValueError):
        raise OrchestratorError("DCI benchmark env file is unavailable") from None
    environment = dict(os.environ if process_environment is None else process_environment)
    for name, value in loaded.items():
        if value is not None:
            environment.setdefault(name, value)
    private_values = {
        value for value in loaded.values() if value is not None and len(value) >= 4
    }
    private_values.update(
        value
        for name, value in environment.items()
        if value and _SECRET_NAME.search(name)
    )
    resource_value = environment.get("ASTERION_DCI_RESOURCE_ROOT", "")
    resource_root = (
        PROJECT
        if not resource_value.strip()
        else _configured_path(resource_value, base=env_file.parent)
    )
    environment["ASTERION_DCI_RESOURCE_ROOT"] = str(resource_root)
    output_value = environment.get("ASTERION_DCI_OUTPUT_ROOT", "")
    configured_output = (
        PROJECT / "outputs" / "asterion-dci-runs"
        if not output_value.strip()
        else _configured_path(output_value, base=env_file.parent)
    )
    output_base = (
        _configured_path(str(options.output_root), base=cwd)
        if options.output_root is not None
        else configured_output / "benchmark-orchestrator" / run_label
    )
    return RunPlan(
        options=options,
        tasks=select_tasks(options.suite),
        environment=MappingProxyType(environment),
        private_values=tuple(sorted(private_values, key=lambda value: (-len(value), value))),
        resource_root=resource_root,
        output_base=output_base,
        run_label=run_label,
    )


def render_plan(plan: RunPlan, stream: TextIO) -> None:
    mode = "EXECUTE" if plan.options.execute else "PLAN"
    print(
        f"DCI benchmark suite={plan.options.suite} tasks={len(plan.tasks)} "
        f"limit={plan.options.limit} concurrency={plan.options.max_concurrency} "
        f"mode={mode} env={plan.options.env_file.name}",
        file=stream,
    )
    print(
        "WARNING: direct benchmark execution has no USD ledger; "
        "limit, concurrency, and sequential execution are the bounds",
        file=stream,
    )
    for index, task in enumerate(plan.tasks, 1):
        status = "SKIP" if task.skip_reason is not None else "PLANNED"
        suffix = "" if task.skip_reason is None else f" reason={task.skip_reason}"
        if task.note:
            suffix += f" note={task.note}"
        print(
            f"[{index}/{len(plan.tasks)}] {task.task_id} {status}{suffix}",
            file=stream,
        )


def build_task_command(
    plan: RunPlan, task: BenchmarkTask, task_root: Path
) -> tuple[str, ...]:
    common = (
        "--limit",
        str(plan.options.limit),
        "--max-concurrency",
        str(plan.options.max_concurrency),
        "--resume-policy",
        "compatible",
        "--output-root",
        str(task_root),
    )
    if task.launcher is not None:
        launcher = PROJECT / task.launcher
        if not launcher.is_file():
            raise OrchestratorError("DCI benchmark task binding is unavailable")
        return (str(launcher), *common)
    if task.dataset is None or task.corpus is None:
        raise OrchestratorError("DCI benchmark task binding is unavailable")
    return (
        "uv",
        "run",
        "--project",
        str(PROJECT),
        "asterion-dci",
        "benchmark",
        "--profile",
        task.profile,
        "--dataset",
        str(plan.resource_root / task.dataset),
        "--corpus",
        str(plan.resource_root / task.corpus),
        *common,
    )


def stream_command(
    command: tuple[str, ...],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    on_line: Callable[[str], None],
) -> int:
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=dict(environment),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=os.name == "posix",
        )
    except OSError:
        raise OrchestratorError(
            "DCI benchmark child process failed to start"
        ) from None
    assert process.stdout is not None
    try:
        for line in process.stdout:
            on_line(line)
        process.stdout.close()
        return process.wait()
    except BaseException as error:
        try:
            process.stdout.close()
        except OSError:
            pass
        initial_signal = (
            signal.SIGINT if isinstance(error, KeyboardInterrupt) else signal.SIGTERM
        )
        used_process_group = _signal_process_tree(process, initial_signal)
        timed_out = False
        try:
            process.wait(timeout=_CHILD_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
        if used_process_group or timed_out:
            _signal_process_tree(process, _KILL_SIGNAL, force=True)
        try:
            process.wait(timeout=_CHILD_STOP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            raise OrchestratorError(
                "DCI benchmark child process cleanup failed"
            ) from None
        raise


def _signal_process_tree(
    process: subprocess.Popen[str],
    value: int,
    *,
    force: bool = False,
) -> bool:
    if os.name == "posix" and hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, value)
            return True
        except (AttributeError, OSError, TypeError):
            pass
    try:
        if force:
            process.kill()
        elif value == signal.SIGTERM:
            process.terminate()
        else:
            process.send_signal(value)
    except OSError:
        pass
    return False


def _redactor(plan: RunPlan) -> Callable[[str], str]:
    values = {
        value
        for name, value in plan.environment.items()
        if value and (_SECRET_NAME.search(name) or _PATH_NAME.search(name))
    }
    values.update(plan.private_values)
    values.update(
        (
            str(PROJECT),
            str(Path.home()),
            str(plan.resource_root),
            str(plan.output_base),
        )
    )
    ordered = sorted(
        (value for value in values if len(value) >= 4),
        key=len,
        reverse=True,
    )

    def redact(line: str) -> str:
        for value in ordered:
            line = line.replace(value, "<redacted>")
        return line

    return redact


@dataclass(slots=True)
class _DirectoryBinding:
    path: Path
    descriptor: int
    identity: tuple[int, int]
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


@dataclass(slots=True)
class _LogBinding:
    parent: _DirectoryBinding
    name: str
    descriptor: int
    identity: tuple[int, int]
    handle: TextIO

    def close(self) -> None:
        if self.descriptor < 0:
            return
        try:
            self.handle.close()
        except OSError:
            pass
        self.descriptor = -1


def _valid_private_directory(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISDIR(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _valid_private_file(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1
    )


def _assert_private_file(
    parent: _DirectoryBinding,
    name: str,
    descriptor: int,
    identity: tuple[int, int],
    *,
    message: str,
) -> None:
    try:
        _assert_identity(parent)
        opened = os.fstat(descriptor)
        named = os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
    except OrchestratorError:
        raise
    except OSError:
        raise OrchestratorError(message) from None
    if (
        not _valid_private_file(opened)
        or not _valid_private_file(named)
        or (opened.st_dev, opened.st_ino) != identity
        or (named.st_dev, named.st_ino) != identity
    ):
        raise OrchestratorError(message)


def _assert_log_identity(binding: _LogBinding) -> None:
    _assert_private_file(
        binding.parent,
        binding.name,
        binding.descriptor,
        binding.identity,
        message="DCI benchmark task log changed",
    )


def _prepare_private_directory(path: Path) -> _DirectoryBinding:
    descriptor = -1
    try:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            path.mkdir(parents=True, mode=0o700)
            path.chmod(0o700)
            metadata = path.lstat()
        if not _valid_private_directory(metadata):
            raise OrchestratorError("DCI benchmark output root is unsafe")
        descriptor = os.open(path, _DIRECTORY_FLAGS)
        opened = os.fstat(descriptor)
        if (
            not _valid_private_directory(opened)
            or (opened.st_dev, opened.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            raise OrchestratorError("DCI benchmark output root is unsafe")
        return _DirectoryBinding(
            path=path,
            descriptor=descriptor,
            identity=(opened.st_dev, opened.st_ino),
        )
    except OrchestratorError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise OrchestratorError("DCI benchmark output root is unsafe") from None


def _assert_identity(binding: _DirectoryBinding) -> None:
    message = (
        "DCI benchmark output root changed"
        if binding.parent is None
        else "DCI benchmark task root changed"
    )
    try:
        opened = os.fstat(binding.descriptor)
        if binding.parent is None:
            metadata = binding.path.lstat()
        else:
            _assert_identity(binding.parent)
            assert binding.name is not None
            metadata = os.stat(
                binding.name,
                dir_fd=binding.parent.descriptor,
                follow_symlinks=False,
            )
    except OrchestratorError:
        raise
    except OSError:
        raise OrchestratorError(message) from None
    if (
        not _valid_private_directory(opened)
        or not _valid_private_directory(metadata)
        or (opened.st_dev, opened.st_ino) != binding.identity
        or (metadata.st_dev, metadata.st_ino) != binding.identity
    ):
        raise OrchestratorError(message)


def _prepare_private_child(
    parent: _DirectoryBinding,
    name: str,
) -> _DirectoryBinding:
    descriptor = -1
    _assert_identity(parent)
    if (
        not name
        or name in (".", "..")
        or "/" in name
        or os.sep in name
    ):
        raise OrchestratorError("DCI benchmark task binding is invalid")
    try:
        try:
            metadata = os.stat(
                name,
                dir_fd=parent.descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            os.mkdir(name, mode=0o700, dir_fd=parent.descriptor)
            metadata = os.stat(
                name,
                dir_fd=parent.descriptor,
                follow_symlinks=False,
            )
        if not _valid_private_directory(metadata):
            raise OrchestratorError("DCI benchmark task root is unsafe")
        descriptor = os.open(
            name,
            _DIRECTORY_FLAGS,
            dir_fd=parent.descriptor,
        )
        os.fchmod(descriptor, 0o700)
        opened = os.fstat(descriptor)
        if (
            not _valid_private_directory(opened)
            or (opened.st_dev, opened.st_ino)
            != (metadata.st_dev, metadata.st_ino)
        ):
            raise OrchestratorError("DCI benchmark task root is unsafe")
        binding = _DirectoryBinding(
            path=parent.path / name,
            descriptor=descriptor,
            identity=(opened.st_dev, opened.st_ino),
            parent=parent,
            name=name,
        )
        _assert_identity(binding)
        return binding
    except OrchestratorError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise OrchestratorError("DCI benchmark task root is unsafe") from None


def _summary_temporary_name() -> str:
    return f".summary.{secrets.token_hex(16)}.tmp"


def _unlink_bound_file(
    parent: _DirectoryBinding,
    name: str,
    identity: tuple[int, int] | None,
) -> None:
    if identity is None:
        return
    try:
        named = os.stat(
            name,
            dir_fd=parent.descriptor,
            follow_symlinks=False,
        )
        if (named.st_dev, named.st_ino) != identity:
            return
        os.unlink(name, dir_fd=parent.descriptor)
    except OSError:
        pass


def _write_summary(
    root: _DirectoryBinding,
    payload: object,
    *,
    required_directories: tuple[_DirectoryBinding, ...] = (),
    required_logs: tuple[_LogBinding, ...] = (),
) -> None:
    _assert_identity(root)
    for binding in required_directories:
        _assert_identity(binding)
    for binding in required_logs:
        _assert_log_identity(binding)
    temporary = _summary_temporary_name()
    descriptor = -1
    temporary_identity: tuple[int, int] | None = None
    promoted = False
    try:
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=root.descriptor,
            )
            os.fchmod(descriptor, 0o600)
            opened = os.fstat(descriptor)
            temporary_identity = (opened.st_dev, opened.st_ino)
            if not _valid_private_file(opened):
                raise OrchestratorError("DCI benchmark summary is unsafe")
            handle = os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                closefd=False,
            )
            with handle:
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(descriptor)
            _assert_identity(root)
            for binding in required_directories:
                _assert_identity(binding)
            for binding in required_logs:
                _assert_log_identity(binding)
            _assert_private_file(
                root,
                temporary,
                descriptor,
                temporary_identity,
                message="DCI benchmark summary is unsafe",
            )
            os.replace(
                temporary,
                "summary.json",
                src_dir_fd=root.descriptor,
                dst_dir_fd=root.descriptor,
            )
            promoted = True
            _assert_private_file(
                root,
                "summary.json",
                descriptor,
                temporary_identity,
                message="DCI benchmark summary is unsafe",
            )
        except OrchestratorError:
            _unlink_bound_file(
                root,
                "summary.json" if promoted else temporary,
                temporary_identity,
            )
            raise
        except (OSError, TypeError, ValueError):
            _unlink_bound_file(
                root,
                "summary.json" if promoted else temporary,
                temporary_identity,
            )
            raise OrchestratorError("DCI benchmark summary is unsafe") from None
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _open_private_log(task_root: _DirectoryBinding) -> _LogBinding:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_APPEND
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    _assert_identity(task_root)
    try:
        descriptor = os.open(
            "runner.log",
            flags,
            0o600,
            dir_fd=task_root.descriptor,
        )
        os.fchmod(descriptor, 0o600)
        opened = os.fstat(descriptor)
        if not _valid_private_file(opened):
            raise OrchestratorError("DCI benchmark task log is unsafe")
        identity = (opened.st_dev, opened.st_ino)
        _assert_private_file(
            task_root,
            "runner.log",
            descriptor,
            identity,
            message="DCI benchmark task log is unsafe",
        )
        handle = os.fdopen(descriptor, "a", encoding="utf-8")
        return _LogBinding(
            parent=task_root,
            name="runner.log",
            descriptor=descriptor,
            identity=identity,
            handle=handle,
        )
    except OrchestratorError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise OrchestratorError("DCI benchmark task log is unsafe") from None


def _progress(
    stream: TextIO,
    index: int,
    total: int,
    task_id: str,
    status_text: str,
) -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{timestamp} [{index}/{total}] {task_id} {status_text}"
    try:
        print(line, file=stream, flush=True)
    except (OSError, ValueError):
        pass
    return line


def _initial_rows(
    tasks: tuple[BenchmarkTask, ...],
) -> tuple[list[dict[str, object]], tuple[str, ...]]:
    slugs = tuple(
        re.sub(r"[^a-z0-9._-]", "-", task.task_id.lower()) for task in tasks
    )
    if any(
        not slug
        or slug in (".", "..")
        or len(os.fsencode(slug)) > 255
        or re.fullmatch(r"[a-z0-9._-]+", slug) is None
        or Path(slug).name != slug
        for slug in slugs
    ):
        raise OrchestratorError("DCI benchmark task binding is invalid")
    if len(slugs) != len(set(slugs)):
        raise OrchestratorError("DCI benchmark task binding is ambiguous")
    rows = [
        {
            "task_id": task.task_id,
            "selection_variant": task.selection_variant,
            "status": "NOT_RUN",
            "exit_code": None,
            "elapsed_seconds": None,
            "output": None,
            "log": None,
            "skip_reason": task.skip_reason,
        }
        for task in tasks
    ]
    return rows, slugs


def _summary_payload(
    plan: RunPlan, rows: list[dict[str, object]], *, passed: bool
) -> dict[str, object]:
    return {
        "schema": "asterion.dci.benchmark-orchestrator-summary/v1",
        "suite": plan.options.suite,
        "run_label": plan.run_label,
        "limit": plan.options.limit,
        "max_concurrency": plan.options.max_concurrency,
        "status": "PASS" if passed else "FAIL",
        "tasks": rows,
    }


def _validate_task_bindings(tasks: tuple[BenchmarkTask, ...]) -> None:
    for task in tasks:
        if task.skip_reason is not None:
            continue
        if task.launcher is not None:
            if not (PROJECT / task.launcher).is_file():
                raise OrchestratorError(
                    "DCI benchmark task binding is unavailable"
                )
            continue
        if task.dataset is None or task.corpus is None:
            raise OrchestratorError("DCI benchmark task binding is unavailable")


def execute_plan(
    plan: RunPlan,
    *,
    stream: TextIO,
    executor: CommandExecutor = stream_command,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    _validate_task_bindings(plan.tasks)
    rows, slugs = _initial_rows(plan.tasks)
    redact = _redactor(plan)

    def discard_check_output(line: str) -> None:
        del line

    check_command = (
        sys.executable,
        str(PROJECT / "tools/setup_resources.py"),
        "--profile",
        "benchmark",
        "--check",
    )
    check_exit = executor(
        check_command,
        cwd=PROJECT,
        environment=plan.environment,
        on_line=discard_check_output,
    )
    if check_exit != 0:
        return check_exit

    run_root = _prepare_private_directory(plan.output_base)
    bound_directories = [run_root]
    total = len(plan.tasks)
    result = 0
    task_bindings: list[
        tuple[_DirectoryBinding, _DirectoryBinding]
    ] = []
    log_bindings: list[_LogBinding] = []
    try:
        for index, (task, slug, row) in enumerate(
            zip(plan.tasks, slugs, rows), start=1
        ):
            _assert_identity(run_root)
            if task.skip_reason is not None:
                row["status"] = "SKIP"
                _progress(
                    stream,
                    index,
                    total,
                    task.task_id,
                    f"SKIP reason={task.skip_reason}",
                )
                continue

            task_root = _prepare_private_child(run_root, slug)
            bound_directories.append(task_root)
            batch_root = _prepare_private_child(task_root, "batch")
            bound_directories.append(batch_root)
            task_bindings.append((task_root, batch_root))
            row["output"] = f"{slug}/batch"
            row["log"] = f"{slug}/runner.log"
            started = clock()
            note = "" if not task.note else f" note={task.note}"
            start_line = _progress(
                stream, index, total, task.task_id, f"START{note}"
            )
            log_binding: _LogBinding | None = None
            try:
                log_binding = _open_private_log(task_root)
                log_bindings.append(log_binding)
                log_binding.handle.write(start_line + "\n")
                log_binding.handle.flush()

                def record_child(line: str) -> None:
                    assert log_binding is not None
                    log_binding.handle.write(redact(line))
                    log_binding.handle.flush()

                _assert_identity(task_root)
                _assert_identity(batch_root)
                _assert_log_identity(log_binding)
                task_environment = dict(plan.environment)
                task_environment[_EXPECTED_OUTPUT_DEVICE] = str(
                    batch_root.identity[0]
                )
                task_environment[_EXPECTED_OUTPUT_INODE] = str(
                    batch_root.identity[1]
                )
                exit_code = executor(
                    build_task_command(plan, task, batch_root.path),
                    cwd=PROJECT,
                    environment=MappingProxyType(task_environment),
                    on_line=record_child,
                )
            except KeyboardInterrupt:
                exit_code = 130
            except Exception:
                exit_code = _CHILD_FAILURE_EXIT

            _assert_identity(run_root)
            _assert_identity(task_root)
            _assert_identity(batch_root)
            if log_binding is not None:
                _assert_log_identity(log_binding)
            elapsed = round(clock() - started, 3)
            row.update(exit_code=exit_code, elapsed_seconds=elapsed)
            if exit_code == 0:
                row["status"] = "DONE"
                _progress(
                    stream,
                    index,
                    total,
                    task.task_id,
                    f"DONE elapsed={elapsed:.3f}s",
                )
                continue
            row["status"] = "FAILED"
            result = exit_code
            _progress(
                stream,
                index,
                total,
                task.task_id,
                f"FAILED exit={exit_code} elapsed={elapsed:.3f}s",
            )
            break

        _assert_identity(run_root)
        for task_root, batch_root in task_bindings:
            _assert_identity(task_root)
            _assert_identity(batch_root)
        _write_summary(
            run_root,
            _summary_payload(plan, rows, passed=result == 0),
            required_directories=tuple(
                binding
                for task_binding in task_bindings
                for binding in task_binding
            ),
            required_logs=tuple(log_bindings),
        )
        return result
    finally:
        for binding in reversed(log_bindings):
            binding.close()
        for binding in reversed(bound_directories):
            binding.close()
