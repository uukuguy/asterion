"""Provider-safe orchestration for the repository DCI benchmark launchers."""

from __future__ import annotations

import json
import os
import re
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
        )
    except OSError:
        raise OrchestratorError(
            "DCI benchmark child process failed to start"
        ) from None
    assert process.stdout is not None
    try:
        for line in process.stdout:
            on_line(line)
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        process.wait()
        raise


def _redactor(plan: RunPlan) -> Callable[[str], str]:
    values = {
        value
        for name, value in plan.environment.items()
        if value and (_SECRET_NAME.search(name) or name.endswith("_ROOT"))
    }
    values.update(plan.private_values)
    values.update((str(plan.resource_root), str(plan.output_base)))
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


def _prepare_private_directory(path: Path) -> tuple[int, int]:
    try:
        if path.is_symlink():
            raise OrchestratorError("DCI benchmark output root is unsafe")
        if path.exists():
            metadata = path.stat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise OrchestratorError("DCI benchmark output root is unsafe")
        else:
            path.mkdir(parents=True, mode=0o700)
            path.chmod(0o700)
            metadata = path.stat()
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o700
                or (opened.st_dev, opened.st_ino)
                != (metadata.st_dev, metadata.st_ino)
            ):
                raise OrchestratorError("DCI benchmark output root is unsafe")
            return opened.st_dev, opened.st_ino
        finally:
            os.close(descriptor)
    except OrchestratorError:
        raise
    except OSError:
        raise OrchestratorError("DCI benchmark output root is unsafe") from None


def _assert_identity(path: Path, identity: tuple[int, int]) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        raise OrchestratorError("DCI benchmark output root changed") from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or (metadata.st_dev, metadata.st_ino) != identity
    ):
        raise OrchestratorError("DCI benchmark output root changed")


def _write_summary(
    root: Path, identity: tuple[int, int], payload: object
) -> None:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        directory = os.open(root, directory_flags)
    except OSError:
        raise OrchestratorError("DCI benchmark output root changed") from None
    temporary = ".summary.json.tmp"
    descriptor = -1
    try:
        opened = os.fstat(directory)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o700
            or (opened.st_dev, opened.st_ino) != identity
        ):
            raise OrchestratorError("DCI benchmark output root changed")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory,
            )
        except OSError:
            raise OrchestratorError("DCI benchmark summary is unsafe") from None
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        try:
            with handle:
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
            os.replace(
                temporary,
                "summary.json",
                src_dir_fd=directory,
                dst_dir_fd=directory,
            )
        except (OSError, TypeError, ValueError):
            try:
                os.unlink(temporary, dir_fd=directory)
            except OSError:
                pass
            raise OrchestratorError("DCI benchmark summary is unsafe") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory)


def _open_private_log(path: Path):
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_APPEND
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError:
        raise OrchestratorError("DCI benchmark task log is unsafe") from None
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise OrchestratorError("DCI benchmark task log is unsafe")
    os.fchmod(descriptor, 0o600)
    return os.fdopen(descriptor, "a", encoding="utf-8")


def _progress(
    stream: TextIO,
    index: int,
    total: int,
    task_id: str,
    status_text: str,
) -> str:
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{timestamp} [{index}/{total}] {task_id} {status_text}"
    print(line, file=stream, flush=True)
    return line


def _initial_rows(
    tasks: tuple[BenchmarkTask, ...],
) -> tuple[list[dict[str, object]], tuple[str, ...]]:
    slugs = tuple(
        re.sub(r"[^a-z0-9._-]", "-", task.task_id.lower()) for task in tasks
    )
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
    redact = _redactor(plan)

    def emit_check(line: str) -> None:
        print(redact(line), end="", file=stream, flush=True)

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
        on_line=emit_check,
    )
    if check_exit != 0:
        return check_exit

    rows, slugs = _initial_rows(plan.tasks)
    run_identity = _prepare_private_directory(plan.output_base)
    total = len(plan.tasks)
    result = 0

    for index, (task, slug, row) in enumerate(
        zip(plan.tasks, slugs, rows), start=1
    ):
        _assert_identity(plan.output_base, run_identity)
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

        container = plan.output_base / slug
        _prepare_private_directory(container)
        batch_root = container / "batch"
        row["output"] = f"{slug}/batch"
        row["log"] = f"{slug}/runner.log"
        started = clock()
        note = "" if not task.note else f" note={task.note}"
        start_line = _progress(
            stream, index, total, task.task_id, f"START{note}"
        )
        try:
            with _open_private_log(container / "runner.log") as log:
                log.write(start_line + "\n")
                log.flush()

                def emit_child(line: str) -> None:
                    safe_line = redact(line)
                    print(safe_line, end="", file=stream, flush=True)
                    log.write(safe_line)
                    log.flush()

                exit_code = executor(
                    build_task_command(plan, task, batch_root),
                    cwd=PROJECT,
                    environment=plan.environment,
                    on_line=emit_child,
                )
        except KeyboardInterrupt:
            elapsed = round(clock() - started, 3)
            row.update(
                status="FAILED", exit_code=130, elapsed_seconds=elapsed
            )
            result = 130
            _progress(
                stream,
                index,
                total,
                task.task_id,
                f"FAILED exit=130 elapsed={elapsed:.3f}s",
            )
            break

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

    _assert_identity(plan.output_base, run_identity)
    _write_summary(
        plan.output_base,
        run_identity,
        _summary_payload(plan, rows, passed=result == 0),
    )
    return result
