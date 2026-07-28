# DCI Benchmark Orchestrator Implementation Plan

> **Superseded by Plan 4 Task 5:** Retired global DCI launcher/orchestrator references in this historical document are replaced by the generic benchmark host and package-owned benchmark bindings.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one operator-run script that previews or sequentially executes the 15-task Asterion DCI benchmark union with clear progress, dotenv configuration, private evidence, and no monetary inputs.

**Architecture:** A thin shell entry point starts a Python coordinator under the repository's `uv` environment. The coordinator owns an explicit immutable task inventory, argument/dotenv planning, descriptor-checked output handling, redacted streaming, and a body-free run summary; existing launchers and `asterion-dci benchmark` remain the only benchmark executors.

**Tech Stack:** Python 3.10+, `argparse`, `dataclasses`, `python-dotenv`, `subprocess`, descriptor-relative filesystem APIs, JSON, Bash, `unittest`.

## Global Constraints

- Default invocation is plan-only with `--suite all --limit 1 --max-concurrency 1`.
- Only explicit `--execute` may start provider-backed Agent or Judge work.
- There are no USD budget, price, or monetary amount options.
- The coordinator reads existing resources from `.env`; it never downloads, converts, repairs, or scans for data.
- `github` has 12 fixed-revision launcher tasks, `paper-main` has 13 benchmark tasks, and their exact-task union has 15 variants.
- GitHub Bamboogle sample-50 and paper-main Bamboogle-125 are distinct tasks.
- Tasks execute sequentially with `--resume-policy compatible`; the first failure prevents later tasks from starting.
- Public output and `summary.json` exclude credentials, dotenv values, private absolute paths, commands, data bodies, prompts, answers, provider payloads, and raw benchmark output.
- All implementation and verification commands are provider-free.
- Preserve the repository's current unrelated modifications; stage only files named by each task.

---

## File structure

- Create `tools/dci_benchmark_orchestrator.py` — immutable suite inventory, planning types, safe environment/output helpers, subprocess coordination, progress, and summary writing.
- Create `tools/run_dci_benchmarks.py` — small `argparse` CLI that calls the coordinator and maps stable errors to exit code 2.
- Create `scripts/run_dci_benchmarks.sh` — stable operator entry point that runs the Python CLI through the repository `uv` project.
- Create `tests/test_dci_benchmark_orchestrator.py` — provider-free unit and integration tests with fake command execution and sentinel secrets.
- Modify `tests/test_standalone_repository.py` — require the new entry point in standalone repository assets.
- Modify `docs/guides/asterion-capability-usage.md` — document preview and execution commands and their safety boundary.

### Task 0: Preserve the verified benchmark resource prerequisite

**Files:**
- Modify: `.gitignore`
- Modify: `src/asterion/dci/resource_setup.py`
- Modify: `tests/test_resource_setup.py`
- Modify: `tests/test_standalone_repository.py`

**Interfaces:**
- Produces: canonical framework-owned staging roots on macOS.
- Produces: an explicit ignore rule for external `paper-full` data.
- Consumes: the already-written regression tests and the verified 22/22 local benchmark resource inventory.

- [ ] **Step 1: Inspect the existing prerequisite diff**

```bash
git diff -- .gitignore src/asterion/dci/resource_setup.py \
  tests/test_resource_setup.py tests/test_standalone_repository.py
git diff --check -- .gitignore src/asterion/dci/resource_setup.py \
  tests/test_resource_setup.py tests/test_standalone_repository.py
```

Expected: only the staging-alias fix, its regression test, the external
`paper-full` ignore rule, and its repository test are present.

- [ ] **Step 2: Re-run the focused provider-free regression tests**

```bash
uv run python -m unittest -v \
  tests.test_resource_setup \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_external_data_ignore_rules_do_not_hide_packaged_resources
```

Expected: all resource tests and the external-data ignore test pass; Agent
operations 0 and Judge operations 0.

- [ ] **Step 3: Re-run benchmark resource readiness**

```bash
uv run python tools/setup_resources.py --profile benchmark --check
```

Expected: `PASS`, 22 resources present, Agent operations 0, Judge operations
0, full dataset no.

- [ ] **Step 4: Commit only the verified prerequisite**

```bash
git add .gitignore src/asterion/dci/resource_setup.py \
  tests/test_resource_setup.py tests/test_standalone_repository.py
git commit -m "fix: canonicalize DCI benchmark resource staging"
```

