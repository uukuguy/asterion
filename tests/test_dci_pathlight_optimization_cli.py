"""Provider-free preparation and authorization tests for Bright optimization."""

from __future__ import annotations

import hashlib
import fcntl
import io
import json
import os
import stat
import shutil
import tempfile
from dataclasses import replace
import unittest
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from asterion.benchmarks import BenchmarkTaskExecutor
from asterion.benchmarks.evidence import BenchmarkRunResult, BenchmarkTaskResult
from asterion.applications.dci_agent_lite.benchmark_host import DciBenchmarkHost
from asterion.applications.dci_agent_lite.benchmark_instances import DciBenchmarkInstance
from asterion.capability_packages.sources.base import CapabilityPackageSource
from asterion.applications.dci_agent_lite.operator_config import DciOperatorConfig
from asterion.capabilities.dci.implementation.operator_inputs import DciBenchmarkOperatorInputs
from asterion.capabilities.dci.implementation.pathlight.recovery import (
    read_completed_dci_run,
)
from asterion.capabilities.dci.implementation.pathlight.conversion import (
    recovered_run_to_evaluation_bundle,
    recovered_run_to_experiment,
)
from asterion.workflow_evidence import read_workflow_observation_bundle, write_workflow_observation_bundle
from asterion.pathlight.protocol import TraceEvent, TraceGraph
from asterion.capabilities.dci.implementation.research.query_planning import QueryPlanningContract

from asterion.applications.dci_agent_lite.pathlight_optimization_cli import (
    PLAN_FILENAME,
    _AUTHORIZATION_SCHEMA,
    _canonical_bytes,
    _diagnosis_digest,
    _digest,
    _native_receipt_projection,
    _result_cost,
    main,
    read_optimization_authorization,
    read_optimization_plan,
)
from asterion.pathlight._private_file import write_private_file
from asterion.pathlight.diagnosis import DIAGNOSIS_BUNDLE_FILENAME, write_diagnosis_bundle
from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    AUTHORIZATION_GATE_REPORT_FILENAME,
    DCI_DIAGNOSIS_REPORT_FILENAME,
    diagnose_recommended_pack,
    write_authorization_gate_report,
    write_dci_diagnosis_report,
)
from tests.test_dci_pathlight_diagnosis import _DATASETS, _coverage_pack, _run


_GATE_FILENAME = AUTHORIZATION_GATE_REPORT_FILENAME
_NATIVE_FIXTURE = Path(__file__).parent / "fixtures" / "dci" / "pathlight-recovery"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bright_rows() -> bytes:
    rows = []
    for index in range(10):
        rows.append(
            {
                "answer": "private answer",
                "excluded_ids": ["excluded"],
                "gold_ids": ["gold"],
                "gold_ids_long": ["gold"],
                "id": f"q-{index:03d}",
                "query": "SENTINEL_PRIVATE_QUERY",
                "query_id": f"q-{index:03d}",
                "reasoning": "private reasoning",
            }
        )
    return ("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n").encode()


def _proposal(scope: str) -> tuple[SimpleNamespace, SimpleNamespace]:
    coverage_finding = _sha("coverage finding")
    query_finding = _sha("query finding")
    coverage_sole = _diagnosis_digest(
        "proposal-sole-variable", "trajectory-coverage-instrumentation-only"
    )
    coverage = SimpleNamespace(
        finding_sha256=coverage_finding,
        proposal_sha256=_sha("coverage proposal"),
        change_sha256=_diagnosis_digest(
            "proposal-change",
            {
                "change": "coverage-instrumentation",
                "sole_variable_sha256": coverage_sole,
            },
        ),
        success_criteria_sha256=_diagnosis_digest(
            "proposal-success", {"trajectory_coverage_recorded": True}
        ),
        stop_criteria_sha256=_diagnosis_digest(
            "proposal-stop", {"infrastructure_failures": 2}
        ),
        budget_sha256=_diagnosis_digest(
            "proposal-budget", {"agent_operations": 50, "max_cost_microusd": 5_000_000}
        ),
    )
    query_sole = _diagnosis_digest("proposal-sole-variable", "retrieval-query-planning")
    query = SimpleNamespace(
        finding_sha256=query_finding,
        proposal_sha256=_sha("query proposal"),
        change_sha256=_diagnosis_digest(
            "proposal-change",
            {
                "change": "retrieval-query-decomposition",
                "sole_variable_sha256": query_sole,
            },
        ),
        scope_sha256=scope,
        success_criteria_sha256=_diagnosis_digest(
            "proposal-success",
            {
                "mean_ndcg_gain_microunits": 50_000,
                "maximum_cost_or_time_increase_microunits": 250_000,
            },
        ),
        stop_criteria_sha256=_diagnosis_digest(
            "proposal-stop", {"prerequisite_proposal_sha256": coverage.proposal_sha256}
        ),
        budget_sha256=_diagnosis_digest(
            "proposal-budget", {"agent_operations": 80, "max_cost_microusd": 16_000_000}
        ),
    )
    return coverage, query


def _write_lock(_lock: object, target: Path) -> None:
    write_private_file(target, b'{"protocol":"test"}\n')


