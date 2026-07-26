"""Provider-safe orchestration for the repository DCI benchmark launchers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, TextIO

from dotenv import dotenv_values


SuiteName = Literal["github", "paper-main", "all"]

PROJECT = Path(__file__).resolve().parents[1]
_SECRET_NAME = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)


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
        private_values=tuple(sorted(private_values, key=len, reverse=True)),
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