### Task 1: Lock the benchmark task inventory

**Files:**
- Create: `tools/dci_benchmark_orchestrator.py`
- Create: `tests/test_dci_benchmark_orchestrator.py`

**Interfaces:**
- Produces: `SuiteName = Literal["github", "paper-main", "all"]`.
- Produces: immutable `BenchmarkTask(task_id, suites, profile, launcher, dataset, corpus, selection_variant, note, skip_reason)`.
- Produces: `select_tasks(suite: SuiteName) -> tuple[BenchmarkTask, ...]`.
- Consumes: existing repository launchers and `src/asterion/dci/resources/paper-benchmarks.json` identities; it does not read dataset bodies.

- [ ] **Step 1: Write failing inventory tests**

Create `tests/test_dci_benchmark_orchestrator.py` with:

```python
from __future__ import annotations

import unittest

from tools.dci_benchmark_orchestrator import select_tasks


class BenchmarkInventoryTests(unittest.TestCase):
    def test_suites_have_stable_ordered_membership(self) -> None:
        github = select_tasks("github")
        paper = select_tasks("paper-main")
        combined = select_tasks("all")

        self.assertEqual(len(github), 12)
        self.assertEqual(len(paper), 13)
        self.assertEqual(len(combined), 15)
        self.assertEqual(len({task.task_id for task in combined}), 15)
        self.assertEqual(
            tuple(task.task_id for task in combined),
            (
                "bcplus.level3",
                "bcplus.main",
                "beir.arguana",
                "beir.scifact",
                "bright.biology",
                "bright.earth-science",
                "bright.economics",
                "bright.robotics",
                "qa.2wikimultihopqa",
                "qa.bamboogle.github-sample50",
                "qa.bamboogle.paper-full125",
                "qa.hotpotqa",
                "qa.musique",
                "qa.nq",
                "qa.triviaqa",
            ),
        )

    def test_bamboogle_variants_are_not_deduplicated(self) -> None:
        tasks = {task.task_id: task for task in select_tasks("all")}
        github = tasks["qa.bamboogle.github-sample50"]
        paper = tasks["qa.bamboogle.paper-full125"]

        self.assertEqual(github.selection_variant, "github-sample50")
        self.assertEqual(paper.selection_variant, "paper-full125")
        self.assertIsNotNone(github.launcher)
        self.assertIsNone(paper.launcher)
        self.assertEqual(
            paper.dataset, "paper-full/data/bamboogle/test-125.jsonl"
        )

    def test_paper_ir_tasks_label_asterion_metric_semantics(self) -> None:
        ir_tasks = (
            task
            for task in select_tasks("paper-main")
            if task.profile.startswith(("beir.", "bright."))
        )
        for task in ir_tasks:
            with self.subTest(task=task.task_id):
                self.assertIn("Asterion-defined", task.note)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the inventory tests and verify the missing module failure**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_orchestrator.BenchmarkInventoryTests
```

Expected: `ERROR` with `ModuleNotFoundError: No module named 'tools.dci_benchmark_orchestrator'`.

- [ ] **Step 3: Implement the immutable explicit inventory**

Create `tools/dci_benchmark_orchestrator.py` beginning with:

```python
"""Provider-safe orchestration for the repository DCI benchmark launchers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SuiteName = Literal["github", "paper-main", "all"]


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
```

- [ ] **Step 4: Run the inventory tests**

Run the Step 2 command again.

Expected: 3 tests `OK`.

- [ ] **Step 5: Commit the inventory**

```bash
git add tools/dci_benchmark_orchestrator.py \
  tests/test_dci_benchmark_orchestrator.py
git commit -m "feat: define DCI benchmark orchestration suites"
```

### Task 2: Add plan-only CLI and safe dotenv resolution

**Files:**
- Modify: `tools/dci_benchmark_orchestrator.py`
- Create: `tools/run_dci_benchmarks.py`
- Modify: `tests/test_dci_benchmark_orchestrator.py`

**Interfaces:**
- Consumes: `select_tasks()` from Task 1.
- Produces: `RunOptions(suite, limit, max_concurrency, output_root, env_file, execute)`.
- Produces: `RunPlan(options, tasks, environment, private_values, resource_root, output_base, run_label)`.
- Produces: `parse_args(argv: Sequence[str] | None) -> RunOptions`.
- Produces: `build_plan(options, *, process_environment, invocation_cwd, run_label) -> RunPlan`.
- Produces: `render_plan(plan, stream) -> None`, which creates no directories and starts no subprocess.