class _OptimizationFixture:
    def __init__(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.output = self.root / "output"
        self.output.mkdir(mode=0o700)
        self.datasets: dict[str, Path] = {}
        for dataset in (
            "bright.biology",
            "bright.earth-science",
            "bright.economics",
            "bright.robotics",
        ):
            path = self.root / f"{dataset}.jsonl"
            path.write_bytes(_bright_rows())
            self.datasets[dataset] = path
        self.report = diagnose_recommended_pack(
            tuple(_run(*dataset) for dataset in _DATASETS),
            coverage_experiment=_coverage_pack(),
        )
        self.diagnosis = self.report.diagnosis_bundle
        self.query = next(
            proposal
            for proposal in self.diagnosis.proposals
            if proposal.proposal_sha256
            == next(item for item in self.report.proposals if item.code == "retrieval-query-decomposition").proposal_sha256
        )
        self.query_scope = self.query.scope_sha256
        self.config = DciOperatorConfig(
            repo_root=self.root,
            benchmark_inputs=DciBenchmarkOperatorInputs(
                dataset_roots=self.datasets,
                corpus_roots={dataset: self.root for dataset in self.datasets},
                private_environment={},
                amount=None,
            ),
            host_service_options={},
            max_native_attempts=1,
        )
        self.diagnosis_file = self.root / DIAGNOSIS_BUNDLE_FILENAME
        self.report_file = self.root / DCI_DIAGNOSIS_REPORT_FILENAME
        self.gate = self.root / _GATE_FILENAME
        write_diagnosis_bundle(self.diagnosis, self.diagnosis_file)
        write_dci_diagnosis_report(self.report, self.report_file)
        write_authorization_gate_report(self.report, self.gate)

    def close(self) -> None:
        self.temp.cleanup()

    def prepare(self, *, real_source_lock: bool = False) -> tuple[int, dict[str, object], Mock]:
        stdout, stderr = io.StringIO(), io.StringIO()
        provider = Mock()
        with (
            patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli._proposal_scope", return_value=self.query_scope),
            patch(
                "asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config",
                return_value=self.config,
            ),
            (nullcontext() if real_source_lock else patch(
                "asterion.applications.dci_agent_lite.pathlight_optimization_cli.resolve_benchmark_source_lock",
                return_value=object(),
            )),
            (nullcontext() if real_source_lock else patch(
                "asterion.applications.dci_agent_lite.pathlight_optimization_cli.write_benchmark_source_lock",
                side_effect=_write_lock,
            )),
            patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.DciBenchmarkHost", provider, create=True),
        ):
            code = main(
                (
                    "prepare",
                    "--diagnosis-file", str(self.diagnosis_file),
                    "--diagnosis-report-file", str(self.report_file),
                    "--gate-report-file", str(self.gate),
                    "--proposal-sha256", self.query.proposal_sha256,
                    "--output-root", str(self.output),
                ),
                stdout=stdout,
                stderr=stderr,
                repo_root=self.root,
                env_file=self.root / ".env",
                environment={},
            )
        if code != 0:
            raise AssertionError(stderr.getvalue())
        return code, json.loads(stdout.getvalue()), provider


def _authorization(plan: dict[str, object]) -> dict[str, object]:
    value = {
        "schema": _AUTHORIZATION_SCHEMA,
        "plan_sha256": plan["plan_sha256"],
        "diagnosis_bundle_sha256": plan["diagnosis_bundle_sha256"],
        "authorization_gate_report_sha256": plan["authorization_gate_report_sha256"],
        "proposal_sha256": plan["proposal_sha256"],
        "finding_sha256": plan["finding_sha256"],
        "scope_sha256": plan["scope_sha256"],
        "source_lock_sha256": plan["source_lock_sha256"],
        "selected_case_scope_sha256": plan["selected_case_scope_sha256"],
        "baseline_query_plan_sha256": plan["baseline_query_plan_sha256"],
        "candidate_query_plan_sha256": plan["candidate_query_plan_sha256"],
        "baseline_variant_sha256": plan["baseline_variant_sha256"],
        "candidate_variant_sha256": plan["candidate_variant_sha256"],
        "baseline_execution_config_sha256": plan["baseline_execution_config_sha256"],
        "candidate_execution_config_sha256": plan["candidate_execution_config_sha256"],
        "output_root_device": plan["output_root_device"],
        "output_root_inode": plan["output_root_inode"],
        "max_agent_operations": 80,
        "max_judge_operations": 0,
        "max_cost_microusd": 16_000_000,
        "max_infrastructure_failures": 2,
        "max_native_attempts": 1,
        "execution_authorized": True,
        "operator_approval_sha256": _sha("approval"),
    }
    value["authorization_sha256"] = _digest(value)
    return value


class TestPrepare(unittest.TestCase):
    def test_prepare_coordinator_has_a_closed_public_surface(self) -> None:
        from asterion.applications.dci_agent_lite.pathlight_optimization_cli import (
            PLAN_FILENAME,
            read_optimization_authorization,
        )

        self.assertEqual(PLAN_FILENAME, "pathlight-bright-optimization.json")
        self.assertTrue(callable(read_optimization_authorization))

    def test_prepare_builds_exact_4x10_unexecuted_plan(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        code, output, provider = fixture.prepare()
        self.assertEqual(code, 0)
        self.assertEqual(output["dataset_count"], 4)
        self.assertEqual(output["case_count"], 40)
        self.assertEqual(output["max_agent_operations"], 80)
        self.assertEqual(output["max_judge_operations"], 0)
        # A ten-case Bright task may contain a single response just above the
        # old $0.10 parallel reservation slice despite remaining below the
        # task's aggregate envelope.  The development optimization plan gives
        # each paired task a $2 envelope, so real bounded execution is not
        # rejected by that artificial slice.
        self.assertEqual(output["max_cost_microusd"], 16_000_000)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        self.assertFalse(plan["execution_authorized"])
        tasks = plan["tasks"]
        self.assertIsInstance(tasks, list)
        assert isinstance(tasks, list)
        self.assertEqual(len(tasks), 8)
        self.assertNotEqual(
            plan["baseline_variant_sha256"], plan["candidate_variant_sha256"]
        )
        self.assertNotEqual(
            plan["baseline_execution_config_sha256"],
            plan["candidate_execution_config_sha256"],
        )
        for task in tasks:
            self.assertEqual(
                task["variant_sha256"],
                plan[f"{task['variant_role']}_variant_sha256"],
            )
            self.assertEqual(
                task["execution_config_sha256"],
                plan[f"{task['variant_role']}_execution_config_sha256"],
            )
        self.assertNotIn("SENTINEL_PRIVATE_QUERY", json.dumps(output))
        provider.assert_not_called()

    def test_prepare_rejects_missing_incomplete_tampered_or_unsafe_gate_report(self) -> None:
        for mutation in (
            "missing",
            "incomplete",
            "tampered",
            "mode",
            "symlink",
            "fifo",
            "oversized",
            "report-tampered",
            "gate-recomputed",
        ):
            with self.subTest(mutation=mutation):
                fixture = _OptimizationFixture()
                self.addCleanup(fixture.close)
                if mutation == "missing":
                    fixture.gate.unlink()
                elif mutation == "incomplete":
                    blocked = diagnose_recommended_pack(
                        tuple(_run(*dataset) for dataset in _DATASETS),
                        coverage_experiment=_coverage_pack(available_queries=9),
                    )
                    fixture.report_file.unlink()
                    write_dci_diagnosis_report(blocked, fixture.report_file)
                elif mutation == "tampered":
                    value = json.loads(fixture.gate.read_text(encoding="utf-8"))
                    value["query_scope_sha256"] = "0" * 64
                    fixture.gate.unlink()
                    write_private_file(
                        fixture.gate,
                        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
                    )
                elif mutation == "report-tampered":
                    fixture.report_file.unlink()
                    write_private_file(fixture.report_file, b"{}\n")
                elif mutation == "gate-recomputed":
                    value = json.loads(fixture.gate.read_text(encoding="utf-8"))
                    value["query_scope_sha256"] = "0" * 64
                    value["gate_report_sha256"] = _digest(
                        {
                            key: item
                            for key, item in value.items()
                            if key != "gate_report_sha256"
                        }
                    )
                    fixture.gate.unlink()
                    write_private_file(
                        fixture.gate,
                        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
                    )
                elif mutation == "mode":
                    fixture.gate.chmod(0o644)
                else:
                    if mutation == "symlink":
                        target = fixture.root / "gate-target.json"
                        fixture.gate.rename(target)
                        fixture.gate.symlink_to(target)
                    elif mutation == "fifo":
                        fixture.gate.unlink()
                        os.mkfifo(fixture.gate, 0o600)
                    else:
                        fixture.gate.write_bytes(b"x" * ((1 << 16) + 1))
                        fixture.gate.chmod(0o600)
                stdout, stderr = io.StringIO(), io.StringIO()
                code = main(
                    (
                        "prepare",
                        "--diagnosis-file", str(fixture.diagnosis_file),
                        "--diagnosis-report-file", str(fixture.report_file),
                        "--gate-report-file", str(fixture.gate),
                        "--proposal-sha256", fixture.query.proposal_sha256,
                        "--output-root", str(fixture.output),
                    ),
                    stdout=stdout,
                    stderr=stderr,
                    repo_root=fixture.root,
                    env_file=None,
                    environment={},
                )
                self.assertEqual(code, 2)
                self.assertEqual(stdout.getvalue(), "")

    def test_plan_reader_rejects_recomputed_variant_or_config_tampering(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare(real_source_lock=True)[0], 0)
        path = fixture.output / PLAN_FILENAME
        original = json.loads(path.read_text(encoding="utf-8"))
        for field, source in (
            ("candidate_variant_sha256", "baseline_variant_sha256"),
            ("candidate_execution_config_sha256", "baseline_execution_config_sha256"),
        ):
            with self.subTest(field=field):
                value = dict(original)
                value[field] = value[source]
                value["plan_sha256"] = _digest(
                    {key: item for key, item in value.items() if key != "plan_sha256"}
                )
                path.unlink()
                write_private_file(
                    path,
                    (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
                )
                with self.assertRaises(ValueError):
                    read_optimization_plan(path)
                path.unlink()
                write_private_file(
                    path,
                    (json.dumps(original, sort_keys=True, separators=(",", ":")) + "\n").encode(),
                )


class TestAuthorization(unittest.TestCase):
    def test_authorization_binds_every_execution_boundary(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        code, _output, _provider = fixture.prepare()
        self.assertEqual(code, 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, (json.dumps(_authorization(plan), sort_keys=True, separators=(",", ":")) + "\n").encode())
        value = read_optimization_authorization(authorization, plan=plan)
        self.assertTrue(value["execution_authorized"])
        self.assertEqual(value["max_agent_operations"], 80)
        self.assertEqual(value["max_judge_operations"], 0)

    def test_authorization_rejects_variant_or_execution_config_drift(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare(real_source_lock=True)[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        for field in (
            "baseline_variant_sha256",
            "candidate_variant_sha256",
            "baseline_execution_config_sha256",
            "candidate_execution_config_sha256",
        ):
            with self.subTest(field=field):
                value = _authorization(plan)
                value[field] = "0" * 64
                value["authorization_sha256"] = _digest(
                    {key: item for key, item in value.items() if key != "authorization_sha256"}
                )
                write_private_file(
                    authorization,
                    (
                        json.dumps(value, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    ).encode(),
                )
                with self.assertRaises(ValueError):
                    read_optimization_authorization(authorization, plan=plan)
                authorization.unlink()

    def test_authorization_rejects_mutated_boundaries_and_unsafe_file_modes(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        path = fixture.root / "authorization.json"
        original = _authorization(plan)
        for field in (
            "plan_sha256",
            "diagnosis_bundle_sha256",
            "authorization_gate_report_sha256",
            "proposal_sha256",
            "finding_sha256",
            "scope_sha256",
            "source_lock_sha256",
            "selected_case_scope_sha256",
            "baseline_query_plan_sha256",
            "candidate_query_plan_sha256",
            "baseline_variant_sha256",
            "candidate_variant_sha256",
            "baseline_execution_config_sha256",
            "candidate_execution_config_sha256",
            "output_root_device",
            "output_root_inode",
            "max_agent_operations",
            "max_judge_operations",
            "max_cost_microusd",
            "max_infrastructure_failures",
            "max_native_attempts",
            "execution_authorized",
            "operator_approval_sha256",
        ):
            with self.subTest(field=field):
                value = dict(original)
                value[field] = False if field == "execution_authorized" else "0" * 64
                write_private_file(
                    path,
                    (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
                )
                with self.assertRaises(ValueError):
                    read_optimization_authorization(path, plan=plan)
                path.unlink()
        write_private_file(
            path,
            (json.dumps(original, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            read_optimization_authorization(path, plan=plan)


class TestStatus(unittest.TestCase):
    def test_status_is_provider_free_and_reports_zero_before_execution(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        code, _output, _provider = fixture.prepare()
        self.assertEqual(code, 0)
        stdout, stderr = io.StringIO(), io.StringIO()
        provider = Mock()
        with patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.DciBenchmarkHost", provider, create=True):
            code = main(
                ("status", "--plan-file", str(fixture.output / PLAN_FILENAME), "--output-root", str(fixture.output)),
                stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None, environment={},
            )
        output = json.loads(stdout.getvalue())
        self.assertEqual((code, output["completed_agent_operations"]), (0, 0))
        provider.assert_not_called()

    def test_status_rejects_every_receipt_before_task_six_exists(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        receipt = fixture.output / "receipts" / "receipt-1-0000.json"
        write_private_file(receipt, b"{}\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        self.assertEqual(
            main(
                ("status", "--plan-file", str(fixture.output / PLAN_FILENAME), "--output-root", str(fixture.output)),
                stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None, environment={},
            ),
            2,
        )


class _RecordingOptimizationHost:
    """A real-host-shaped fake: it records every required host lifecycle phase."""

    def __init__(
        self, task_id: str, events: list[str], outcomes: dict[str, list[str]] | None = None
    ) -> None:
        self.task_id = task_id
        self.events = events
        self.outcomes = {} if outcomes is None else outcomes

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

    def create_plan(self, _resolved: object, *, execute: bool, **_kwargs: object) -> object:
        if not execute:
            self.events.append(f"preflight:{self.task_id}:plan")
        return SimpleNamespace(case_limit=10, run_id=f"run-{self.task_id}")

    def authorize_execution(self, **_kwargs: object) -> object:
        self.events.append(f"authorize:{self.task_id}")
        return object()

    def load_selected_providers(self, _payloads: object, _authorization: object) -> object:
        self.events.append(f"provider:{self.task_id}")
        return object()

    def run(self, _plan: object, _providers: object, **_kwargs: object) -> BenchmarkRunResult:
        self.events.append(f"run:{self.task_id}")
        outcome = self.outcomes.get(self.task_id, ["completed"])
        status = outcome.pop(0) if outcome else "completed"
        if status == "network":
            raise NetworkFailure()
        if status == "cancelled":
            return BenchmarkRunResult(
                "cancelled",
                (BenchmarkTaskResult(self.task_id.rsplit(".", 1)[0], "cancelled", 0),),
            )
        artifact_ids: tuple[str, ...] = (
            "coverage-authorized-microusd.2000000", "coverage-upper-microusd.2000000"
        )
        if status == "observation-invalid":
            status = "completed"
            artifact_ids = (
                "coverage-authorized-microusd.2000000", "coverage-upper-microusd.2000000",
                "pathlight-observation-invalid",
            )
        elif status.startswith("actual:"):
            _prefix, amount = status.split(":", 1)
            status = "completed"
            artifact_ids = (
                f"coverage-actual-microusd.{amount}", "coverage-authorized-microusd.2000000",
            )
        return BenchmarkRunResult(
            status,
            (BenchmarkTaskResult(self.task_id.rsplit(".", 1)[0], status, 10 if status == "completed" else 0, artifact_ids),),
        )


class NetworkFailure(Exception):
    pass


class _NativeEvidenceExecutor(BenchmarkTaskExecutor):
    """Controlled executor fixture which emits the native DCI closure."""

    def __init__(self, calls: list[tuple[str, Decimal | None]], *, fail_first: bool = False, candidate_score: float = 0.75, actual_cost: int | None = None, candidate_cost: int | None = None, regression_dataset: int | None = None) -> None:
        self.calls = calls
        self.fail_first = fail_first
        self.candidate_score = candidate_score
        self.actual_cost = actual_cost
        self.candidate_cost = candidate_cost
        self.regression_dataset = regression_dataset

    def execute(self, invocation: object, **_kwargs: object) -> BenchmarkTaskResult:
        payload = getattr(invocation, "private_payload")
        task_id = getattr(invocation, "task_id")
        output = getattr(payload, "output_directory")
        self.calls.append((task_id, getattr(payload, "amount")))
        is_candidate = len(self.calls) % 2 == 0
        candidate_value = 0.5 if is_candidate and self.regression_dataset == (len(self.calls) // 2 - 1) else self.candidate_score
        assert isinstance(output, Path)
        output.mkdir(parents=True)
        for source in _NATIVE_FIXTURE.iterdir():
            shutil.copy2(source, output / source.name)
        analysis_path = output / "analysis.json"
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        rows = []
        for index in range(10):
            row = dict(analysis["per_query_metrics"][index % 2])
            row["query_id"] = f"q-{index:03d}"
            row["ndcg_at_10"] = candidate_value if is_candidate else (0.5 if index < 5 else 1.0)
            rows.append(row)
        analysis["per_query_metrics"] = rows
        analysis_path.write_text(json.dumps(analysis, sort_keys=True), encoding="utf-8")
        (output / "batch-state.json").write_text(
            json.dumps({"schema": "asterion.dci.batch-state/v1", "status": "completed", "counts": {"total": 10, "failed": 0}}),
            encoding="utf-8",
        )
        summary = output / "summary.json"
        summary.write_text(
            json.dumps({"schema": "asterion.dci.batch-summary/v1", "counts": {"total": 10, "failed_runs": 0}, "ndcg_at_10": candidate_value if is_candidate else 0.75}),
            encoding="utf-8",
        )
        results = output / "results.jsonl"
        results.write_text("".join(json.dumps({"schema": "asterion.dci.batch-result/v1", "query_id": f"q-{index:03d}", "status": "completed", "mode": "ir", "native_generation": "native-generation-0001"}) + "\n" for index in range(10)), encoding="utf-8")
        config_path = output / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["dataset"]["dataset_id"] = task_id
        config["selection"]["selected_rows"] = 10
        summary = output / "summary.json"
        results = output / "results.jsonl"
        config["artifact_digests"]["summary.json"] = hashlib.sha256(summary.read_bytes()).hexdigest()
        config["artifact_digests"]["results.jsonl"] = hashlib.sha256(results.read_bytes()).hexdigest()
        config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
        config_path.chmod(0o600)
        for index in range(10):
            workflow_root = output / f"q-{index:03d}" / "native-generation-0001"
            workflow_root.mkdir(parents=True, mode=0o700)
            record = {
                "schema": "asterion.workflow-evidence/v1", "run_id": f"native-run-{index}",
                "input_digest": f"{index:064x}", "terminal_status": "completed", "tools": [],
                "usage": {"input_tokens": 100, "output_tokens": 50}, "artifacts": [],
            }
            record["graph_sha256"] = hashlib.sha256(
                json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            trace_id = f"00000000-0000-4000-8000-{len(self.calls) * 100 + index + 1:012d}"
            trace = TraceGraph.build(
                trace_id,
                (TraceEvent.start(trace_id, trace_id, None, 1, "task"), TraceEvent.complete(trace_id, trace_id, 2)),
            ).to_mapping()
            write_workflow_observation_bundle(
                workflow_root / "workflow-evidence.json", (record,), pathlight_traces=(trace,)
            )
        for path in output.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        output.chmod(0o700)
        output.parent.chmod(0o700)
        output.parent.parent.chmod(0o700)
        if self.fail_first and len(self.calls) == 1:
            return BenchmarkTaskResult(task_id, "failed", 0)
        artifacts = (
            (f"coverage-actual-microusd.{self.candidate_cost if is_candidate and self.candidate_cost is not None else self.actual_cost}", "coverage-authorized-microusd.2000000")
            if self.actual_cost is not None
            else
            ("coverage-actual-microusd.17", "coverage-authorized-microusd.2000000")
            if len(self.calls) == 1
            else ("coverage-authorized-microusd.2000000", "coverage-upper-microusd.2000000")
        )
        return BenchmarkTaskResult(task_id, "completed", 10, artifacts)


def _execute_optimization(
    fixture: _OptimizationFixture,
    *,
    command: str = "execute",
    outcomes: dict[str, list[str]] | None = None,
    events: list[str] | None = None,
) -> tuple[int, dict[str, object], list[str]]:
    authorization = fixture.root / "authorization.json"
    if not authorization.exists():
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))
    recorded = [] if events is None else events
    values = {} if outcomes is None else outcomes

    def host_factory(*, task: object, operator_config: object, **_kwargs: object) -> object:
        amount = getattr(getattr(operator_config, "benchmark_inputs"), "amount")
        if amount is None or not 0 < amount <= 2:
            raise AssertionError("real task host did not receive its bounded amount")
        recorded.append(f"budget:{getattr(task, 'get')('task_id')}:{amount}")
        return _RecordingOptimizationHost(getattr(task, "get")("task_id"), recorded, values)

    stdout, stderr = io.StringIO(), io.StringIO()
    with patch(
        "asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config",
        return_value=fixture.config,
    ):
        code = main(
            (command, "--plan-file", str(fixture.output / PLAN_FILENAME), "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
            stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None,
            environment={}, host_factory=host_factory,
        )
    return code, json.loads(stdout.getvalue()) if stdout.getvalue() else {}, recorded


def _finalize_real_native(
    fixture: _OptimizationFixture, *, candidate_score: float, actual_cost: int = 100,
    candidate_cost: int | None = None, elapsed_ns: tuple[int, int] = (1_000, 1_000), regression_dataset: int | None = None,
) -> dict[str, object]:
    """Run the whole product coordinator with Task6-shaped native evidence."""

    if fixture.prepare(real_source_lock=True)[0] != 0:
        raise AssertionError
    plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
    authorization = fixture.root / "authorization.json"
    write_private_file(authorization, _canonical_bytes(_authorization(plan)))

    def host_factory(**kwargs: object) -> object:
        return DciBenchmarkHost(
            instance=cast(DciBenchmarkInstance, kwargs["instance"]), operator_config=cast(DciOperatorConfig, kwargs["operator_config"]),
            package_sources=cast(Sequence[CapabilityPackageSource] | None, kwargs["package_sources"]),
            query_planning_contract=cast(QueryPlanningContract, kwargs["query_planning_contract"]), query_planning_prompt_file=cast(Path | None, kwargs["query_planning_prompt_file"]),
        )

    clock: list[int] = []
    cursor = 0
    for _dataset in range(4):
        for duration in elapsed_ns:
            clock.extend((cursor, cursor + duration))
            cursor += duration
    calls: list[tuple[str, Decimal | None]] = []
    with (
        patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config", return_value=fixture.config),
        patch.object(DciBenchmarkHost, "_default_executor", return_value=_NativeEvidenceExecutor(calls, candidate_score=candidate_score, actual_cost=actual_cost, candidate_cost=candidate_cost, regression_dataset=regression_dataset)),
        patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.time.monotonic_ns", side_effect=clock),
    ):
        stderr = io.StringIO()
        if main(("execute", "--plan-file", str(fixture.output / PLAN_FILENAME), "--authorization-file", str(authorization), "--output-root", str(fixture.output)), stdout=io.StringIO(), stderr=stderr, repo_root=fixture.root, env_file=None, environment={}, host_factory=host_factory) != 0:
            raise AssertionError(stderr.getvalue())
    stdout, stderr = io.StringIO(), io.StringIO()
    if main(("finalize", "--plan-file", str(fixture.output / PLAN_FILENAME), "--authorization-file", str(authorization), "--diagnosis-file", str(fixture.diagnosis_file), "--output-root", str(fixture.output)), stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None, environment={}) != 0:
        raise AssertionError(stderr.getvalue())
    return json.loads(stdout.getvalue())


class TestExecute(unittest.TestCase):
    def test_execute_rejects_a_concurrent_coordinator_before_host_creation(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        lease = fixture.output / ".pathlight-bright-optimization.execution.lock"
        descriptor = os.open(lease, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            events: list[str] = []
            code, _output, events = _execute_optimization(fixture, events=events)
            self.assertEqual(code, 2)
            self.assertEqual(events, [])
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def test_result_cost_requires_exact_authorized_and_exclusive_actual_or_upper_artifacts(self) -> None:
        valid_actual = (
            "coverage-actual-microusd.17", "coverage-authorized-microusd.2000000"
        )
        valid_upper = (
            "coverage-authorized-microusd.2000000", "coverage-upper-microusd.2000000"
        )
        invalid = (
            (),
            ("coverage-actual-microusd.17",),
            ("coverage-authorized-microusd.1", "coverage-upper-microusd.1000000"),
            ("coverage-authorized-microusd.1000000", "coverage-upper-microusd.1"),
            ("coverage-actual-microusd.01", "coverage-authorized-microusd.1000000"),
            ("coverage-actual-microusd.17", "coverage-authorized-microusd.1000000", "coverage-upper-microusd.1000000"),
        )

        def result(artifacts: tuple[str, ...]) -> BenchmarkRunResult:
            return BenchmarkRunResult(
                "completed", (BenchmarkTaskResult("bright.biology", "completed", 10, artifacts),)
            )

        self.assertEqual(_result_cost(result(valid_actual), task_id="bright.biology", maximum=2_000_000), (17, "actual"))
        self.assertEqual(_result_cost(result(valid_upper), task_id="bright.biology", maximum=2_000_000), (2_000_000, "conservative"))
        for artifacts in invalid:
            with self.subTest(artifacts=artifacts), self.assertRaises(ValueError):
                _result_cost(result(artifacts), task_id="bright.biology", maximum=2_000_000)

    def test_real_dci_host_unknown_progress_failure_quarantines_and_resume_is_not_wedged(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare(real_source_lock=True)[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))
        calls: list[tuple[str, Decimal | None]] = []

        def host_factory(**kwargs: object) -> object:
            return DciBenchmarkHost(
                instance=cast(DciBenchmarkInstance, kwargs["instance"]), operator_config=cast(DciOperatorConfig, kwargs["operator_config"]),
                package_sources=cast(Sequence[CapabilityPackageSource] | None, kwargs["package_sources"]), query_planning_contract=cast(QueryPlanningContract, kwargs["query_planning_contract"]),
                query_planning_prompt_file=cast(Path | None, kwargs["query_planning_prompt_file"]),
            )

        with (
            patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config", return_value=fixture.config),
            patch.object(DciBenchmarkHost, "_default_executor", return_value=_NativeEvidenceExecutor(calls, fail_first=True)),
        ):
            self.assertEqual(main(
                ("execute", "--plan-file", str(fixture.output / PLAN_FILENAME),
                 "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
                env_file=None, environment={}, host_factory=host_factory,
            ), 2)
            self.assertFalse(any((fixture.output / "receipts").iterdir()))
            self.assertTrue(any((fixture.output / "evidence-quarantine").iterdir()))
            self.assertEqual(main(
                ("resume", "--plan-file", str(fixture.output / PLAN_FILENAME),
                 "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
                env_file=None, environment={}, host_factory=host_factory,
            ), 0)

    def test_real_dci_host_projects_native_receipts_and_revalidates_on_resume(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare(real_source_lock=True)[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))
        calls: list[tuple[str, Decimal | None]] = []

        def host_factory(**kwargs: object) -> object:
            return DciBenchmarkHost(
                instance=cast(DciBenchmarkInstance, kwargs["instance"]), operator_config=cast(DciOperatorConfig, kwargs["operator_config"]),
                package_sources=cast(Sequence[CapabilityPackageSource] | None, kwargs["package_sources"]),
                query_planning_contract=cast(QueryPlanningContract, kwargs["query_planning_contract"]),
                query_planning_prompt_file=cast(Path | None, kwargs["query_planning_prompt_file"]),
            )

        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config", return_value=fixture.config),
            patch.object(DciBenchmarkHost, "_default_executor", return_value=_NativeEvidenceExecutor(calls)),
        ):
            code = main(
                ("execute", "--plan-file", str(fixture.output / PLAN_FILENAME),
                 "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None,
                environment={}, host_factory=host_factory,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(len(calls), 8)
        self.assertTrue(all(amount == Decimal("2") for _task, amount in calls))
        receipt = json.loads((fixture.output / "receipts" / "receipt-1-0000.json").read_text())
        self.assertEqual(receipt["completed_case_count"], 10)
        self.assertEqual(receipt["cost_microusd"], 17)
        self.assertEqual(receipt["cost_source"], "actual")
        self.assertEqual((receipt["input_tokens"], receipt["output_tokens"], receipt["total_tokens"]), (1000, 500, 1500))
        self.assertTrue(all(receipt[name] for name in (
            "recovered_run_sha256", "experiment_bundle_sha256", "evaluation_bundle_sha256", "workflow_bundle_set_sha256",
        )))
        upper = json.loads((fixture.output / "receipts" / "receipt-2-0000.json").read_text())
        self.assertEqual((upper["cost_source"], upper["cost_microusd"]), ("conservative", 2_000_000))
        native = next((fixture.output / "evidence" / "bright.biology" / "baseline" / "outputs").glob("*/*"))
        recovered = read_completed_dci_run(native, "bright.biology")
        self.assertEqual(receipt["recovered_run_sha256"], recovered.recovered_run_sha256)
        self.assertEqual(receipt["experiment_bundle_sha256"], recovered_run_to_experiment(recovered).bundle_sha256)
        self.assertEqual(receipt["evaluation_bundle_sha256"], recovered_run_to_evaluation_bundle(recovered).bundle_sha256)
        tampered_workflow = next(native.glob("q-*/native-generation-0001/workflow-evidence.json"))
        tampered_workflow.chmod(0o600)
        tampered_workflow.write_text("{}", encoding="utf-8")
        self.assertEqual(main(
            ("resume", "--plan-file", str(fixture.output / PLAN_FILENAME),
             "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
            stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
            env_file=None, environment={}, host_factory=host_factory,
        ), 2)

    def test_native_projection_rejects_missing_duplicate_and_extra_workflows(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare(real_source_lock=True)[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))
        calls: list[tuple[str, Decimal | None]] = []

        def host_factory(**kwargs: object) -> object:
            return DciBenchmarkHost(
                instance=cast(DciBenchmarkInstance, kwargs["instance"]), operator_config=cast(DciOperatorConfig, kwargs["operator_config"]),
                package_sources=cast(Sequence[CapabilityPackageSource] | None, kwargs["package_sources"]),
                query_planning_contract=cast(QueryPlanningContract, kwargs["query_planning_contract"]),
                query_planning_prompt_file=cast(Path | None, kwargs["query_planning_prompt_file"]),
            )

        with (
            patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config", return_value=fixture.config),
            patch.object(DciBenchmarkHost, "_default_executor", return_value=_NativeEvidenceExecutor(calls)),
        ):
            self.assertEqual(main(
                ("execute", "--plan-file", str(fixture.output / PLAN_FILENAME),
                 "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
                env_file=None, environment={}, host_factory=host_factory,
            ), 0)
        native = next((fixture.output / "evidence" / "bright.biology" / "baseline" / "outputs").glob("*/*"))
        workflows = tuple(sorted(native.glob("q-*/native-generation-0001/workflow-evidence.json")))
        self.assertEqual(len(workflows), 10)
        extra = native / "q-extra" / "native-generation-0001"
        extra.parent.mkdir(mode=0o700)
        shutil.copytree(workflows[0].parent, extra)
        for path in extra.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        self.assertIsNone(_native_receipt_projection(native.parent.parent.parent, "bright.biology"))
        shutil.rmtree(extra)
        replacement = workflows[0]
        replacement.unlink()
        altered = {
            "schema": "asterion.workflow-evidence/v1", "run_id": "replacement-run",
            "input_digest": "f" * 64, "terminal_status": "completed", "tools": [],
            "usage": {"input_tokens": 1, "output_tokens": 2}, "artifacts": [],
        }
        altered["graph_sha256"] = hashlib.sha256(
            json.dumps(altered, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        write_workflow_observation_bundle(replacement, (altered,))
        # The native total may include provider-side billable/context tokens
        # which are intentionally absent from the structured workflow usage.
        self.assertIsNotNone(_native_receipt_projection(native.parent.parent.parent, "bright.biology"))
        workflows[-1].unlink()
        self.assertIsNone(_native_receipt_projection(native.parent.parent.parent, "bright.biology"))

    def test_execute_preflights_all_tasks_then_runs_exact_order_once(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(
            authorization,
            (json.dumps(_authorization(plan), sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
        events: list[str] = []

        def host_factory(*, task: object, **_kwargs: object) -> object:
            return _RecordingOptimizationHost(getattr(task, "get")("task_id"), events)

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch(
            "asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config",
            return_value=fixture.config,
        ):
            code = main(
                (
                    "execute",
                    "--plan-file", str(fixture.output / PLAN_FILENAME),
                    "--authorization-file", str(authorization),
                    "--output-root", str(fixture.output),
                ),
                stdout=stdout,
                stderr=stderr,
                repo_root=fixture.root,
                env_file=None,
                environment={},
                host_factory=host_factory,
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["status"], "completed")
        self.assertEqual(
            [event for event in events if event.startswith("run:")],
            [
                f"run:{dataset}.{role}"
                for dataset in ("bright.biology", "bright.earth-science", "bright.economics", "bright.robotics")
                for role in ("baseline", "candidate")
            ],
        )
        first_provider = next(index for index, event in enumerate(events) if event.startswith("provider:"))
        self.assertEqual(sum(event.startswith("preflight:") for event in events[:first_provider]), 40)
        receipts = sorted((fixture.output / "receipts").glob("receipt-*.json"))
        self.assertEqual(len(receipts), 8)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in receipts))

    def test_two_infrastructure_failures_stop_before_the_next_task(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))
        events: list[str] = []
        outcomes = {
            "bright.biology.baseline": ["network"],
            "bright.biology.candidate": ["network"],
        }

        def host_factory(*, task: object, **_kwargs: object) -> object:
            return _RecordingOptimizationHost(getattr(task, "get")("task_id"), events, outcomes)

        with patch(
            "asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config",
            return_value=fixture.config,
        ):
            code = main(
                ("execute", "--plan-file", str(fixture.output / PLAN_FILENAME), "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
                env_file=None, environment={}, host_factory=host_factory,
            )
        self.assertEqual(code, 1)
        self.assertEqual([event for event in events if event.startswith("run:")], [
            "run:bright.biology.baseline", "run:bright.biology.candidate",
        ])
        receipts = sorted((fixture.output / "receipts").glob("receipt-*.json"))
        self.assertEqual(len(receipts), 2)
        self.assertEqual(json.loads(receipts[0].read_text())["failure_category"], "network")

    def test_resume_is_provider_free_after_all_tasks_are_terminal(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))
        events: list[str] = []
        outcomes = {"bright.biology.baseline": ["failed"]}

        def host_factory(*, task: object, **_kwargs: object) -> object:
            return _RecordingOptimizationHost(getattr(task, "get")("task_id"), events, outcomes)

        with patch(
            "asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config",
            return_value=fixture.config,
        ):
            self.assertEqual(main(
                ("execute", "--plan-file", str(fixture.output / PLAN_FILENAME), "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
                env_file=None, environment={}, host_factory=host_factory,
            ), 0)
            count = len(events)
            self.assertEqual(main(
                ("resume", "--plan-file", str(fixture.output / PLAN_FILENAME), "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
                env_file=None, environment={}, host_factory=host_factory,
            ), 0)
        self.assertEqual(len(events), count)

    def test_status_rejects_reordered_or_forged_receipt_chain(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))
        with patch(
            "asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config",
            return_value=fixture.config,
        ):
            self.assertEqual(main(
                ("execute", "--plan-file", str(fixture.output / PLAN_FILENAME), "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
                env_file=None, environment={}, host_factory=lambda **kwargs: _RecordingOptimizationHost(kwargs["task"]["task_id"], []),
            ), 0)
        original = fixture.output / "receipts" / "receipt-2-0000.json"
        original.rename(fixture.output / "receipts" / "receipt-3-0000.json")
        self.assertEqual(main(
            ("status", "--plan-file", str(fixture.output / PLAN_FILENAME), "--output-root", str(fixture.output)),
            stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root, env_file=None, environment={},
        ), 2)

    def test_terminal_failure_cancellation_observation_and_cost_semantics(self) -> None:
        cases = (
            ("model", {"bright.biology.baseline": ["failed"]}, 0, "model-business", "terminal"),
            ("cancelled", {"bright.biology.baseline": ["cancelled"]}, 130, "cancelled", "cancelled"),
            ("observation", {"bright.biology.baseline": ["observation-invalid"]}, 0, "observation-invalid", "completed"),
            # A host-shaped fake cannot claim native closure: a completed
            # result without real DCI artifacts is observation-invalid.
            ("actual", {"bright.biology.baseline": ["actual:17"]}, 0, "observation-invalid", "completed"),
        )
        for name, outcomes, expected_code, category, expected_status in cases:
            with self.subTest(name=name):
                fixture = _OptimizationFixture()
                self.addCleanup(fixture.close)
                self.assertEqual(fixture.prepare()[0], 0)
                code, output, events = _execute_optimization(fixture, outcomes=outcomes)
                self.assertEqual(code, expected_code)
                receipt = json.loads((fixture.output / "receipts" / "receipt-1-0000.json").read_text())
                self.assertEqual(receipt["failure_category"], category)
                self.assertEqual(
                    (receipt["input_tokens"], receipt["output_tokens"], receipt["total_tokens"]),
                    (None, None, None),
                )
                self.assertIn(receipt["native_evidence_state"], {"invalid", "unavailable"})
                if name == "actual":
                    self.assertEqual(receipt["cost_microusd"], 17)
                    self.assertEqual(receipt["cost_source"], "actual")
                else:
                    self.assertEqual(receipt["cost_microusd"], 2_000_000)
                self.assertEqual(output["status"], expected_status)
                if name == "cancelled":
                    self.assertEqual([event for event in events if event.startswith("run:")], ["run:bright.biology.baseline"])

    def test_partial_resume_skips_terminal_task_and_executes_only_unstarted_tasks(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        events: list[str] = []
        code, _output, events = _execute_optimization(
            fixture, outcomes={"bright.biology.baseline": ["cancelled"]}, events=events
        )
        self.assertEqual(code, 130)
        count = len(events)
        code, output, events = _execute_optimization(fixture, command="resume", events=events)
        self.assertEqual(code, 0)
        self.assertEqual(output["status"], "terminal")
        self.assertNotIn("run:bright.biology.baseline", events[count:])
        self.assertEqual(len([event for event in events if event.startswith("run:")]), 8)

    def test_preflight_rejects_source_selection_and_prompt_drift_before_host_creation(self) -> None:
        for mutation in ("plan", "root", "source", "selection", "prompt"):
            with self.subTest(mutation=mutation):
                fixture = _OptimizationFixture()
                self.addCleanup(fixture.close)
                self.assertEqual(fixture.prepare()[0], 0)
                plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
                write_private_file(fixture.root / "authorization.json", _canonical_bytes(_authorization(plan)))
                if mutation == "plan":
                    path = fixture.output / PLAN_FILENAME
                    path.chmod(0o600)
                    data = json.loads(path.read_text())
                    data["candidate_execution_config_sha256"] = "0" * 64
                    data["plan_sha256"] = _digest({key: value for key, value in data.items() if key != "plan_sha256"})
                    path.unlink()
                    write_private_file(path, _canonical_bytes(data))
                elif mutation == "root":
                    # A different operator root cannot satisfy plan parent and
                    # recorded device/inode identity.
                    stdout, stderr = io.StringIO(), io.StringIO()
                    self.assertEqual(main(
                        ("execute", "--plan-file", str(fixture.output / PLAN_FILENAME), "--authorization-file", str(fixture.root / "authorization.json"), "--output-root", str(fixture.root)),
                        stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None,
                        environment={}, host_factory=lambda **_kwargs: (_ for _ in ()).throw(AssertionError()),
                    ), 2)
                    continue
                elif mutation == "source":
                    fixture.datasets["bright.biology"].write_bytes(_bright_rows() + b"\n")
                elif mutation == "selection":
                    path = fixture.output / "selections" / "bright.biology.json"
                    path.chmod(0o600)
                    data = json.loads(path.read_text())
                    data["selected_case_sha256s"] = list(reversed(data["selected_case_sha256s"]))
                    data["selected_ids_sha256"] = _digest(data["selected_case_sha256s"])
                    data["selection_sha256"] = _digest({key: value for key, value in data.items() if key != "selection_sha256"})
                    path.unlink()
                    write_private_file(path, _canonical_bytes(data))
                else:
                    path = fixture.output / str(plan["candidate_prompt_path"])
                    path.chmod(0o600)
                    path.write_text("drift", encoding="utf-8")
                    path.chmod(0o400)
                events: list[str] = []
                code, _output, events = _execute_optimization(fixture, events=events)
                self.assertEqual(code, 2)
                self.assertEqual(events, [])

    def test_unknown_host_failure_is_not_receipted(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        events: list[str] = []

        class UnexpectedFailure(Exception):
            pass

        original = _RecordingOptimizationHost.run

        def fail_unknown(self: _RecordingOptimizationHost, *args: object, **kwargs: object) -> BenchmarkRunResult:
            if self.task_id == "bright.biology.baseline":
                raise UnexpectedFailure()
            return original(self, *args, **kwargs)

        with patch.object(_RecordingOptimizationHost, "run", fail_unknown):
            code, _output, events = _execute_optimization(fixture, events=events)
        self.assertEqual(code, 2)
        self.assertEqual([event for event in events if event.startswith("provider:")], ["provider:bright.biology.baseline"])
        self.assertFalse(any((fixture.output / "receipts").iterdir()))
        self.assertFalse((fixture.output / "evidence" / "bright.biology" / "baseline").exists())
        self.assertTrue(any((fixture.output / "evidence-quarantine").iterdir()))

    def test_receipt_reader_rejects_private_file_attack_matrix(self) -> None:
        for mutation in ("truncate", "extra", "mode", "symlink", "fifo", "cost"):
            with self.subTest(mutation=mutation):
                fixture = _OptimizationFixture()
                self.addCleanup(fixture.close)
                self.assertEqual(fixture.prepare()[0], 0)
                self.assertEqual(_execute_optimization(fixture)[0], 0)
                receipts = fixture.output / "receipts"
                target = receipts / "receipt-1-0000.json"
                if mutation == "truncate":
                    target.chmod(0o600)
                    target.write_bytes(b"{")
                    target.chmod(0o600)
                elif mutation == "extra":
                    write_private_file(receipts / "receipt-9-0000.json", b"{}\n")
                elif mutation == "mode":
                    target.chmod(0o644)
                elif mutation == "symlink":
                    copied = receipts / "target.json"
                    target.rename(copied)
                    target.symlink_to(copied)
                elif mutation == "fifo":
                    target.unlink()
                    os.mkfifo(target, 0o600)
                else:
                    target.chmod(0o600)
                    data = json.loads(target.read_text())
                    data["cost_microusd"] = 1_000_001
                    data["receipt_sha256"] = _digest({key: value for key, value in data.items() if key != "receipt_sha256"})
                    target.unlink()
                    write_private_file(target, _canonical_bytes(data))
                self.assertEqual(main(
                    ("status", "--plan-file", str(fixture.output / PLAN_FILENAME), "--output-root", str(fixture.output)),
                    stdout=io.StringIO(), stderr=io.StringIO(), repo_root=fixture.root,
                    env_file=None, environment={},
                ), 2)


class TestFinalize(unittest.TestCase):
    def test_public_finalizer_rejects_metric_selection_and_pairing_invariants(self) -> None:
        """The public finalizer rejects closed-boundary lineage drift itself."""

        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        _finalize_real_native(fixture, candidate_score=1.0)
        from asterion.capabilities.dci.implementation.pathlight.optimization import (
            BrightNativeBatch,
            DciBrightOptimizationError,
            finalize_bright_optimization,
        )
        from asterion.pathlight.diagnosis import read_diagnosis_bundle

        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = read_optimization_authorization(fixture.root / "authorization.json", plan=plan)
        receipts = tuple(
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((fixture.output / "receipts").iterdir())
        )
        batches: list[BrightNativeBatch] = []
        tasks = cast(list[dict[str, object]], plan["tasks"])
        for task, receipt in zip(tasks, receipts, strict=True):
            root = next((fixture.output / str(task["evidence_path"]) / "outputs").glob("*/*"))
            bundles = tuple(sorted(
                read_workflow_observation_bundle(path).bundle_sha256
                for path in root.glob("q-*/native-generation-0001/workflow-evidence.json")
            ))
            batches.append(BrightNativeBatch(
                str(task["dataset_id"]), str(task["variant_role"]), receipt,
                read_completed_dci_run(root, str(task["dataset_id"])), bundles, root,
            ))
        diagnosis = read_diagnosis_bundle(fixture.diagnosis_file)

        bad_selection = json.loads(json.dumps(plan))
        selected = cast(list[str], bad_selection["tasks"][1]["selected_case_sha256s"])
        selected[0] = "0" * 64
        recovered_run = batches[0].recovered_run
        assert recovered_run is not None
        cases = (
            ("wrong-selected-item", bad_selection, tuple(batches)),
            ("duplicate-pair", plan, (*batches[:-1], batches[-2])),
            ("wrong-metric", plan, (replace(batches[0], recovered_run=replace(recovered_run, metric_name="accuracy")), *batches[1:])),
        )
        for name, candidate_plan, candidate_batches in cases:
            with self.subTest(name=name):
                with self.assertRaises(DciBrightOptimizationError):
                    finalize_bright_optimization(
                        plan=candidate_plan, authorization=authorization, receipts=receipts,
                        native_batches=candidate_batches, diagnosis=diagnosis,
                    )

    def test_finalize_marks_resealed_observation_failure_inconclusive_and_rejects_untrusted_usage(self) -> None:
        """A receipt may honestly report observation loss, but never null usage."""

        def rewrite_first_receipt(
            fixture: _OptimizationFixture, mutate: Callable[[dict[str, object]], None],
        ) -> None:
            previous: str | None = None
            for path in sorted((fixture.output / "receipts").iterdir()):
                receipt = json.loads(path.read_text(encoding="utf-8"))
                receipt.pop("receipt_sha256")
                if previous is None:
                    mutate(receipt)
                receipt["previous_receipt_sha256"] = previous
                receipt["receipt_sha256"] = _digest(receipt)
                previous = cast(str, receipt["receipt_sha256"])
                path.write_bytes(_canonical_bytes(receipt))
                path.chmod(0o600)

        def finalize(fixture: _OptimizationFixture) -> tuple[int, dict[str, object]]:
            stdout, stderr = io.StringIO(), io.StringIO()
            code = main(
                ("finalize", "--plan-file", str(fixture.output / PLAN_FILENAME),
                 "--authorization-file", str(fixture.root / "authorization.json"),
                 "--diagnosis-file", str(fixture.diagnosis_file), "--output-root", str(fixture.output)),
                stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None, environment={},
            )
            return code, json.loads(stdout.getvalue()) if stdout.getvalue() else {}

        observation = _OptimizationFixture()
        self.addCleanup(observation.close)
        _finalize_real_native(observation, candidate_score=1.0)

        def observation_invalid(receipt: dict[str, object]) -> None:
            receipt["failure_category"] = "observation-invalid"
            receipt["native_evidence_state"] = "invalid"
            for name in (
                "recovered_run_sha256", "experiment_bundle_sha256", "evaluation_bundle_sha256",
                "workflow_bundle_set_sha256", "input_tokens", "output_tokens", "total_tokens",
            ):
                receipt[name] = None

        rewrite_first_receipt(observation, observation_invalid)
        # Remove the first publication so this call must derive, not replay,
        # the newly sealed observation state.
        for name in (
            "pathlight-experiment.json", "pathlight-evaluations.json", "pathlight-optimization.json",
            "pathlight-diagnosis.json", "pathlight-bright-optimization.zh-CN.md",
        ):
            (observation.output / name).unlink()
        code, result = finalize(observation)
        self.assertEqual(code, 0)
        self.assertEqual((result["decision"], result["reason"]), ("inconclusive", "incomplete-trials"))

        request_only = _OptimizationFixture()
        self.addCleanup(request_only.close)
        _finalize_real_native(request_only, candidate_score=1.0)
        evidence_root = request_only.output / "evidence" / "bright.biology" / "baseline"
        native_root = next((evidence_root / "outputs").glob("*/*"))
        workflow_path = next(native_root.glob("q-*/native-generation-0001/workflow-evidence.json"))
        private_records = json.loads(workflow_path.read_text(encoding="utf-8"))["records"]
        trace_id = "00000000-0000-4000-8000-000000000999"
        workflow_path.unlink()
        request_only_trace = TraceGraph.build(
            trace_id,
            (
                TraceEvent.start(
                    trace_id, trace_id, None, 1, "task",
                    attributes={"missing_evidence_labels": ("model-request-boundary",)},
                ),
                TraceEvent.complete(trace_id, trace_id, 2),
            ),
        ).to_mapping()
        write_workflow_observation_bundle(
            workflow_path, private_records, pathlight_traces=(request_only_trace,),
        )
        workflow_path.chmod(0o600)
        native_projection = _native_receipt_projection(
            evidence_root, "bright.biology", expected_case_count=10,
        )
        self.assertIsNotNone(native_projection)
        rewrite_first_receipt(
            request_only,
            lambda receipt: receipt.update(cast(dict[str, object], native_projection)),
        )
        for name in (
            "pathlight-experiment.json", "pathlight-evaluations.json", "pathlight-optimization.json",
            "pathlight-diagnosis.json", "pathlight-bright-optimization.zh-CN.md",
        ):
            (request_only.output / name).unlink()
        code, result = finalize(request_only)
        self.assertEqual(code, 0)
        self.assertEqual((result["decision"], result["reason"]), ("accepted", "quality-and-efficiency-met"))

        for field in ("cost_microusd", "elapsed_ns"):
            with self.subTest(field=field):
                fixture = _OptimizationFixture()
                self.addCleanup(fixture.close)
                _finalize_real_native(fixture, candidate_score=1.0)
                rewrite_first_receipt(fixture, lambda receipt, name=field: receipt.__setitem__(name, None))
                self.assertEqual(finalize(fixture)[0], 2)

    def test_finalize_fails_closed_for_real_native_reader_tamper_matrix(self) -> None:
        """Finalize re-reads the Task 6 files; receipt digests are not authority."""

        def missing_workflow(native: Path) -> None:
            next(native.glob("q-*/native-generation-0001/workflow-evidence.json")).unlink()

        def tampered_workflow(native: Path) -> None:
            path = next(native.glob("q-*/native-generation-0001/workflow-evidence.json"))
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o600)

        def duplicate_trace(native: Path) -> None:
            paths = tuple(sorted(native.glob("q-*/native-generation-0001/workflow-evidence.json")))
            paths[1].write_bytes(paths[0].read_bytes())
            paths[1].chmod(0o600)

        def reordered_results(native: Path) -> None:
            path = native / "results.jsonl"
            path.write_bytes(b"".join(reversed(path.read_bytes().splitlines(keepends=True))))
            path.chmod(0o600)

        def extra_result(native: Path) -> None:
            path = native / "results.jsonl"
            path.write_bytes(path.read_bytes() + path.read_bytes().splitlines(keepends=True)[0])
            path.chmod(0o600)

        for name, mutate in (
            ("missing-workflow", missing_workflow), ("tampered-workflow", tampered_workflow),
            ("duplicate-trace", duplicate_trace), ("reordered-result", reordered_results),
            ("extra-result", extra_result),
        ):
            with self.subTest(name=name):
                fixture = _OptimizationFixture()
                self.addCleanup(fixture.close)
                _finalize_real_native(fixture, candidate_score=1.0)
                native = next((fixture.output / "evidence" / "bright.biology" / "baseline" / "outputs").glob("*/*"))
                mutate(native)
                stdout, stderr = io.StringIO(), io.StringIO()
                self.assertEqual(main(
                    ("finalize", "--plan-file", str(fixture.output / PLAN_FILENAME),
                     "--authorization-file", str(fixture.root / "authorization.json"),
                     "--diagnosis-file", str(fixture.diagnosis_file), "--output-root", str(fixture.output)),
                    stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None, environment={},
                ), 2)

    def test_report_shows_one_dataset_regression_without_overriding_global_criteria(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        result = _finalize_real_native(
            fixture, candidate_score=1.0, regression_dataset=2,
        )
        self.assertEqual(result["decision"], "accepted")
        report = (fixture.output / "pathlight-bright-optimization.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("bright.economics：baseline 750000，candidate 500000，delta -250000 微单位。", report)
        for dataset in ("bright.biology", "bright.earth-science", "bright.robotics"):
            self.assertIn(f"{dataset}：baseline 750000，candidate 1000000，delta 250000 微单位。", report)
        self.assertIn("40 条基线 + 40 条候选", report)
        self.assertIn("Decision：accepted（quality-and-efficiency-met）", report)
        self.assertIn("不能作为论文复现", report)
        self.assertNotIn("查询分解导致", report)

    def test_finalize_derives_each_pre_registered_rejection_reason(self) -> None:
        cases = (
            ("quality", 0.75, 100, None, (1_000, 1_000), "quality-threshold-missed"),
            ("cost", 1.0, 100, 130, (1_000, 1_000), "cost-threshold-exceeded"),
            ("time", 1.0, 100, None, (1_000, 1_300), "time-threshold-exceeded"),
            ("multiple", 0.75, 100, 130, (1_000, 1_300), "multiple-thresholds-missed"),
        )
        for name, score, cost, candidate_cost, elapsed, reason in cases:
            with self.subTest(name=name):
                fixture = _OptimizationFixture()
                self.addCleanup(fixture.close)
                result = _finalize_real_native(
                    fixture, candidate_score=score, actual_cost=cost,
                    candidate_cost=candidate_cost, elapsed_ns=elapsed,
                )
                self.assertEqual((result["decision"], result["reason"]), ("rejected", reason))

    def test_finalize_real_native_80_case_accepted_closure(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare(real_source_lock=True)[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))

        def host_factory(**kwargs: object) -> object:
            return DciBenchmarkHost(
                instance=cast(DciBenchmarkInstance, kwargs["instance"]),
                operator_config=cast(DciOperatorConfig, kwargs["operator_config"]),
                package_sources=cast(Sequence[CapabilityPackageSource] | None, kwargs["package_sources"]),
                query_planning_contract=cast(QueryPlanningContract, kwargs["query_planning_contract"]),
                query_planning_prompt_file=cast(Path | None, kwargs["query_planning_prompt_file"]),
            )

        calls: list[tuple[str, Decimal | None]] = []
        with (
            patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config", return_value=fixture.config),
            patch.object(DciBenchmarkHost, "_default_executor", return_value=_NativeEvidenceExecutor(calls, candidate_score=1.0, actual_cost=100)),
            patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli.time.monotonic_ns", side_effect=range(0, 16_000, 1_000)),
        ):
            execute_stdout, execute_stderr = io.StringIO(), io.StringIO()
            self.assertEqual(main(
                ("execute", "--plan-file", str(fixture.output / PLAN_FILENAME),
                 "--authorization-file", str(authorization), "--output-root", str(fixture.output)),
                stdout=execute_stdout, stderr=execute_stderr, repo_root=fixture.root,
                env_file=None, environment={}, host_factory=host_factory,
            ), 0, execute_stderr.getvalue())
        finalize_stdout, finalize_stderr = io.StringIO(), io.StringIO()
        self.assertEqual(main(
            ("finalize", "--plan-file", str(fixture.output / PLAN_FILENAME),
             "--authorization-file", str(authorization), "--diagnosis-file", str(fixture.diagnosis_file),
             "--output-root", str(fixture.output)),
            stdout=finalize_stdout, stderr=finalize_stderr, repo_root=fixture.root,
            env_file=None, environment={},
        ), 0, finalize_stderr.getvalue())
        result = json.loads(finalize_stdout.getvalue())
        self.assertEqual(result["decision"], "accepted", result)
        from asterion.pathlight.experiment import read_experiment_bundle
        from asterion.pathlight.evaluation import read_evaluation_bundle
        from asterion.pathlight.optimization import read_optimization_bundle, validate_optimization_closure
        from asterion.pathlight.diagnosis import read_diagnosis_bundle
        optimization = read_optimization_bundle(fixture.output / "pathlight-optimization.json")
        self.assertEqual(len(optimization.trials), 80)
        self.assertEqual(len(read_experiment_bundle(fixture.output / "pathlight-experiment.json").trials), 80)
        validate_optimization_closure(
            optimization, workflow_trace_sha256s=optimization.trace_sha256s,
            experiment_bundles=(read_experiment_bundle(fixture.output / "pathlight-experiment.json"),),
            evaluation_bundles=(read_evaluation_bundle(fixture.output / "pathlight-evaluations.json"),),
            diagnosis_bundles=(read_diagnosis_bundle(fixture.output / "pathlight-diagnosis.json"),),
        )
        report = (fixture.output / "pathlight-bright-optimization.zh-CN.md").read_text(encoding="utf-8")
        for dataset in ("bright.biology", "bright.earth-science", "bright.economics", "bright.robotics"):
            self.assertIn(f"{dataset}：baseline 750000，candidate 1000000，delta 250000 微单位。", report)
        self.assertIn("baseline 成本 400 微美元；candidate 成本 400 微美元；增幅 0 微单位。", report)
        self.assertIn("baseline 时间 4000 ns；candidate 时间 4000 ns；增幅 0 微单位。", report)
        self.assertIn("baseline 完成/失败/取消 40/0/0；candidate 完成/失败/取消 40/0/0", report)
        self.assertIn("证据缺口：无额外缺口", report)
        self.assertIn("不能作为论文复现或可比较结果", report)
        self.assertIn("最小下一步", report)
        for private in ("SENTINEL_PRIVATE_QUERY", "private answer", str(fixture.root), "query-planning"):
            self.assertNotIn(private, report)

    def test_finalize_without_native_receipts_publishes_inconclusive_closure_provider_free(self) -> None:
        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        self.assertEqual(fixture.prepare()[0], 0)
        plan = read_optimization_plan(fixture.output / PLAN_FILENAME)
        authorization = fixture.root / "authorization.json"
        write_private_file(authorization, _canonical_bytes(_authorization(plan)))
        stdout, stderr = io.StringIO(), io.StringIO()

        code = main(
            (
                "finalize", "--plan-file", str(fixture.output / PLAN_FILENAME),
                "--authorization-file", str(authorization), "--diagnosis-file", str(fixture.diagnosis_file),
                "--output-root", str(fixture.output),
            ),
            stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=fixture.root / ".env", environment={},
        )

        self.assertEqual(code, 0, stderr.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["decision"], "inconclusive")
        self.assertEqual(result["reason"], "incomplete-trials")
        report = (fixture.output / "pathlight-bright-optimization.zh-CN.md").read_text(encoding="utf-8")
        self.assertIn("40 条基线 + 40 条候选", report)
        self.assertIn("不能作为论文复现", report)
        self.assertNotIn("SENTINEL_PRIVATE_QUERY", report)
        names = {
            "pathlight-experiment.json", "pathlight-evaluations.json", "pathlight-optimization.json",
            "pathlight-diagnosis.json", "pathlight-bright-optimization.zh-CN.md",
        }
        self.assertTrue(all((fixture.output / name).is_file() for name in names))
        self.assertTrue(all(stat.S_IMODE((fixture.output / name).stat().st_mode) == 0o600 for name in names))
        unchanged = {name: (fixture.output / name).read_bytes() for name in names}
        unchanged_inodes = {
            name: ((fixture.output / name).stat().st_dev, (fixture.output / name).stat().st_ino)
            for name in names
        }
        rerun_stdout, rerun_stderr = io.StringIO(), io.StringIO()
        self.assertEqual(main(
            (
                "finalize", "--plan-file", str(fixture.output / PLAN_FILENAME),
                "--authorization-file", str(authorization), "--diagnosis-file", str(fixture.diagnosis_file),
                "--output-root", str(fixture.output),
            ), stdout=rerun_stdout, stderr=rerun_stderr, repo_root=fixture.root,
            env_file=fixture.root / ".env", environment={},
        ), 0, rerun_stderr.getvalue())
        conflict = fixture.output / "pathlight-evaluations.json"
        conflict.chmod(0o600)
        conflict.write_bytes(b"conflict")
        conflict.chmod(0o600)
        conflict_stdout, conflict_stderr = io.StringIO(), io.StringIO()
        self.assertEqual(main(
            (
                "finalize", "--plan-file", str(fixture.output / PLAN_FILENAME),
                "--authorization-file", str(authorization), "--diagnosis-file", str(fixture.diagnosis_file),
                "--output-root", str(fixture.output),
            ), stdout=conflict_stdout, stderr=conflict_stderr, repo_root=fixture.root,
            env_file=fixture.root / ".env", environment={},
        ), 2)
        for name, expected in unchanged.items():
            if name != conflict.name:
                self.assertEqual((fixture.output / name).read_bytes(), expected)
                self.assertEqual(
                    ((fixture.output / name).stat().st_dev, (fixture.output / name).stat().st_ino),
                    unchanged_inodes[name],
                )

    def test_finalize_publish_fault_rolls_back_every_new_output_and_staging_root(self) -> None:
        """A failed fifth-output transaction cannot expose a partial closure."""

        fixture = _OptimizationFixture()
        self.addCleanup(fixture.close)
        _finalize_real_native(fixture, candidate_score=1.0)
        names = (
            "pathlight-experiment.json", "pathlight-evaluations.json",
            "pathlight-optimization.json", "pathlight-diagnosis.json",
            "pathlight-bright-optimization.zh-CN.md",
        )
        for name in names:
            (fixture.output / name).unlink()

        original_link = os.link
        publish_count = 0

        def fail_third_publish(*args: Any, **kwargs: Any) -> None:
            nonlocal publish_count
            # The production publisher is descriptor-relative.  Only the
            # staging-to-root hard links are transaction publication points.
            if kwargs.get("src_dir_fd") is not None and kwargs.get("dst_dir_fd") is not None:
                publish_count += 1
                if publish_count == 3:
                    raise OSError("injected publication fault")
            original_link(*args, **kwargs)

        with patch(
            "asterion.applications.dci_agent_lite.pathlight_optimization_cli.os.link",
            side_effect=fail_third_publish,
        ):
            stdout, stderr = io.StringIO(), io.StringIO()
            self.assertEqual(main(
                ("finalize", "--plan-file", str(fixture.output / PLAN_FILENAME),
                 "--authorization-file", str(fixture.root / "authorization.json"),
                 "--diagnosis-file", str(fixture.diagnosis_file), "--output-root", str(fixture.output)),
                stdout=stdout, stderr=stderr, repo_root=fixture.root, env_file=None, environment={},
            ), 2)

        self.assertEqual(publish_count, 3)
        self.assertTrue(all(not (fixture.output / name).exists() for name in names))
        self.assertFalse(any(path.name.startswith(".pathlight-staging-") for path in fixture.output.iterdir()))

    def test_finalize_staging_write_and_cleanup_faults_leave_no_staging_tree(self) -> None:
        names = (
            "pathlight-experiment.json", "pathlight-evaluations.json",
            "pathlight-optimization.json", "pathlight-diagnosis.json",
            "pathlight-bright-optimization.zh-CN.md",
        )

        def arguments(fixture: _OptimizationFixture) -> tuple[str, ...]:
            return (
                "finalize", "--plan-file", str(fixture.output / PLAN_FILENAME),
                "--authorization-file", str(fixture.root / "authorization.json"),
                "--diagnosis-file", str(fixture.diagnosis_file), "--output-root", str(fixture.output),
            )

        stage = _OptimizationFixture()
        self.addCleanup(stage.close)
        _finalize_real_native(stage, candidate_score=1.0)
        for name in names:
            (stage.output / name).unlink()
        with patch(
            "asterion.applications.dci_agent_lite.pathlight_optimization_cli.write_optimization_bundle",
            side_effect=OSError("injected staging write fault"),
        ):
            self.assertEqual(main(
                arguments(stage), stdout=io.StringIO(), stderr=io.StringIO(), repo_root=stage.root,
                env_file=None, environment={},
            ), 2)
        self.assertTrue(all(not (stage.output / name).exists() for name in names))
        self.assertFalse(any(path.name.startswith(".pathlight-staging-") for path in stage.output.iterdir()))

        cleanup = _OptimizationFixture()
        self.addCleanup(cleanup.close)
        _finalize_real_native(cleanup, candidate_score=1.0)
        for name in names:
            (cleanup.output / name).unlink()
        from asterion.applications.dci_agent_lite import pathlight_optimization_cli
        original_cleanup = pathlight_optimization_cli._cleanup_staging_tree
        calls = 0

        def fail_cleanup_once(root: Path, staging: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected cleanup fault")
            original_cleanup(root, staging)

        with patch(
            "asterion.applications.dci_agent_lite.pathlight_optimization_cli._cleanup_staging_tree",
            side_effect=fail_cleanup_once,
        ):
            self.assertEqual(main(
                arguments(cleanup), stdout=io.StringIO(), stderr=io.StringIO(), repo_root=cleanup.root,
                env_file=None, environment={},
            ), 2)
        self.assertEqual(calls, 2)
        self.assertTrue(all((cleanup.output / name).is_file() for name in names))
        self.assertFalse(any(path.name.startswith(".pathlight-staging-") for path in cleanup.output.iterdir()))


class TestRouting(unittest.TestCase):
    def test_pathlight_cli_routes_optimization_to_product_coordinator(self) -> None:
        from asterion.applications.dci_agent_lite import pathlight_cli

        stdout, stderr = io.StringIO(), io.StringIO()
        coordinator = Mock(return_value=17)
        with patch(
            "asterion.applications.dci_agent_lite.pathlight_optimization_cli.main",
            coordinator,
        ):
            code = pathlight_cli.main(
                ("optimization", "status"),
                stdout=stdout,
                stderr=stderr,
                repo_root=Path.cwd(),
                env_file=None,
                environment={},
            )
        self.assertEqual(code, 17)
        coordinator.assert_called_once()
