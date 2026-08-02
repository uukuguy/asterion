"""Provider-free coordination tests for the bounded DCI coverage experiment."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from asterion.applications.dci_agent_lite.benchmark_instances import (
    DciBenchmarkInstance,
)
from asterion.applications.dci_agent_lite.cli import main
from asterion.applications.dci_agent_lite.operator_config import DciOperatorConfig
from asterion.benchmarks.cli import BenchmarkCommandHost
from asterion.benchmarks.evidence import BenchmarkRunResult, BenchmarkTaskResult
from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    diagnose_recommended_pack,
)
from asterion.pathlight.diagnosis import write_diagnosis_bundle
from tests.test_dci_pathlight_diagnosis import _DATASETS, _run


_TASK_IDS = (
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "beir.scifact",
)


def _write_inputs(root: Path, *, suffix: str = "") -> None:
    paths = {
        "beir.scifact": (
            "data/dci-bench/data/beir_scifact/test.jsonl",
            "corpus/beir/scifact",
        ),
        "bright.biology": (
            "data/dci-bench/data/bright_biology/bright_biology.jsonl",
            "corpus/bright_corpus/biology",
        ),
        "bright.earth-science": (
            "data/dci-bench/data/bright_earth_science/bright_earth_science.jsonl",
            "corpus/bright_corpus/earth_science",
        ),
        "bright.economics": (
            "data/dci-bench/data/bright_economics/economics_full.jsonl",
            "corpus/bright_corpus/economics",
        ),
        "bright.robotics": (
            "data/dci-bench/data/bright_robotics/bright_robotics.jsonl",
            "corpus/bright_corpus/robotics",
        ),
    }
    for task_id, (dataset_name, corpus_name) in paths.items():
        dataset = root / dataset_name
        corpus = root / corpus_name
        dataset.parent.mkdir(parents=True, exist_ok=True)
        corpus.mkdir(parents=True, exist_ok=True)
        rows = []
        for index in range(10):
            document = f"doc-{index}.txt"
            query_id = f"{task_id}-q-{index}{suffix}"
            if task_id.startswith("beir."):
                rows.append(
                    {
                        "query_id": query_id,
                        "query": f"query {index}",
                        "answer": "",
                        "gold_ids": [document],
                    }
                )
            else:
                rows.append(
                    {
                        "query_id": query_id,
                        "query": f"query {index}",
                        "answer": "answer",
                        "excluded_ids": ["excluded.txt"],
                        "gold_ids": [document],
                        "gold_ids_long": [document],
                        "id": f"source-{query_id}",
                        "reasoning": "reasoning",
                    }
                )
            (corpus / document).write_text(f"body {index}\n", encoding="utf-8")
        dataset.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )


def _write_diagnosis(root: Path) -> tuple[Path, str]:
    report = diagnose_recommended_pack(tuple(_run(*dataset) for dataset in _DATASETS))
    diagnosis = root / "pathlight-diagnosis.json"
    write_diagnosis_bundle(report.diagnosis_bundle, diagnosis)
    proposal = next(
        item.proposal_sha256
        for item in report.proposals
        if item.code == "coverage-instrumentation"
    )
    return diagnosis, proposal


def _prepare(root: Path, *, suffix: str = "") -> tuple[Path, Path, str]:
    resource_root = root / "resources"
    _write_inputs(resource_root, suffix=suffix)
    diagnosis, proposal = _write_diagnosis(root)
    output = root / "output"
    output.mkdir(mode=0o700)
    code = main(
        [
            "pathlight",
            "experiment",
            "prepare",
            "--diagnosis-file",
            str(diagnosis),
            "--proposal-sha256",
            proposal,
            "--output-root",
            str(output),
        ],
        repo_root=root,
        environment={"ASTERION_DCI_RESOURCE_ROOT": str(resource_root)},
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    if code != 0:
        raise AssertionError("coverage experiment preparation failed")
    return output / "pathlight-coverage-experiment.json", output, proposal


def _execution_environment(root: Path) -> dict[str, str]:
    return {
        "ASTERION_DCI_RESOURCE_ROOT": str(root / "resources"),
        "PRIVATE_SENTINEL": "must-not-leak",
    }


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _write_authorization(root: Path, plan_path: Path) -> Path:
    plan = json.loads(plan_path.read_bytes())
    body = {
        "schema": "asterion.dci.pathlight.coverage-experiment-authorization/v1",
        "plan_sha256": plan["plan_sha256"],
        "proposal_sha256": plan["proposal_sha256"],
        "scope_sha256": plan["scope_sha256"],
        "variant_sha256": plan["variant_sha256"],
        "registry_set_sha256": plan["registry_set_sha256"],
        "max_agent_operations": 50,
        "max_cost_microusd": 5_000_000,
        "max_infrastructure_failures": 2,
        "execution_authorized": True,
        "operator_approval_sha256": hashlib.sha256(b"operator approval").hexdigest(),
    }
    body["authorization_sha256"] = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    path = root / "coverage-authorization.json"
    path.write_bytes(_canonical_bytes(body))
    path.chmod(0o600)
    return path


class _RecordingHost:
    def __init__(
        self,
        task_id: str,
        events: list[str],
        outcomes: dict[str, list[str]],
        authorized_cost_microusd: int,
    ) -> None:
        self.task_id = task_id
        self.events = events
        self.outcomes = outcomes
        self.authorized_cost_microusd = authorized_cost_microusd

    def discover_metadata(self, **_kwargs: object) -> object:
        self.events.append(f"preflight:{self.task_id}:metadata")
        return object()

    def resolve_source_lock(self, _path: Path) -> object:
        self.events.append(f"preflight:{self.task_id}:lock")
        return object()

    def open_selected_payloads(self, _metadata: object, _lock: object) -> object:
        self.events.append(f"preflight:{self.task_id}:payload")
        return object()

    def resolve_application(self, _payloads: object, **_kwargs: object) -> object:
        self.events.append(f"preflight:{self.task_id}:application")
        return object()

    def create_plan(
        self,
        _resolved: object,
        *,
        execute: bool,
        resume_run_id: str | None,
        **_kwargs: object,
    ) -> object:
        if not execute:
            self.events.append(f"preflight:{self.task_id}:plan")
        generation = sum(
            event == f"authorize:{self.task_id}:new" for event in self.events
        )
        run_id = resume_run_id or f"run-{self.task_id}-{generation}"
        return SimpleNamespace(case_limit=10, run_id=run_id)

    def authorize_execution(
        self, *, resume_run_id: str | None, **_kwargs: object
    ) -> object:
        self.events.append(f"authorize:{self.task_id}:{resume_run_id or 'new'}")
        return object()

    def load_selected_providers(
        self, _payloads: object, _authorization: object
    ) -> object:
        self.events.append(f"provider:{self.task_id}")
        return object()

    def run(
        self, _plan: object, _providers: object, **_kwargs: object
    ) -> BenchmarkRunResult:
        self.events.append(f"run:{self.task_id}")
        values = self.outcomes.get(self.task_id, ["completed"])
        outcome = values.pop(0) if values else "completed"
        status, separator, raw_consumed = outcome.partition(":")
        consumed = int(raw_consumed) if separator else 0
        return BenchmarkRunResult(
            status,
            (
                BenchmarkTaskResult(
                    self.task_id,
                    status,
                    10 if status == "completed" else 0,
                    tuple(
                        sorted(
                            (
                                f"coverage-actual-microusd.{consumed}",
                                "coverage-authorized-microusd."
                                f"{self.authorized_cost_microusd}",
                            )
                        )
                    ),
                ),
            ),
        )


def _host_factory(
    events: list[str], outcomes: dict[str, list[str]]
) -> Callable[..., BenchmarkCommandHost]:
    def create(
        *,
        instance: DciBenchmarkInstance,
        operator_config: DciOperatorConfig,
        **_kwargs: object,
    ) -> BenchmarkCommandHost:
        task_id = instance.task_ids[0]
        inputs = operator_config.benchmark_inputs
        if set(inputs.coverage_registry_roots) != set(_TASK_IDS):
            raise AssertionError("coverage registries were not bound")
        amount = inputs.amount
        if amount is None or not Decimal("0") < amount <= Decimal("1"):
            raise AssertionError("per-task budget is outside its one dollar envelope")
        authorized = int(amount * Decimal(1_000_000))
        events.append(f"budget:{task_id}:{authorized}")
        return cast(
            BenchmarkCommandHost,
            _RecordingHost(task_id, events, outcomes, authorized),
        )

    return create


class TestDciPathlightExperimentCli(unittest.TestCase):
    def test_prepare_builds_exact_five_by_ten_scope_without_loading_provider(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            resource_root = root / "resources"
            _write_inputs(resource_root)
            diagnosis, proposal = _write_diagnosis(root)
            output = root / "output"
            output.mkdir(mode=0o700)
            stdout, stderr = io.StringIO(), io.StringIO()

            with patch(
                "asterion.capability_packages.sources.builtin."
                "BuiltinCapabilitySource.load_provider",
                side_effect=AssertionError("provider loaded during prepare"),
            ):
                code = main(
                    [
                        "pathlight",
                        "experiment",
                        "prepare",
                        "--diagnosis-file",
                        str(diagnosis),
                        "--proposal-sha256",
                        proposal,
                        "--output-root",
                        str(output),
                    ],
                    repo_root=root,
                    environment={"ASTERION_DCI_RESOURCE_ROOT": str(resource_root)},
                    stdout=stdout,
                    stderr=stderr,
                )

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            plan_path = output / "pathlight-coverage-experiment.json"
            plan = json.loads(plan_path.read_bytes())
            self.assertEqual(plan["max_agent_operations"], 50)
            self.assertEqual(plan["max_cost_microusd"], 5_000_000)
            self.assertEqual(plan["max_infrastructure_failures"], 2)
            self.assertFalse(plan["execution_authorized"])
            self.assertEqual(
                tuple(task["instance_selector"] for task in plan["tasks"]),
                tuple(f"dci.{task_id}@1.0.0" for task_id in _TASK_IDS),
            )
            self.assertEqual(
                tuple(task["case_limit"] for task in plan["tasks"]), (10,) * 5
            )
            self.assertTrue(
                all(
                    (output / task["registry_path"]).is_file() for task in plan["tasks"]
                )
            )

    def test_execute_rejects_missing_or_changed_authority_before_provider_or_network(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            wrong_authority = root / "wrong-authorization.json"
            wrong_authority.write_text("{}\n", encoding="utf-8")
            wrong_authority.chmod(0o600)
            stdout, stderr = io.StringIO(), io.StringIO()

            with patch(
                "asterion.applications.dci_agent_lite.benchmark_host."
                "DciBenchmarkHost.run"
            ) as run:
                code = main(
                    [
                        "pathlight",
                        "experiment",
                        "execute",
                        "--plan-file",
                        str(plan),
                        "--authorization-file",
                        str(wrong_authority),
                        "--output-root",
                        str(output),
                    ],
                    repo_root=root,
                    environment={"PRIVATE_SENTINEL": "must-not-leak"},
                    stdout=stdout,
                    stderr=stderr,
                )

            self.assertEqual(code, 2)
            run.assert_not_called()
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "asterion-dci: command failed\n")
            self.assertNotIn(str(root), stderr.getvalue())
            self.assertNotIn("must-not-leak", stderr.getvalue())

    def test_execute_preflights_all_five_then_runs_sequentially_without_judge(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            env_file = root / ".env"
            env_file.write_text(
                "DEEPSEEK_API_KEY=SENTINEL_ENV_PRIVATE_JUDGE_KEY\n",
                encoding="utf-8",
            )
            env_file.chmod(0o600)
            events: list[str] = []
            stdout, stderr = io.StringIO(), io.StringIO()

            code = main(
                [
                    "pathlight",
                    "experiment",
                    "execute",
                    "--plan-file",
                    str(plan),
                    "--authorization-file",
                    str(authorization),
                    "--output-root",
                    str(output),
                ],
                repo_root=root,
                env_file=env_file,
                environment=_execution_environment(root),
                experiment_host_factory=_host_factory(events, {}),
                stdout=stdout,
                stderr=stderr,
            )

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            first_provider = next(
                index
                for index, event in enumerate(events)
                if event.startswith("provider:")
            )
            self.assertEqual(
                sum(event.endswith(":plan") for event in events[:first_provider]), 5
            )
            self.assertEqual(
                [
                    event.removeprefix("run:")
                    for event in events
                    if event.startswith("run:")
                ],
                list(_TASK_IDS),
            )
            public = json.loads(stdout.getvalue())
            self.assertEqual(public["case_count"], 50)
            self.assertEqual(public["completed_task_count"], 5)
            self.assertEqual(public["max_cost_microusd"], 5_000_000)
            self.assertEqual(public["status"], "completed")
            self.assertNotIn("must-not-leak", stdout.getvalue())
            self.assertNotIn("SENTINEL_ENV_PRIVATE_JUDGE_KEY", stdout.getvalue())
            self.assertNotIn(str(root), stdout.getvalue())

            status_stdout = io.StringIO()
            self.assertEqual(
                main(
                    [
                        "pathlight",
                        "experiment",
                        "status",
                        "--plan-file",
                        str(plan),
                        "--output-root",
                        str(output),
                    ],
                    stdout=status_stdout,
                    stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(
                json.loads(status_stdout.getvalue())["status"], "completed"
            )

            prior_runs = len([event for event in events if event.startswith("run:")])
            self.assertEqual(
                main(
                    [
                        "pathlight",
                        "experiment",
                        "execute",
                        "--plan-file",
                        str(plan),
                        "--authorization-file",
                        str(authorization),
                        "--output-root",
                        str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(events, {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                2,
            )
            self.assertEqual(
                len([event for event in events if event.startswith("run:")]), prior_runs
            )

    def test_cancelled_item_resumes_in_new_bound_generation_before_remaining(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            events: list[str] = []
            outcomes = {"bright.biology": ["cancelled:250000", "completed"]}
            arguments = [
                "pathlight",
                "experiment",
                "execute",
                "--plan-file",
                str(plan),
                "--authorization-file",
                str(authorization),
                "--output-root",
                str(output),
            ]

            self.assertEqual(
                main(
                    arguments,
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(events, outcomes),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                130,
            )
            self.assertEqual(
                [event for event in events if event.startswith("run:")],
                ["run:bright.biology"],
            )

            second_stdout = io.StringIO()
            self.assertEqual(
                main(
                    arguments,
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(events, outcomes),
                    stdout=second_stdout,
                    stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(events.count("authorize:bright.biology:new"), 2)
            self.assertEqual(events.count("budget:bright.biology:750000"), 1)
            receipts = sorted((output / "receipts").glob("receipt-1-*.json"))
            self.assertEqual(len(receipts), 2)
            self.assertEqual(
                json.loads(receipts[0].read_bytes())["consumed_cost_microusd"],
                250000,
            )
            self.assertEqual(
                json.loads(receipts[1].read_bytes())["authorized_cost_microusd"],
                750000,
            )
            self.assertNotEqual(
                json.loads(receipts[0].read_bytes())["run_id"],
                json.loads(receipts[1].read_bytes())["run_id"],
            )
            self.assertEqual(json.loads(second_stdout.getvalue())["case_count"], 50)

    def test_second_infrastructure_failure_stops_before_third_launch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            events: list[str] = []
            outcomes = {
                "bright.biology": ["failed"],
                "bright.earth-science": ["failed"],
            }
            stdout = io.StringIO()

            code = main(
                [
                    "pathlight",
                    "experiment",
                    "execute",
                    "--plan-file",
                    str(plan),
                    "--authorization-file",
                    str(authorization),
                    "--output-root",
                    str(output),
                ],
                repo_root=root,
                environment=_execution_environment(root),
                experiment_host_factory=_host_factory(events, outcomes),
                stdout=stdout,
                stderr=io.StringIO(),
            )

            self.assertEqual(code, 1)
            self.assertEqual(
                [
                    event.removeprefix("run:")
                    for event in events
                    if event.startswith("run:")
                ],
                ["bright.biology", "bright.earth-science"],
            )
            self.assertNotIn("run:bright.economics", events)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "failed")

    def test_partial_registry_and_cross_swapped_authority_fail_before_host(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first = root / "first"
            second = root / "second"
            first.mkdir(mode=0o700)
            second.mkdir(mode=0o700)
            first_plan, first_output, _proposal = _prepare(first)
            second_plan, _second_output, _proposal = _prepare(second, suffix="-other")
            crossed_authority = _write_authorization(root, second_plan)
            events: list[str] = []
            arguments = [
                "pathlight",
                "experiment",
                "execute",
                "--plan-file",
                str(first_plan),
                "--authorization-file",
                str(crossed_authority),
                "--output-root",
                str(first_output),
            ]
            self.assertEqual(
                main(
                    arguments,
                    repo_root=root,
                    environment=_execution_environment(first),
                    experiment_host_factory=_host_factory(events, {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                2,
            )
            self.assertFalse(any(event.startswith("provider:") for event in events))
            self.assertFalse(any(event.startswith("run:") for event in events))

            correct_authority = _write_authorization(first, first_plan)
            (first_output / "coverage/bright.robotics/registry.json").unlink()
            arguments[arguments.index(str(crossed_authority))] = str(correct_authority)
            self.assertEqual(
                main(
                    arguments,
                    repo_root=root,
                    environment=_execution_environment(first),
                    experiment_host_factory=_host_factory(events, {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                2,
            )
            self.assertFalse(any(event.startswith("provider:") for event in events))
            self.assertFalse(any(event.startswith("run:") for event in events))

    def test_repeated_plan_and_non_private_authority_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan_path, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan_path)
            events: list[str] = []

            authorization.chmod(0o644)
            self.assertEqual(
                main(
                    [
                        "pathlight",
                        "experiment",
                        "execute",
                        "--plan-file",
                        str(plan_path),
                        "--authorization-file",
                        str(authorization),
                        "--output-root",
                        str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(events, {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                2,
            )
            self.assertEqual(events, [])

            plan = json.loads(plan_path.read_bytes())
            plan["tasks"][1] = dict(plan["tasks"][0])
            plan["registry_set_sha256"] = hashlib.sha256(
                _canonical_bytes(
                    [
                        {
                            "task_id": task["task_id"],
                            "registry_sha256": task["registry_sha256"],
                            "selected_ids_sha256": task["selected_ids_sha256"],
                        }
                        for task in plan["tasks"]
                    ]
                )
            ).hexdigest()
            plan.pop("plan_sha256")
            plan["plan_sha256"] = hashlib.sha256(_canonical_bytes(plan)).hexdigest()
            plan_path.unlink()
            plan_path.write_bytes(_canonical_bytes(plan))
            plan_path.chmod(0o600)
            authorization.unlink()
            authorization = _write_authorization(root, plan_path)
            self.assertEqual(
                main(
                    [
                        "pathlight",
                        "experiment",
                        "execute",
                        "--plan-file",
                        str(plan_path),
                        "--authorization-file",
                        str(authorization),
                        "--output-root",
                        str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(events, {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                2,
            )
            self.assertEqual(events, [])

    def test_prepare_rolls_back_all_staged_outputs_and_status_is_read_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            resource_root = root / "resources"
            _write_inputs(resource_root)
            diagnosis, proposal = _write_diagnosis(root)
            output = root / "output"
            output.mkdir(mode=0o700)
            arguments = [
                "pathlight",
                "experiment",
                "prepare",
                "--diagnosis-file",
                str(diagnosis),
                "--proposal-sha256",
                proposal,
                "--output-root",
                str(output),
            ]

            with patch(
                "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
                "write_private_file",
                side_effect=RuntimeError("SENTINEL_PRIVATE_PLAN"),
            ):
                self.assertEqual(
                    main(
                        arguments,
                        repo_root=root,
                        environment={"ASTERION_DCI_RESOURCE_ROOT": str(resource_root)},
                        stdout=io.StringIO(),
                        stderr=io.StringIO(),
                    ),
                    2,
                )
            self.assertEqual(tuple(output.iterdir()), ())

            self.assertEqual(
                main(
                    arguments,
                    repo_root=root,
                    environment={"ASTERION_DCI_RESOURCE_ROOT": str(resource_root)},
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )
            before = tuple(
                sorted(
                    (str(path.relative_to(output)), path.stat().st_mtime_ns)
                    for path in output.rglob("*")
                )
            )
            status_stdout = io.StringIO()
            self.assertEqual(
                main(
                    [
                        "pathlight",
                        "experiment",
                        "status",
                        "--plan-file",
                        str(output / "pathlight-coverage-experiment.json"),
                        "--output-root",
                        str(output),
                    ],
                    stdout=status_stdout,
                    stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(json.loads(status_stdout.getvalue())["status"], "prepared")
            after = tuple(
                sorted(
                    (str(path.relative_to(output)), path.stat().st_mtime_ns)
                    for path in output.rglob("*")
                )
            )
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