- [ ] **Step 1: Write failing plan-only and validation tests**

Append imports and tests:

```python
import io
import os
import tempfile
from pathlib import Path

from tools.dci_benchmark_orchestrator import (
    OrchestratorError,
    RunOptions,
    build_plan,
    render_plan,
)


class BenchmarkPlanTests(unittest.TestCase):
    def test_default_plan_is_bounded_body_free_and_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / ".env"
            output = root / "private-output"
            env_file.write_text(
                "ASTERION_DCI_RESOURCE_ROOT=resources\n"
                "ASTERION_DCI_OUTPUT_ROOT=private-output\n"
                "DEEPSEEK_API_KEY=sentinel-secret\n",
                encoding="utf-8",
            )
            stream = io.StringIO()
            plan = build_plan(
                RunOptions(env_file=env_file),
                process_environment={"PATH": os.environ.get("PATH", "")},
                invocation_cwd=root,
                run_label="fixture-run",
            )
            render_plan(plan, stream)
            text = stream.getvalue()

            self.assertEqual(plan.options.suite, "all")
            self.assertEqual(plan.options.limit, 1)
            self.assertEqual(plan.options.max_concurrency, 1)
            self.assertFalse(plan.options.execute)
            self.assertEqual(len(plan.tasks), 15)
            self.assertFalse(output.exists())
            self.assertIn("mode=PLAN", text)
            self.assertIn("tasks=15", text)
            self.assertIn("no USD ledger", text)
            self.assertNotIn("sentinel-secret", text)
            self.assertNotIn(str(root), text)

    def test_process_environment_overrides_dotenv_without_logging_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env_file = root / "operator.env"
            env_file.write_text(
                "DCI_MODEL=dotenv-model\nASTERION_DCI_RESOURCE_ROOT=dotenv-root\n",
                encoding="utf-8",
            )
            plan = build_plan(
                RunOptions(env_file=env_file),
                process_environment={
                    "DCI_MODEL": "process-model",
                    "ASTERION_DCI_RESOURCE_ROOT": str(root / "process-root"),
                },
                invocation_cwd=root,
                run_label="fixture-run",
            )
            self.assertEqual(plan.environment["DCI_MODEL"], "process-model")
            self.assertEqual(plan.resource_root, root / "process-root")

    def test_invalid_positive_integer_and_missing_env_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing.env"
            with self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark env file is unavailable$"
            ):
                build_plan(
                    RunOptions(env_file=missing),
                    process_environment={},
                    invocation_cwd=root,
                    run_label="fixture-run",
                )
            for value in (0, -1):
                with self.subTest(value=value), self.assertRaisesRegex(
                    OrchestratorError, "^DCI benchmark limit is invalid$"
                ):
                    RunOptions(limit=value).validate()
```

- [ ] **Step 2: Run the plan tests and verify missing interfaces**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_orchestrator.BenchmarkPlanTests
```

Expected: import failure for `OrchestratorError` or `RunOptions`.

- [ ] **Step 3: Implement plan types, dotenv precedence, and body-free rendering**

Extend `tools/dci_benchmark_orchestrator.py` with these public shapes and
equivalent private helpers:

```python
import os
import re
from dataclasses import field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence, TextIO

from dotenv import dotenv_values


PROJECT = Path(__file__).resolve().parents[1]
_SECRET_NAME = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)


class OrchestratorError(RuntimeError):
    """Stable body-free coordinator failure."""


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
        PROJECT if not resource_value.strip()
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
```

Create `tools/run_dci_benchmarks.py` with:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from dci_benchmark_orchestrator import (
    OrchestratorError,
    RunOptions,
    build_plan,
    render_plan,
)


def parse_args(argv: Sequence[str] | None = None) -> RunOptions:
    parser = argparse.ArgumentParser(description="Run Asterion DCI benchmarks")
    parser.add_argument("--suite", choices=("github", "paper-main", "all"), default="all")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env",
    )
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    return RunOptions(
        suite=args.suite,
        limit=args.limit,
        max_concurrency=args.max_concurrency,
        output_root=args.output_root,
        env_file=args.env_file,
        execute=args.execute,
    )


def _run_label() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        plan = build_plan(parse_args(argv), run_label=_run_label())
        render_plan(plan, sys.stdout)
        if not plan.options.execute:
            return 0
        from dci_benchmark_orchestrator import execute_plan
        return execute_plan(plan, stream=sys.stdout)
    except OrchestratorError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

The deferred import of `execute_plan` keeps the plan-only test red until Task
3 without calling an undefined interface.

- [ ] **Step 4: Run plan tests and CLI help**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_orchestrator.BenchmarkPlanTests
uv run python tools/run_dci_benchmarks.py --help
```

