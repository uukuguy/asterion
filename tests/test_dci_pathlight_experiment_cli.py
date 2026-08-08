"""Provider-free coordination tests for the bounded DCI coverage experiment."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from collections.abc import Callable, Mapping
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

from asterion.applications.dci_agent_lite.benchmark_instances import (
    DciBenchmarkInstance,
)
from asterion.applications.dci_agent_lite.cli import main
from asterion.applications.dci_agent_lite import pathlight_experiment_cli as experiment_cli
from asterion.applications.dci_agent_lite.pathlight_experiment_cli import (
    _seal_completed_native_task,
    read_completed_coverage_experiment,
)
from asterion.applications.dci_agent_lite.operator_config import DciOperatorConfig
from asterion.benchmarks.cli import BenchmarkCommandHost
from asterion.benchmarks.evidence import BenchmarkRunResult, BenchmarkTaskResult
from asterion.capabilities.dci.implementation.evaluation.artifacts import (
    pathlight_trace_id,
)
from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    DciCoverageDatasetObservation,
    diagnose_recommended_pack,
)
from asterion.capabilities.dci.implementation.pathlight.recovery import (
    DciRecoveryError,
    read_completed_dci_run,
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
_NATIVE_FIXTURE = Path(__file__).parent / "fixtures" / "dci" / "pathlight-recovery"


def _exact_observation(task_id: str) -> DciCoverageDatasetObservation:
    return DciCoverageDatasetObservation(
        dataset_id=task_id,
        coverage_available_queries=10,
        coverage_total_queries=10,
        coverage_median_any_microunits=1_000_000,
        coverage_median_mean_microunits=500_000,
        coverage_median_all_microunits=0,
        retained_available_queries=10,
        retained_median_microunits=500_000,
        tool_observation_count=20,
        surfaced_gold_count=10,
        model_call_count=10,
        context_frame_count=10,
        missing_boundary_count=0,
        integrity_failure_count=0,
        evidence_sha256=hashlib.sha256(task_id.encode()).hexdigest(),
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


def _prepare(
    root: Path,
    *,
    suffix: str = "",
    environment_overrides: Mapping[str, str] | None = None,
) -> tuple[Path, Path, str]:
    resource_root = root / "resources"
    _write_inputs(resource_root, suffix=suffix)
    diagnosis, proposal = _write_diagnosis(root)
    output = root / "output"
    output.mkdir(mode=0o700)
    environment = {"ASTERION_DCI_RESOURCE_ROOT": str(resource_root)}
    if environment_overrides is not None:
        environment.update(environment_overrides)
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
        environment=environment,
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
        "execution_config_sha256": plan["execution_config_sha256"],
        "operator_root_sha256": experiment_cli._operator_root_binding_sha256(
            plan_path.parent
        ),
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


def _write_recovery_authorization(root: Path, plan_path: Path) -> Path:
    plan = json.loads(plan_path.read_bytes())
    body = {
        "schema": "asterion.dci.pathlight.coverage-recovery-authorization/v1",
        "plan_sha256": plan["plan_sha256"],
        "parent_plan_sha256": plan["parent_plan_sha256"],
        "operator_root_sha256": experiment_cli._operator_root_binding_sha256(
            plan_path.parent
        ),
        "max_agent_operations": 20,
        "max_cost_microusd": 2_000_000,
        "execution_authorized": True,
        "operator_approval_sha256": hashlib.sha256(b"recovery approval").hexdigest(),
    }
    body["authorization_sha256"] = hashlib.sha256(_canonical_bytes(body)).hexdigest()
    path = root / "recovery-authorization.json"
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
    events: list[str], outcomes: dict[str, list[str]], *, expected_coverage_tasks: set[str] | None = None
) -> Callable[..., BenchmarkCommandHost]:
    def create(
        *,
        instance: DciBenchmarkInstance,
        operator_config: DciOperatorConfig,
        **_kwargs: object,
    ) -> BenchmarkCommandHost:
        task_id = instance.task_ids[0]
        inputs = operator_config.benchmark_inputs
        if set(inputs.coverage_registry_roots) != (
            set(_TASK_IDS) if expected_coverage_tasks is None else expected_coverage_tasks
        ):
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
    def setUp(self) -> None:
        self._native_seal_patch = patch(
            "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
            "_seal_completed_native_task",
            side_effect=lambda **kwargs: _exact_observation(
                str(kwargs["task"]["task_id"])
            ),
        )
        self._native_seal_patch.start()
        self.addCleanup(self._native_seal_patch.stop)

    def test_development_status_accepts_omitted_authorization_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            stdout = io.StringIO()
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "status",
                        "--plan-file", str(plan),
                        "--output-root", str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    stdout=stdout,
                    stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(json.loads(stdout.getvalue())["status"], "prepared")

    def test_development_status_reads_historical_explicit_authorization_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "execute",
                        "--plan-file", str(plan),
                        "--authorization-file", str(authorization),
                        "--output-root", str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory([], {}),
                    stdout=io.StringIO(), stderr=io.StringIO(),
                ),
                0,
            )
            stdout = io.StringIO()
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "status",
                        "--plan-file", str(plan),
                        "--output-root", str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    stdout=stdout, stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(json.loads(stdout.getvalue())["status"], "completed")

    def test_development_execute_accepts_omitted_authorization_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            events: list[str] = []
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "execute",
                        "--plan-file", str(plan),
                        "--output-root", str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(events, {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(len([event for event in events if event.startswith("run:")]), 5)

    def test_production_execute_rejects_omitted_authorization_before_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            events: list[str] = []
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "execute",
                        "--plan-file", str(plan),
                        "--output-root", str(output),
                    ],
                    repo_root=root,
                    environment={
                        **_execution_environment(root),
                        "ASTERION_DCI_REQUIRE_EXECUTION_AUTHORIZATION": "1",
                    },
                    experiment_host_factory=_host_factory(events, {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                2,
            )
            self.assertEqual(events, [])

    def test_prepare_recovery_selects_only_failed_tasks_and_binds_completed_receipts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent_plan, parent_root, _proposal = _prepare(root)
            authorization = _write_authorization(root, parent_plan)
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "execute",
                        "--plan-file", str(parent_plan),
                        "--authorization-file", str(authorization),
                        "--output-root", str(parent_root),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(
                        [], {"bright.economics": ["failed"], "beir.scifact": ["failed"]}
                    ),
                    stdout=io.StringIO(), stderr=io.StringIO(),
                ),
                1,
            )
            recovery_root = root / "recovery"
            recovery_root.mkdir(mode=0o700)
            stdout = io.StringIO()
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "prepare-recovery",
                        "--parent-plan-file", str(parent_plan),
                        "--parent-authorization-file", str(authorization),
                        "--parent-output-root", str(parent_root),
                        "--output-root", str(recovery_root),
                    ],
                    repo_root=root,
                    environment={"PRIVATE_SENTINEL": "must-not-leak"},
                    stdout=stdout, stderr=io.StringIO(),
                ),
                0,
            )
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["case_count"], 20)
            retry = json.loads(
                (recovery_root / "pathlight-coverage-recovery.json").read_bytes()
            )
            self.assertEqual(
                [task["task_id"] for task in retry["tasks"]],
                ["bright.economics", "beir.scifact"],
            )
            self.assertEqual(len(retry["completed_receipts"]), 3)

    def test_development_prepare_recovery_omits_parent_authorization_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent_plan, parent_root, _proposal = _prepare(root)
            self.assertEqual(
                main(
                    ["pathlight", "experiment", "execute", "--plan-file", str(parent_plan), "--output-root", str(parent_root)],
                    repo_root=root, environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(
                        [], {"bright.economics": ["failed"], "beir.scifact": ["failed"]}
                    ), stdout=io.StringIO(), stderr=io.StringIO(),
                ),
                1,
            )
            recovery_root = root / "recovery"
            recovery_root.mkdir(mode=0o700)
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "prepare-recovery",
                        "--parent-plan-file", str(parent_plan),
                        "--parent-output-root", str(parent_root),
                        "--output-root", str(recovery_root),
                    ],
                    repo_root=root, environment=_execution_environment(root),
                    stdout=io.StringIO(), stderr=io.StringIO(),
                ),
                0,
            )

    def test_development_recovery_status_omits_authorization_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent_plan, parent_root, _proposal = _prepare(root)
            main(
                ["pathlight", "experiment", "execute", "--plan-file", str(parent_plan), "--output-root", str(parent_root)],
                repo_root=root, environment=_execution_environment(root),
                experiment_host_factory=_host_factory(
                    [], {"bright.economics": ["failed"], "beir.scifact": ["failed"]}
                ), stdout=io.StringIO(), stderr=io.StringIO(),
            )
            recovery_root = root / "recovery"
            recovery_root.mkdir(mode=0o700)
            main(
                ["pathlight", "experiment", "prepare-recovery", "--parent-plan-file", str(parent_plan), "--parent-output-root", str(parent_root), "--output-root", str(recovery_root)],
                repo_root=root, environment=_execution_environment(root), stdout=io.StringIO(), stderr=io.StringIO(),
            )
            stdout = io.StringIO()
            self.assertEqual(
                main(
                    ["pathlight", "experiment", "status-recovery", "--plan-file", str(recovery_root / "pathlight-coverage-recovery.json"), "--output-root", str(recovery_root)],
                    repo_root=root, environment=_execution_environment(root), stdout=stdout, stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(json.loads(stdout.getvalue())["status"], "prepared")

    def test_development_execute_recovery_omits_authorization_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent_plan, parent_root, _proposal = _prepare(root)
            main(
                ["pathlight", "experiment", "execute", "--plan-file", str(parent_plan), "--output-root", str(parent_root)],
                repo_root=root, environment=_execution_environment(root),
                experiment_host_factory=_host_factory(
                    [], {"bright.economics": ["failed"], "beir.scifact": ["failed"]}
                ), stdout=io.StringIO(), stderr=io.StringIO(),
            )
            recovery_root = root / "recovery"
            recovery_root.mkdir(mode=0o700)
            main(
                ["pathlight", "experiment", "prepare-recovery", "--parent-plan-file", str(parent_plan), "--parent-output-root", str(parent_root), "--output-root", str(recovery_root)],
                repo_root=root, environment=_execution_environment(root), stdout=io.StringIO(), stderr=io.StringIO(),
            )
            events: list[str] = []
            self.assertEqual(
                main(
                    ["pathlight", "experiment", "execute-recovery", "--plan-file", str(recovery_root / "pathlight-coverage-recovery.json"), "--output-root", str(recovery_root), "--parent-plan-file", str(parent_plan), "--parent-output-root", str(parent_root)],
                    repo_root=root, environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(events, {}, expected_coverage_tasks={"bright.economics", "beir.scifact"}),
                    stdout=io.StringIO(), stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual([event for event in events if event.startswith("run:")], ["run:bright.economics", "run:beir.scifact"])

    def test_recovery_status_requires_exact_bound_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent_plan, parent_root, _proposal = _prepare(root)
            parent_authorization = _write_authorization(root, parent_plan)
            main(
                [
                    "pathlight", "experiment", "execute",
                    "--plan-file", str(parent_plan),
                    "--authorization-file", str(parent_authorization),
                    "--output-root", str(parent_root),
                ],
                repo_root=root,
                environment=_execution_environment(root),
                experiment_host_factory=_host_factory(
                    [], {"bright.economics": ["failed"], "beir.scifact": ["failed"]}
                ),
                stdout=io.StringIO(), stderr=io.StringIO(),
            )
            recovery_root = root / "recovery"
            recovery_root.mkdir(mode=0o700)
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "prepare-recovery",
                        "--parent-plan-file", str(parent_plan),
                        "--parent-authorization-file", str(parent_authorization),
                        "--parent-output-root", str(parent_root),
                        "--output-root", str(recovery_root),
                    ],
                    repo_root=root, environment={}, stdout=io.StringIO(), stderr=io.StringIO(),
                ),
                0,
            )
            recovery_plan = recovery_root / "pathlight-coverage-recovery.json"
            authorization = _write_recovery_authorization(root, recovery_plan)
            stdout = io.StringIO()
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "status-recovery",
                        "--plan-file", str(recovery_plan),
                        "--authorization-file", str(authorization),
                        "--output-root", str(recovery_root),
                    ],
                    repo_root=root, environment={}, stdout=stdout, stderr=io.StringIO(),
                ),
                0,
            )
            self.assertEqual(json.loads(stdout.getvalue())["status"], "prepared")
            self.assertEqual(json.loads(stdout.getvalue())["case_count"], 0)

    def test_execute_recovery_runs_only_the_two_failed_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            parent_plan, parent_root, _proposal = _prepare(root)
            parent_authorization = _write_authorization(root, parent_plan)
            main(
                ["pathlight", "experiment", "execute", "--plan-file", str(parent_plan), "--authorization-file", str(parent_authorization), "--output-root", str(parent_root)],
                repo_root=root, environment=_execution_environment(root),
                experiment_host_factory=_host_factory([], {"bright.economics": ["failed"], "beir.scifact": ["failed"]}),
                stdout=io.StringIO(), stderr=io.StringIO(),
            )
            recovery_root = root / "recovery"
            recovery_root.mkdir(mode=0o700)
            self.assertEqual(main(
                ["pathlight", "experiment", "prepare-recovery", "--parent-plan-file", str(parent_plan), "--parent-authorization-file", str(parent_authorization), "--parent-output-root", str(parent_root), "--output-root", str(recovery_root)],
                repo_root=root, environment={}, stdout=io.StringIO(), stderr=io.StringIO(),
            ), 0)
            authorization = _write_recovery_authorization(
                root, recovery_root / "pathlight-coverage-recovery.json"
            )
            events: list[str] = []
            stdout = io.StringIO()
            stderr = io.StringIO()
            self.assertEqual(main(
                ["pathlight", "experiment", "execute-recovery", "--plan-file", str(recovery_root / "pathlight-coverage-recovery.json"), "--authorization-file", str(authorization), "--output-root", str(recovery_root), "--parent-plan-file", str(parent_plan), "--parent-output-root", str(parent_root)],
                repo_root=root, environment=_execution_environment(root),
                experiment_host_factory=_host_factory(
                    events, {}, expected_coverage_tasks={"bright.economics", "beir.scifact"}
                ), stdout=stdout, stderr=stderr,
            ), 0, stderr.getvalue())
            self.assertEqual(
                [event.removeprefix("run:") for event in events if event.startswith("run:")],
                ["bright.economics", "beir.scifact"],
            )
            self.assertEqual(json.loads(stdout.getvalue())["status"], "completed")
            status_stdout = io.StringIO()
            self.assertEqual(main(
                ["pathlight", "experiment", "status-recovery", "--plan-file", str(recovery_root / "pathlight-coverage-recovery.json"), "--authorization-file", str(authorization), "--output-root", str(recovery_root)],
                repo_root=root, environment={}, stdout=status_stdout, stderr=io.StringIO(),
            ), 0)
            self.assertEqual(json.loads(status_stdout.getvalue())["status"], "completed")

    def test_execute_does_not_publish_completed_receipt_without_native_seal(self) -> None:
        self._native_seal_patch.stop()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)

            code = main(
                [
                    "pathlight", "experiment", "execute",
                    "--plan-file", str(plan),
                    "--authorization-file", str(authorization),
                    "--output-root", str(output),
                ],
                repo_root=root,
                environment=_execution_environment(root),
                experiment_host_factory=_host_factory([], {}),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

            self.assertEqual(code, 1)
            receipts = tuple(sorted((output / "receipts").glob("receipt-*.json")))
            self.assertEqual(len(receipts), 5)
            self.assertTrue(
                all(
                    json.loads(path.read_bytes())["benchmark_status"] == "completed"
                    for path in receipts
                )
            )
            self.assertTrue(
                all(
                    json.loads(path.read_bytes())["observation_status"] == "invalid"
                    for path in receipts
                )
            )

    def test_observation_invalid_is_terminal_and_preserves_agent_operations(self) -> None:
        self._native_seal_patch.stop()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            events: list[str] = []
            arguments = [
                "pathlight", "experiment", "execute",
                "--plan-file", str(plan),
                "--authorization-file", str(authorization),
                "--output-root", str(output),
            ]
            with patch(
                "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
                "_seal_completed_native_task",
                side_effect=ValueError("observation invalid"),
            ):
                code = main(
                    arguments,
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory(events, {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
            receipts = tuple(sorted((output / "receipts").glob("receipt-*.json")))
            self.assertEqual(code, 1)
            self.assertEqual(len(receipts), 5)
            for path in receipts:
                receipt = json.loads(path.read_bytes())
                self.assertEqual(receipt["benchmark_status"], "completed")
                self.assertEqual(receipt["observation_status"], "invalid")
                self.assertEqual(receipt["case_count"], 10)
            self.assertEqual(len([event for event in events if event.startswith("run:")]), 5)
            self.assertEqual(
                sum(json.loads(path.read_bytes())["case_count"] for path in receipts),
                50,
            )

            before_runs = len(
                [event for event in events if event.startswith("run:")]
            )
            with patch(
                "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
                "_seal_completed_native_task",
                side_effect=AssertionError("must not retry terminal observation"),
            ):
                self.assertEqual(
                    main(
                        arguments,
                        repo_root=root,
                        environment=_execution_environment(root),
                        experiment_host_factory=_host_factory(events, {}),
                        stdout=io.StringIO(),
                        stderr=io.StringIO(),
                    ),
                    1,
                )
            self.assertEqual(
                len([event for event in events if event.startswith("run:")]),
                before_runs,
            )

    def test_reconcile_appends_native_validation_without_rerunning_or_mutating_receipts(
        self,
    ) -> None:
        self._native_seal_patch.stop()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            execute = [
                "pathlight", "experiment", "execute",
                "--plan-file", str(plan),
                "--authorization-file", str(authorization),
                "--output-root", str(output),
            ]
            with patch(
                "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
                "_seal_completed_native_task",
                side_effect=ValueError("old reader rejected native evidence"),
            ):
                self.assertEqual(
                    main(
                        execute,
                        repo_root=root,
                        environment=_execution_environment(root),
                        experiment_host_factory=_host_factory([], {}),
                        stdout=io.StringIO(),
                        stderr=io.StringIO(),
                    ),
                    1,
                )
            original_receipts = {
                path.name: path.read_bytes()
                for path in (output / "receipts").glob("receipt-*.json")
            }
            stdout = io.StringIO()
            with patch(
                "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
                "_read_native_dataset_observation",
                side_effect=lambda *, task, **_kwargs: _exact_observation(
                    str(task["task_id"])
                ),
            ):
                self.assertEqual(
                    main(
                        [
                            "pathlight", "experiment", "reconcile",
                            "--plan-file", str(plan),
                            "--authorization-file", str(authorization),
                            "--output-root", str(output),
                        ],
                        repo_root=root,
                        environment={"PRIVATE_SENTINEL": "must-not-leak"},
                        stdout=stdout,
                        stderr=io.StringIO(),
                    ),
                    0,
                )
            self.assertEqual(json.loads(stdout.getvalue())["status"], "completed")
            self.assertEqual(json.loads(stdout.getvalue())["reconciled_task_count"], 5)
            self.assertEqual(
                {
                    path.name: path.read_bytes()
                    for path in (output / "receipts").glob("receipt-*.json")
                },
                original_receipts,
            )
            reconciliations = tuple(
                sorted((output / "reconciliations").glob("reconciliation-*.json"))
            )
            self.assertEqual(len(reconciliations), 5)
            self.assertTrue(
                all(
                    json.loads(path.read_bytes())["receipt_sha256"]
                    == json.loads(original_receipts[f"receipt-{index}-0000.json"])[
                        "receipt_sha256"
                    ]
                    for index, path in enumerate(reconciliations, start=1)
                )
            )
            first = reconciliations[0]
            tampered = json.loads(first.read_bytes())
            tampered["observation_evidence_sha256"] = "0" * 64
            first.write_bytes(_canonical_bytes(tampered))
            first.chmod(0o600)
            loaded_plan = experiment_cli._read_plan(plan)
            loaded_authorization = experiment_cli._read_authorization(
                authorization, plan=loaded_plan, output_root=output
            )
            first_task = loaded_plan["tasks"][0]
            assert isinstance(first_task, dict)
            first_receipt = experiment_cli._read_receipt_chain(
                output / "receipts",
                plan=loaded_plan,
                task=first_task,
                expected_authorization_sha256=str(
                    loaded_authorization["authorization_sha256"]
                ),
            )[-1]
            with self.assertRaises(ValueError):
                experiment_cli._read_reconciliation(
                    output / "reconciliations",
                    plan=loaded_plan,
                    task=first_task,
                    receipt=first_receipt,
                    authorization=loaded_authorization,
                )

    def test_receipt_reader_requires_exact_authorization_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan_path, output, _proposal = _prepare(root)
            plan = experiment_cli._read_plan(plan_path)
            authorization = _write_authorization(root, plan_path)
            authority = experiment_cli._read_authorization(
                authorization, plan=plan, output_root=output
            )
            tasks = plan["tasks"]
            assert isinstance(tasks, list)
            task = tasks[0]
            assert isinstance(task, dict)
            experiment_cli._publish_receipt(
                output / "receipts",
                plan=plan,
                task=task,
                authorization=authority,
                generation=0,
                run_id="run-exact-authority",
                status="failed",
                case_count=0,
                authorized_cost_microusd=1_000_000,
                consumed_cost_microusd=1_000_000,
                cost_evidence="upper-bound",
            )
            with self.assertRaises(ValueError):
                experiment_cli._read_receipt_chain(
                    output / "receipts",
                    plan=plan,
                    task=task,
                    expected_authorization_sha256="f" * 64,
                )

    def test_authorization_rejects_an_equivalent_plan_in_another_operator_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first_root = root / "first"
            second_root = root / "second"
            first_root.mkdir(mode=0o700)
            second_root.mkdir(mode=0o700)
            first_plan, first_output, _proposal = _prepare(first_root)
            second_plan, second_output, _proposal = _prepare(second_root)
            self.assertEqual(
                json.loads(first_plan.read_bytes())["plan_sha256"],
                json.loads(second_plan.read_bytes())["plan_sha256"],
            )
            authorization = _write_authorization(first_root, first_plan)
            events: list[str] = []

            code = main(
                [
                    "pathlight", "experiment", "execute",
                    "--plan-file", str(second_plan),
                    "--authorization-file", str(authorization),
                    "--output-root", str(second_output),
                ],
                repo_root=second_root,
                environment=_execution_environment(second_root),
                experiment_host_factory=_host_factory(events, {}),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

            self.assertEqual(code, 2)
            self.assertEqual(events, [])

    def test_workflow_case_binding_rejects_cross_run_replay(self) -> None:
        run_id = "native-run-1"
        record = {
            "run_sha256": hashlib.sha256(b"other-native-run").hexdigest(),
            "terminal_status": "completed",
        }
        trajectory = {
            "run": {"run_id": run_id, "attempt": 1},
            "dataset": {"dataset_id": "bright.biology", "query_id": "q-1"},
        }
        with self.assertRaises(ValueError):
            experiment_cli._validate_workflow_case_binding(
                record=record,
                trace={"trace_id": pathlight_trace_id(run_id, attempt=1)},
                trajectory=trajectory,
                expected_dataset_id="bright.biology",
                expected_query_id="q-1",
                expected_generation="native-generation-0001",
                generation_state={"run_id": run_id, "attempts": [{}]},
                workflow_run_id=run_id,
            )
        valid_record = {
            "run_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "terminal_status": "completed",
        }
        for name, query_id, generation in (
            ("query", "q-2", "native-generation-0001"),
            ("generation", "q-1", "native-generation-0002"),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                experiment_cli._validate_workflow_case_binding(
                    record=valid_record,
                    trace={"trace_id": pathlight_trace_id(run_id, attempt=1)},
                    trajectory=trajectory,
                    expected_dataset_id="bright.biology",
                    expected_query_id=query_id,
                    expected_generation=generation,
                    generation_state={"run_id": run_id, "attempts": [{}]},
                    workflow_run_id=run_id,
                )

    def test_workflow_case_binding_rejects_trace_from_another_native_run(self) -> None:
        run_id = "native-run-1"
        record = {
            "run_sha256": hashlib.sha256(run_id.encode()).hexdigest(),
            "terminal_status": "completed",
        }
        trajectory = {
            "run": {"run_id": run_id, "attempt": 1},
            "dataset": {"dataset_id": "bright.biology", "query_id": "q-1"},
        }
        replayed_trace = {
            "trace_id": "00000000-0000-4000-8000-000000000999",
        }
        with self.assertRaises(ValueError):
            experiment_cli._validate_workflow_case_binding(
                record=record,
                trace=replayed_trace,
                trajectory=trajectory,
                expected_dataset_id="bright.biology",
                expected_query_id="q-1",
                expected_generation="native-generation-0001",
                generation_state={"run_id": run_id, "attempts": [{}]},
                workflow_run_id=run_id,
            )

    def test_workflow_case_binding_accepts_distinct_protocol_and_native_ids(self) -> None:
        native_run_id = "query-0"
        protocol_run_id = "query-0-attempt-0001"
        experiment_cli._validate_workflow_case_binding(
            record={
                "run_sha256": hashlib.sha256(protocol_run_id.encode()).hexdigest(),
                "terminal_status": "completed",
            },
            trace={"trace_id": pathlight_trace_id(protocol_run_id, attempt=1)},
            trajectory={
                "run": {"run_id": native_run_id, "attempt": 1},
                "dataset": {"dataset_id": "bright.biology", "query_id": "q-1"},
            },
            expected_dataset_id="bright.biology",
            expected_query_id="q-1",
            expected_generation="native-generation-0001",
            generation_state={"run_id": native_run_id, "attempts": [{}]},
            workflow_run_id=protocol_run_id,
        )
    def test_status_revalidates_completed_native_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            arguments = [
                "pathlight", "experiment", "execute",
                "--plan-file", str(plan),
                "--authorization-file", str(authorization),
                "--output-root", str(output),
            ]
            self.assertEqual(
                main(
                    arguments,
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory([], {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )
            stdout = io.StringIO()
            with patch(
                "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
                "_seal_completed_native_task",
                side_effect=ValueError("tampered native"),
            ):
                self.assertEqual(
                    main(
                        [
                            "pathlight", "experiment", "status",
                            "--plan-file", str(plan),
                            "--authorization-file", str(authorization),
                            "--output-root", str(output),
                        ],
                        stdout=stdout,
                        stderr=io.StringIO(),
                    ),
                    0,
                )
            self.assertEqual(json.loads(stdout.getvalue())["status"], "observation-invalid")

    def test_native_seal_rejects_fixture_dataset_identity_and_accepts_exact_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory).resolve() / "native"
            shutil.copytree(_NATIVE_FIXTURE, fixture)
            fixture.chmod(0o700)
            for path in fixture.iterdir():
                path.chmod(0o600)
            config_path = fixture / "config.json"
            config = json.loads(config_path.read_bytes())
            for name in ("summary.json", "results.jsonl"):
                config["artifact_digests"][name] = hashlib.sha256(
                    (fixture / name).read_bytes()
                ).hexdigest()
            config_path.write_bytes(_canonical_bytes(config))
            config_path.chmod(0o600)
            self.assertEqual(
                read_completed_dci_run(fixture, "bright.biology").dataset_id,
                "bright.biology",
            )
            config["dataset"]["dataset_id"] = "dataset.local"
            config_path.write_bytes(_canonical_bytes(config))
            config_path.chmod(0o600)
            with self.assertRaises(DciRecoveryError):
                read_completed_dci_run(fixture, "bright.biology")

        exact = DciCoverageDatasetObservation(
            dataset_id="bright.biology",
            coverage_available_queries=10,
            coverage_total_queries=10,
            coverage_median_any_microunits=1_000_000,
            coverage_median_mean_microunits=500_000,
            coverage_median_all_microunits=0,
            retained_available_queries=10,
            retained_median_microunits=500_000,
            tool_observation_count=20,
            surfaced_gold_count=10,
            model_call_count=10,
            context_frame_count=10,
            missing_boundary_count=0,
            integrity_failure_count=0,
            evidence_sha256=hashlib.sha256(b"exact-native").hexdigest(),
        )
        with patch(
            "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
            "_read_native_dataset_observation",
            return_value=exact,
        ) as reader:
            sealed = _seal_completed_native_task(
                output_root=Path("/operator/root"),
                plan={"plan_sha256": "0" * 64},
                task={"task_id": "bright.biology"},
                run_id="run-exact-native",
            )
        self.assertEqual(sealed, exact)
        reader.assert_called_once_with(
            output_root=Path("/operator/root"),
            plan={"plan_sha256": "0" * 64},
            task={"task_id": "bright.biology"},
            receipt={"run_id": "run-exact-native", "receipt_sha256": "0" * 64},
        )

    def test_query_generation_reader_accepts_only_native_case_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            query_root = Path(directory).resolve() / "query"
            query_root.mkdir(mode=0o700)
            generation = query_root / "native-generation-0001"
            generation.mkdir(mode=0o700)
            for name in (
                "input_question.txt",
                "item.json",
                "reproduction-evidence.json",
                "result.json",
                "timing.json",
            ):
                path = query_root / name
                path.write_text("safe\n", encoding="utf-8")
                path.chmod(0o600)

            self.assertEqual(
                experiment_cli._query_generation_root(
                    query_root, "native-generation-0001"
                ),
                generation,
            )

            unexpected = query_root / "unexpected.json"
            unexpected.write_text("safe\n", encoding="utf-8")
            unexpected.chmod(0o600)
            with self.assertRaises(ValueError):
                experiment_cli._query_generation_root(
                    query_root, "native-generation-0001"
                )

    def test_native_json_reader_accepts_writer_format_but_rejects_duplicate_keys(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            formatted = root / "formatted.json"
            formatted.write_text('{\n  "value": 1\n}\n', encoding="utf-8")
            formatted.chmod(0o600)
            self.assertEqual(experiment_cli._json_native(formatted), {"value": 1})

            duplicate = root / "duplicate.json"
            duplicate.write_text('{"value": 1, "value": 2}\n', encoding="utf-8")
            duplicate.chmod(0o600)
            with self.assertRaises(ValueError):
                experiment_cli._json_native(duplicate)

    def test_completed_experiment_reader_rebuilds_observation_from_exact_chain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "execute",
                        "--plan-file", str(plan),
                        "--authorization-file", str(authorization),
                        "--output-root", str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory([], {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )

            def observed(
                *, task: Mapping[str, object], **_kwargs: object
            ) -> DciCoverageDatasetObservation:
                return DciCoverageDatasetObservation(
                    dataset_id=str(task["task_id"]),
                    coverage_available_queries=10,
                    coverage_total_queries=10,
                    coverage_median_any_microunits=1_000_000,
                    coverage_median_mean_microunits=500_000,
                    coverage_median_all_microunits=0,
                    retained_available_queries=10,
                    retained_median_microunits=500_000,
                    tool_observation_count=20,
                    surfaced_gold_count=10,
                    model_call_count=10,
                    context_frame_count=10,
                    missing_boundary_count=0,
                    integrity_failure_count=0,
                    evidence_sha256=hashlib.sha256(
                        str(task["task_id"]).encode()
                    ).hexdigest(),
                )

            with patch(
                "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
                "_read_native_dataset_observation",
                side_effect=observed,
            ):
                observation = read_completed_coverage_experiment(
                    plan_file=plan,
                    authorization_file=authorization,
                    output_root=output,
                )

            self.assertTrue(observation.complete)
            self.assertEqual(observation.agent_operation_count, 50)
            self.assertEqual(observation.judge_operation_count, 0)
            self.assertEqual(tuple(item.dataset_id for item in observation.datasets), _TASK_IDS)

    def test_completed_experiment_reader_rejects_incomplete_tampered_or_replaced_chain(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "execute",
                        "--plan-file", str(plan),
                        "--authorization-file", str(authorization),
                        "--output-root", str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory([], {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )

            receipt = output / "receipts" / "receipt-1-0000.json"
            original_receipt = receipt.read_bytes()
            receipt.unlink()
            with self.assertRaisesRegex(ValueError, "coverage experiment evidence is invalid"):
                read_completed_coverage_experiment(
                    plan_file=plan,
                    authorization_file=authorization,
                    output_root=output,
                )
            receipt.write_bytes(original_receipt)
            receipt.chmod(0o600)

            tampered = json.loads(original_receipt)
            tampered["consumed_cost_microusd"] = 1
            receipt.write_bytes(_canonical_bytes(tampered))
            receipt.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "coverage experiment evidence is invalid"):
                read_completed_coverage_experiment(
                    plan_file=plan,
                    authorization_file=authorization,
                    output_root=output,
                )
            receipt.write_bytes(original_receipt)
            receipt.chmod(0o600)

            wrong_authorization = root / "wrong-authorization.json"
            wrong = json.loads(authorization.read_bytes())
            wrong["plan_sha256"] = "0" * 64
            wrong_authorization.write_bytes(_canonical_bytes(wrong))
            wrong_authorization.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "coverage experiment evidence is invalid"):
                read_completed_coverage_experiment(
                    plan_file=plan,
                    authorization_file=wrong_authorization,
                    output_root=output,
                )

            alias = root / "coverage-alias"
            alias.symlink_to(output, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "coverage experiment evidence is invalid"):
                read_completed_coverage_experiment(
                    plan_file=plan,
                    authorization_file=authorization,
                    output_root=alias,
                )

    def test_completed_experiment_reader_rejects_native_tamper_without_leaking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan, output, _proposal = _prepare(root)
            authorization = _write_authorization(root, plan)
            self.assertEqual(
                main(
                    [
                        "pathlight", "experiment", "execute",
                        "--plan-file", str(plan),
                        "--authorization-file", str(authorization),
                        "--output-root", str(output),
                    ],
                    repo_root=root,
                    environment=_execution_environment(root),
                    experiment_host_factory=_host_factory([], {}),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )
            with patch(
                "asterion.applications.dci_agent_lite.pathlight_experiment_cli."
                "_read_native_dataset_observation",
                side_effect=RuntimeError("SENTINEL_PRIVATE_NATIVE_PATH"),
            ):
                with self.assertRaisesRegex(
                    ValueError, "^coverage experiment evidence is invalid$"
                ) as raised:
                    read_completed_coverage_experiment(
                        plan_file=plan,
                        authorization_file=authorization,
                        output_root=output,
                    )
            self.assertNotIn(str(root), str(raised.exception))
            self.assertNotIn("SENTINEL", str(raised.exception))

    def test_prepare_binds_only_effective_execution_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            baseline = {
                "DCI_RPC_TIMEOUT_SECONDS": "120",
                "DCI_PI_THINKING_LEVEL": "high",
                "DCI_NODE_MAX_OLD_SPACE_SIZE_MB": "4096",
                "OPENAI_API_KEY": "SENTINEL_CREDENTIAL_A",
                "DCI_PROVIDER": "ignored-provider-a",
                "DCI_MODEL": "ignored-model-a",
                "DCI_RUNTIME": "ignored-runtime-a",
                "DCI_TOOLS": "ignored-tools-a",
                "DCI_MAX_TURNS": "7",
                "DCI_RUNTIME_CONTEXT_LEVEL": "level1",
            }
            rotated = {
                **baseline,
                "OPENAI_API_KEY": "SENTINEL_CREDENTIAL_B",
                "DCI_PROVIDER": "ignored-provider-b",
                "DCI_MODEL": "ignored-model-b",
                "DCI_RUNTIME": "ignored-runtime-b",
                "DCI_TOOLS": "ignored-tools-b",
                "DCI_MAX_TURNS": "9",
                "DCI_RUNTIME_CONTEXT_LEVEL": "level2",
            }

            plans: dict[str, dict[str, object]] = {}
            environments = {
                "baseline": baseline,
                "rotated": rotated,
                "timeout": {**baseline, "DCI_RPC_TIMEOUT_SECONDS": "121"},
                "thinking": {**baseline, "DCI_PI_THINKING_LEVEL": "low"},
                "node-memory": {
                    **baseline,
                    "DCI_NODE_MAX_OLD_SPACE_SIZE_MB": "8192",
                },
            }
            for name, environment in environments.items():
                root = parent / name
                root.mkdir(mode=0o700)
                env_file = root / ".env"
                env_file.write_text(
                    "PRIVATE_SENTINEL=SENTINEL_DOTENV_PRIVATE\n",
                    encoding="utf-8",
                )
                env_file.chmod(0o600)
                plan_path, _output, _proposal = _prepare(
                    root,
                    environment_overrides=environment,
                )
                encoded = plan_path.read_text(encoding="utf-8")
                self.assertNotIn("SENTINEL_", encoded)
                self.assertNotIn(str(root), encoded)
                plans[name] = json.loads(encoded)

            for plan in plans.values():
                self.assertIn("execution_config_sha256", plan)
            baseline_digest = plans["baseline"]["execution_config_sha256"]
            self.assertRegex(str(baseline_digest), r"^[0-9a-f]{64}$")
            self.assertEqual(
                plans["rotated"]["execution_config_sha256"],
                baseline_digest,
            )
            for name in ("timeout", "thinking", "node-memory"):
                with self.subTest(name=name):
                    self.assertNotEqual(
                        plans[name]["execution_config_sha256"],
                        baseline_digest,
                    )

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

    def test_execute_rejects_effective_config_drift_before_host_construction(
        self,
    ) -> None:
        changes = {
            "timeout": {"DCI_RPC_TIMEOUT_SECONDS": "121"},
            "thinking": {"DCI_PI_THINKING_LEVEL": "low"},
            "node-memory": {"DCI_NODE_MAX_OLD_SPACE_SIZE_MB": "8192"},
        }
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            for name, change in changes.items():
                with self.subTest(name=name):
                    root = parent / name
                    root.mkdir(mode=0o700)
                    prepared_environment = {
                        "DCI_RPC_TIMEOUT_SECONDS": "120",
                        "DCI_PI_THINKING_LEVEL": "high",
                        "DCI_NODE_MAX_OLD_SPACE_SIZE_MB": "4096",
                    }
                    plan, output, _proposal = _prepare(
                        root,
                        environment_overrides=prepared_environment,
                    )
                    authorization = _write_authorization(root, plan)
                    events: list[str] = []
                    execution_environment = {
                        **_execution_environment(root),
                        **prepared_environment,
                        **change,
                    }

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
                        environment=execution_environment,
                        experiment_host_factory=_host_factory(events, {}),
                        stdout=io.StringIO(),
                        stderr=io.StringIO(),
                    )

                    self.assertEqual(code, 2)
                    self.assertEqual(events, [])

    def test_execute_rejects_code_defined_config_drift_before_host_construction(
        self,
    ) -> None:
        fixed_overrides = {
            "runtime": "pi",
            "provider": "openai-codex",
            "model": "gpt-5.6-luna",
            "tools": "read,bash",
            "runtime_context_level": "level2",
        }
        config_patches = (
            (
                "executor-profile",
                lambda: patch(
                    "asterion.applications.dci_agent_lite.benchmark_host."
                    "_REAL_AGENT_EXECUTOR_PROFILE",
                    "changed-real-profile",
                    create=True,
                ),
            ),
            (
                "runtime-context",
                lambda: patch(
                    "asterion.applications.dci_agent_lite.benchmark_host."
                    "_REAL_AGENT_RUNTIME_OVERRIDES",
                    fixed_overrides,
                ),
            ),
            (
                "native-attempts",
                lambda: patch.dict(
                    "asterion.applications.dci_agent_lite.benchmark_executor."
                    "_REAL_TASK_NATIVE_ATTEMPTS",
                    {"bright.biology": 4},
                ),
            ),
            (
                "effective-tools",
                lambda: patch(
                    "asterion.applications.dci_agent_lite.benchmark_executor."
                    "_COVERAGE_EFFECTIVE_TOOLS",
                    "read",
                    create=True,
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory).resolve()
            for name, config_patch in config_patches:
                with self.subTest(name=name):
                    root = parent / name
                    root.mkdir(mode=0o700)
                    plan, output, _proposal = _prepare(root)
                    authorization = _write_authorization(root, plan)
                    events: list[str] = []

                    with config_patch():
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
                            experiment_host_factory=_host_factory(events, {}),
                            stdout=io.StringIO(),
                            stderr=io.StringIO(),
                        )

                    self.assertEqual(code, 2)
                    self.assertEqual(events, [])

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
            plan_value = json.loads(plan.read_bytes())
            receipts = sorted((output / "receipts").glob("receipt-*.json"))
            self.assertEqual(len(receipts), 5)
            for receipt_path in receipts:
                receipt = json.loads(receipt_path.read_bytes())
                self.assertIn("execution_config_sha256", receipt)
                self.assertEqual(
                    receipt["execution_config_sha256"],
                    plan_value["execution_config_sha256"],
                )

            status_stdout = io.StringIO()
            self.assertEqual(
                main(
                    [
                        "pathlight",
                        "experiment",
                        "status",
                        "--plan-file",
                        str(plan),
                        "--authorization-file",
                        str(authorization),
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
                        "--authorization-file",
                        str(_write_authorization(root, output / "pathlight-coverage-experiment.json")),
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
