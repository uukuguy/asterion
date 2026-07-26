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