Expected: plan tests `OK`; help lists exactly the six designed options and no
cost or USD option.

- [ ] **Step 5: Commit planning and dotenv behavior**

```bash
git add tools/dci_benchmark_orchestrator.py \
  tools/run_dci_benchmarks.py tests/test_dci_benchmark_orchestrator.py
git commit -m "feat: add bounded DCI benchmark planning"
```

### Task 3: Execute sequentially with private redacted evidence

**Files:**
- Modify: `tools/dci_benchmark_orchestrator.py`
- Modify: `tests/test_dci_benchmark_orchestrator.py`

**Interfaces:**
- Consumes: `RunPlan` and `BenchmarkTask` from Tasks 1–2.
- Produces: `CommandExecutor(command, cwd, environment, on_line) -> int` callable contract.
- Produces: `build_task_command(plan, task, task_root) -> tuple[str, ...]`.
- Produces: `execute_plan(plan, *, stream, executor=stream_command, clock=time.monotonic) -> int`.
- Produces: private `runner.log` files and one body-free `summary.json`.

- [ ] **Step 1: Write failing command, sequencing, skip, failure, and redaction tests**

Append:

```python
import json
import stat
from dataclasses import replace

from tools.dci_benchmark_orchestrator import (
    BenchmarkTask,
    build_task_command,
    execute_plan,
)


class FakeExecutor:
    def __init__(self, outcomes: list[int | BaseException] | None = None) -> None:
        self.commands: list[tuple[str, ...]] = []
        self.outcomes = list(outcomes or ())

    def __call__(self, command, *, cwd, environment, on_line):
        self.commands.append(tuple(command))
        on_line("child sentinel-secret private-root-value\n")
        outcome = self.outcomes.pop(0) if self.outcomes else 0
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class BenchmarkExecutionTests(unittest.TestCase):
    def _plan(self, root: Path, **changes):
        env_file = root / ".env"
        env_file.write_text(
            f"ASTERION_DCI_RESOURCE_ROOT={root / 'resources'}\n"
            f"ASTERION_DCI_OUTPUT_ROOT={root / 'outputs'}\n"
            "DEEPSEEK_API_KEY=sentinel-secret\n"
            "PRIVATE_PATH=private-root-value\n",
            encoding="utf-8",
        )
        options = RunOptions(
            suite="github",
            env_file=env_file,
            output_root=root / "run",
            execute=True,
        )
        options = replace(options, **changes)
        return build_plan(
            options,
            process_environment={},
            invocation_cwd=root,
            run_label="fixture-run",
        )

    def test_commands_are_bounded_and_task_roots_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root, limit=2, max_concurrency=1)
            first, second = plan.tasks[:2]
            one = build_task_command(plan, first, root / "one")
            two = build_task_command(plan, second, root / "two")
            for command, output in ((one, root / "one"), (two, root / "two")):
                self.assertIn("--limit", command)
                self.assertEqual(command[command.index("--limit") + 1], "2")
                self.assertEqual(
                    command[command.index("--max-concurrency") + 1], "1"
                )
                self.assertEqual(
                    command[command.index("--resume-policy") + 1], "compatible"
                )
                self.assertEqual(
                    command[command.index("--output-root") + 1], str(output)
                )
            self.assertNotEqual(one[-1], two[-1])

    def test_paper_bamboogle_command_uses_full_125_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root, suite="all")
            task = next(
                task
                for task in plan.tasks
                if task.task_id == "qa.bamboogle.paper-full125"
            )
            command = build_task_command(plan, task, root / "paper-bamboogle")
            self.assertEqual(
                command[0:5],
                (
                    "uv",
                    "run",
                    "--project",
                    str(Path(__file__).resolve().parents[1]),
                    "asterion-dci",
                ),
            )
            self.assertEqual(
                command[command.index("--dataset") + 1],
                str(
                    plan.resource_root
                    / "paper-full/data/bamboogle/test-125.jsonl"
                ),
            )

    def test_resource_check_precedes_sequential_tasks_and_failure_stops(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            executor = FakeExecutor([0, 0, 7])
            stream = io.StringIO()
            result = execute_plan(plan, stream=stream, executor=executor)

            self.assertEqual(result, 7)
            self.assertIn("setup_resources.py", " ".join(executor.commands[0]))
            self.assertEqual(len(executor.commands), 3)
            self.assertIn("[1/12]", stream.getvalue())
            self.assertIn("DONE", stream.getvalue())
            self.assertIn("FAILED exit=7", stream.getvalue())
            self.assertIn("elapsed=", stream.getvalue())
            self.assertRegex(
                stream.getvalue(),
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00",
            )
            self.assertNotIn("sentinel-secret", stream.getvalue())
            self.assertNotIn("private-root-value", stream.getvalue())

            summary = json.loads((root / "run" / "summary.json").read_text())
            self.assertEqual(
                stat.S_IMODE((root / "run" / "summary.json").stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(
                    (root / "run" / "bcplus.level3" / "runner.log").stat().st_mode
                ),
                0o600,
            )
            runner_log = (
                root / "run" / "bcplus.level3" / "runner.log"
            ).read_text(encoding="utf-8")
            self.assertIn("<redacted>", runner_log)
            self.assertNotIn("sentinel-secret", runner_log)
            self.assertNotIn("private-root-value", runner_log)
            self.assertEqual(summary["tasks"][0]["status"], "DONE")
            self.assertEqual(summary["tasks"][1]["status"], "FAILED")
            self.assertTrue(
                all(item["status"] == "NOT_RUN" for item in summary["tasks"][2:])
            )
            encoded = json.dumps(summary, sort_keys=True)
            self.assertNotIn(str(root), encoded)
            self.assertNotIn("sentinel-secret", encoded)
            self.assertNotIn("private-root-value", encoded)

    def test_failed_resource_check_creates_no_run_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            executor = FakeExecutor([4])
            self.assertEqual(
                execute_plan(plan, stream=io.StringIO(), executor=executor), 4
            )
            self.assertEqual(len(executor.commands), 1)
            self.assertFalse(plan.output_base.exists())

    def test_missing_task_binding_fails_before_resource_or_provider_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            missing = replace(
                plan.tasks[0], launcher="scripts/missing-launcher.sh"
            )
            plan = replace(plan, tasks=(missing,))
            executor = FakeExecutor()
            with self.assertRaisesRegex(
                OrchestratorError,
                "^DCI benchmark task binding is unavailable$",
            ):
                execute_plan(plan, stream=io.StringIO(), executor=executor)
            self.assertEqual(executor.commands, [])
            self.assertFalse(plan.output_base.exists())

    def test_skip_is_nonfatal_and_never_reported_done(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            skipped = BenchmarkTask(
                "paper.ablation.missing", ("paper-main",), "unused", None,
                None, None, "method-incomplete", "",
                skip_reason="method-incomplete",
            )
            plan = replace(plan, tasks=(skipped, plan.tasks[0]))
            executor = FakeExecutor([0, 0])
            stream = io.StringIO()
            self.assertEqual(
                execute_plan(plan, stream=stream, executor=executor), 0
            )
            self.assertIn("SKIP reason=method-incomplete", stream.getvalue())
            self.assertNotIn("paper.ablation.missing DONE", stream.getvalue())
            self.assertEqual(len(executor.commands), 2)

    def test_interrupt_finalizes_body_free_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            executor = FakeExecutor([0, KeyboardInterrupt()])
            self.assertEqual(
                execute_plan(plan, stream=io.StringIO(), executor=executor), 130
            )
            summary = json.loads((plan.output_base / "summary.json").read_text())
            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["tasks"][0]["status"], "FAILED")
            self.assertTrue(
                all(item["status"] == "NOT_RUN" for item in summary["tasks"][1:])
            )

    def test_existing_non_private_or_symlink_run_root_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            plan.output_base.mkdir(mode=0o755)
            plan.output_base.chmod(0o755)
            with self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark output root is unsafe$"
            ):
                execute_plan(plan, stream=io.StringIO(), executor=FakeExecutor())
            target = root / "target"
            target.mkdir(mode=0o700)
            linked_plan = self._plan(root, output_root=root / "linked-run")
            linked_plan.output_base.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark output root is unsafe$"
            ):
                execute_plan(
                    linked_plan, stream=io.StringIO(), executor=FakeExecutor()
                )

    def test_replaced_run_root_fails_before_later_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = self._plan(root)
            calls = 0

            def replacing_executor(command, *, cwd, environment, on_line):
                nonlocal calls
                calls += 1
                if calls == 2:
                    moved = plan.output_base.with_name("moved")
                    plan.output_base.rename(moved)
                    plan.output_base.mkdir(mode=0o700)
                return 0

            with self.assertRaisesRegex(
                OrchestratorError, "^DCI benchmark output root changed$"
            ):
                execute_plan(
                    plan, stream=io.StringIO(), executor=replacing_executor
                )
            self.assertEqual(calls, 2)
```

- [ ] **Step 2: Run execution tests and verify missing execution interfaces**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_orchestrator.BenchmarkExecutionTests
```

Expected: import failure for `build_task_command` or `execute_plan`.

- [ ] **Step 3: Implement command construction and injectable streaming**

Add:

```python
import json
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone


CommandExecutor = Callable[..., int]


def build_task_command(
    plan: RunPlan, task: BenchmarkTask, task_root: Path
) -> tuple[str, ...]:
    common = (
        "--limit", str(plan.options.limit),
        "--max-concurrency", str(plan.options.max_concurrency),
        "--resume-policy", "compatible",
        "--output-root", str(task_root),
    )
    if task.launcher is not None:
        launcher = PROJECT / task.launcher
        if not launcher.is_file():
            raise OrchestratorError("DCI benchmark task binding is unavailable")
        return (str(launcher), *common)
    if task.dataset is None or task.corpus is None:
        raise OrchestratorError("DCI benchmark task binding is unavailable")
    return (
        "uv", "run", "--project", str(PROJECT), "asterion-dci", "benchmark",
        "--profile", task.profile,
        "--dataset", str(plan.resource_root / task.dataset),
        "--corpus", str(plan.resource_root / task.corpus),
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
    ordered = sorted((value for value in values if len(value) >= 4), key=len, reverse=True)

    def redact(line: str) -> str:
        for value in ordered:
            line = line.replace(value, "<redacted>")
        return line

    return redact
```

The task execution step must use this callback for both terminal output and
`runner.log`; it must never persist the unredacted line.

- [ ] **Step 4: Implement private root identity, logs, failure stopping, and summary**

Add private helpers with these exact rules:

```python
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


def _write_summary(root: Path, identity: tuple[int, int], payload: object) -> None:
    try:
        current = root.stat()
    except OSError:
        raise OrchestratorError("DCI benchmark output root changed") from None
    if (current.st_dev, current.st_ino) != identity or root.is_symlink():
        raise OrchestratorError("DCI benchmark output root changed")
    temporary = root / ".summary.json.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError:
        raise OrchestratorError("DCI benchmark summary is unsafe") from None
    try:
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = -1
        with handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        try:
            os.replace(temporary, root / "summary.json")
        except OSError:
            raise OrchestratorError("DCI benchmark summary is unsafe") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
```

Implement `execute_plan()` so it:

1. Runs `(sys.executable, PROJECT / "tools/setup_resources.py",
   "--profile", "benchmark", "--check")` through the injected executor.
2. Returns the nonzero resource-check status before creating `output_base`.
3. Creates/reopens `output_base` as mode `0700` and retains its `(device,
   inode)` identity.
4. Creates each filesystem-safe task child as mode `0700`, and `runner.log` as
   mode `0600` using `O_NOFOLLOW`.
5. Emits timestamped `START`, `DONE`, `FAILED`, and `SKIP` lines using
   `time.monotonic()` elapsed seconds.
6. Stops after the first nonzero task exit and leaves later statuses
   `NOT_RUN`.
7. Writes `summary.json` containing only:

```python
{
    "schema": "asterion.dci.benchmark-orchestrator-summary/v1",
    "suite": plan.options.suite,
    "run_label": plan.run_label,
    "limit": plan.options.limit,
    "max_concurrency": plan.options.max_concurrency,
    "status": "PASS" or "FAIL",
    "tasks": [
        {
            "task_id": task.task_id,
            "selection_variant": task.selection_variant,
            "status": "DONE" or "FAILED" or "SKIP" or "NOT_RUN",
            "exit_code": int_or_none,
            "elapsed_seconds": rounded_float_or_none,
            "output": f"{task_slug}/batch" or None,
            "log": f"{task_slug}/runner.log" or None,
            "skip_reason": task.skip_reason,
        }
    ],
}
```

Use a filesystem slug produced by
`re.sub(r"[^a-z0-9._-]", "-", task.task_id.lower())`; reject duplicate slugs.
Before creating each task child and before every summary write, recheck the run
root identity. On `KeyboardInterrupt`, mark the active task `FAILED`, leave
later tasks `NOT_RUN`, write the summary if the root identity remains valid,
then return 130.

Use these helpers and execution loop:

```python
def _assert_identity(path: Path, identity: tuple[int, int]) -> None:
    try:
        if path.is_symlink():
            raise OrchestratorError("DCI benchmark output root changed")
        metadata = path.stat()
    except OrchestratorError:
        raise
    except OSError:
        raise OrchestratorError("DCI benchmark output root changed") from None
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or (metadata.st_dev, metadata.st_ino) != identity
    ):
        raise OrchestratorError("DCI benchmark output root changed")


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
    if not stat.S_ISREG(metadata.st_mode):
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
```

The task container holds `runner.log`; the benchmark receives its `batch`
child as `--output-root`, so coordinator evidence never violates the
benchmark batch's closed artifact inventory.

- [ ] **Step 5: Run execution and full orchestrator tests**

Run:

```bash
uv run python -m unittest -v tests.test_dci_benchmark_orchestrator
```

Expected: all tests `OK`; fake executor is the only command runner.

- [ ] **Step 6: Commit sequential execution**

```bash
git add tools/dci_benchmark_orchestrator.py \
  tests/test_dci_benchmark_orchestrator.py
git commit -m "feat: execute DCI benchmarks sequentially"
```

### Task 4: Add the stable shell entry point and operator documentation

**Files:**
- Create: `scripts/run_dci_benchmarks.sh`
- Modify: `tests/test_dci_benchmark_orchestrator.py`
- Modify: `tests/test_standalone_repository.py`
- Modify: `docs/guides/asterion-capability-usage.md`

**Interfaces:**
- Consumes: `tools/run_dci_benchmarks.py`.
- Produces: executable `scripts/run_dci_benchmarks.sh`.
- Produces: documented preview and explicit execution commands.

- [ ] **Step 1: Write failing shell entry-point tests**

Add `"scripts/run_dci_benchmarks.sh"` and
`"tools/run_dci_benchmarks.py"` to `REQUIRED_ASSETS` in
`tests/test_standalone_repository.py`.

Append:

```python
import subprocess


class BenchmarkEntrypointTests(unittest.TestCase):
    def test_shell_entrypoint_has_valid_syntax_and_exact_python_target(self) -> None:
        project = Path(__file__).resolve().parents[1]
        script = project / "scripts/run_dci_benchmarks.sh"
        syntax = subprocess.run(
            ["bash", "-n", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        text = script.read_text(encoding="utf-8")
        self.assertIn('uv run --project "$PROJECT_ROOT"', text)
        self.assertIn(
            'python "$PROJECT_ROOT/tools/run_dci_benchmarks.py" "$@"', text
        )
        self.assertNotIn("source ", text)
        self.assertNotIn(". \"$", text)

    def test_cli_help_has_no_monetary_inputs(self) -> None:
        project = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            ["uv", "run", "python", "tools/run_dci_benchmarks.py", "--help"],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--execute", completed.stdout)
        self.assertIn("--limit", completed.stdout)
        self.assertNotIn("cost", completed.stdout.lower())
        self.assertNotIn("usd", completed.stdout.lower())
        self.assertNotIn("price", completed.stdout.lower())
```

- [ ] **Step 2: Run entry-point tests and verify missing asset failures**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_orchestrator.BenchmarkEntrypointTests \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_required_repository_assets_exist
```

Expected: failures because both new entry-point files are not yet complete.

- [ ] **Step 3: Create the shell entry point**

Create `scripts/run_dci_benchmarks.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)

exec uv run --project "$PROJECT_ROOT" \
  python "$PROJECT_ROOT/tools/run_dci_benchmarks.py" "$@"
```

Run:

```bash
chmod 755 scripts/run_dci_benchmarks.sh tools/run_dci_benchmarks.py
```

- [ ] **Step 4: Document the exact operator workflow**

Add this section after the benchmark usage table in
`docs/guides/asterion-capability-usage.md`:

````markdown
### 顺序运行 DCI benchmark 清单

先预览全部 15 个任务变体；该命令不调用 Agent 或 Judge，也不创建任务输出：

```bash
scripts/run_dci_benchmarks.sh
```

显式执行一查询、单并发 smoke suite：

```bash
scripts/run_dci_benchmarks.sh \
  --suite all \
  --limit 1 \
  --max-concurrency 1 \
  --execute
```

可选 suite 为 `github`、`paper-main` 和 `all`。脚本读取仓库 `.env`
中已配置的数据、语料、Pi、输出与 Judge 设置，不下载资源。直接 benchmark
没有 USD ledger；`--limit`、单任务并发和任务间顺序执行是本入口的运行边界。
每个任务输出到独立私有目录，失败时停止后续任务，使用相同
`--output-root` 重跑会采用 `--resume-policy compatible`。

该入口生成 Asterion benchmark 证据，不自动构成论文分数复现。
````

- [ ] **Step 5: Run entry-point, repository, and docs checks**

Run:

```bash
uv run python -m unittest -v \
  tests.test_dci_benchmark_orchestrator.BenchmarkEntrypointTests \
  tests.test_standalone_repository.StandaloneRepositoryTests.test_required_repository_assets_exist
bash -n scripts/run_dci_benchmarks.sh
make docs-check
```

Expected: all tests and checks pass with zero Agent/Judge operations.

- [ ] **Step 6: Commit entry point and documentation**

```bash
git add scripts/run_dci_benchmarks.sh tools/run_dci_benchmarks.py \
  tests/test_dci_benchmark_orchestrator.py \
  tests/test_standalone_repository.py \
  docs/guides/asterion-capability-usage.md
git commit -m "docs: expose DCI benchmark orchestrator"
```

### Task 5: Verify provider-free behavior and repository integration

**Files:**
- Modify only if a verification failure proves a defect:
  `tools/dci_benchmark_orchestrator.py`,
  `tools/run_dci_benchmarks.py`,
  `scripts/run_dci_benchmarks.sh`,
  `tests/test_dci_benchmark_orchestrator.py`,
  `tests/test_standalone_repository.py`,
  `docs/guides/asterion-capability-usage.md`.

**Interfaces:**
- Consumes: the completed coordinator and entry point.
- Produces: named provider-free evidence for handoff.

- [ ] **Step 1: Run the focused suite**

```bash
uv run python -m unittest -v tests.test_dci_benchmark_orchestrator
```

Expected: all orchestrator tests pass; only fake child execution occurs.

- [ ] **Step 2: Run the real default preview**

```bash
scripts/run_dci_benchmarks.sh
```

Expected: exit 0, `mode=PLAN`, `tasks=15`, 15 `PLANNED` lines, no output
directory creation, and zero Agent/Judge operations.

- [ ] **Step 3: Run the existing provider-free benchmark resource check**

```bash
uv run python tools/setup_resources.py --profile benchmark --check
```

Expected: `PASS`, 22 resources present, Agent operations 0, Judge operations
0, full dataset no.

- [ ] **Step 4: Run repository verification**

```bash
make check
make promotion-check
```

Expected: all Python, TypeScript, Rust, lint, documentation, build,
distribution, resource, and promotion checks pass without provider-backed
operations or a full dataset run.

- [ ] **Step 5: Inspect the final diff and public surface**

```bash
git diff --check
git status --short
uv run python tools/run_dci_benchmarks.py --help
```

Expected: no whitespace errors; help exposes only suite, limit, concurrency,
output root, env file, execute, and help; existing unrelated working-tree
changes remain preserved.

- [ ] **Step 6: Commit only verified corrective edits, if Step 1–5 required them**

If verification required a correction, stage only the exact files changed for
that correction and commit:

```bash
git diff --name-only
git add --patch
git diff --cached --check
git commit -m "fix: close DCI benchmark orchestrator verification"
```

If no correction was needed, do not create an empty commit.
