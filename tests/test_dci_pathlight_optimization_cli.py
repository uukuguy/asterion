"""Provider-free preparation and authorization tests for Bright optimization."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asterion.benchmarks.evidence import BenchmarkRunResult, BenchmarkTaskResult

from asterion.applications.dci_agent_lite.pathlight_optimization_cli import (
    PLAN_FILENAME,
    _AUTHORIZATION_SCHEMA,
    _canonical_bytes,
    _diagnosis_digest,
    _digest,
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
                "id": f"private-{index}",
                "query": "SENTINEL_PRIVATE_QUERY",
                "query_id": index,
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
            "proposal-budget", {"agent_operations": 80, "max_cost_microusd": 8_000_000}
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
        self.config = SimpleNamespace(
            benchmark_inputs=SimpleNamespace(
                dataset_roots=self.datasets, private_environment={}
            )
        )
        self.diagnosis_file = self.root / DIAGNOSIS_BUNDLE_FILENAME
        self.report_file = self.root / DCI_DIAGNOSIS_REPORT_FILENAME
        self.gate = self.root / _GATE_FILENAME
        write_diagnosis_bundle(self.diagnosis, self.diagnosis_file)
        write_dci_diagnosis_report(self.report, self.report_file)
        write_authorization_gate_report(self.report, self.gate)

    def close(self) -> None:
        self.temp.cleanup()

    def prepare(self) -> tuple[int, dict[str, object], Mock]:
        stdout, stderr = io.StringIO(), io.StringIO()
        provider = Mock()
        with (
            patch("asterion.applications.dci_agent_lite.pathlight_optimization_cli._proposal_scope", return_value=self.query_scope),
            patch(
                "asterion.applications.dci_agent_lite.pathlight_optimization_cli.load_operator_config",
                return_value=self.config,
            ),
            patch(
                "asterion.applications.dci_agent_lite.pathlight_optimization_cli.resolve_benchmark_source_lock",
                return_value=object(),
            ),
            patch(
                "asterion.applications.dci_agent_lite.pathlight_optimization_cli.write_benchmark_source_lock",
                side_effect=_write_lock,
            ),
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
        "max_cost_microusd": 8_000_000,
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
        self.assertEqual(output["max_cost_microusd"], 8_000_000)
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
        self.assertEqual(fixture.prepare()[0], 0)
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
        self.assertEqual(fixture.prepare()[0], 0)
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
        artifact_ids: tuple[str, ...] = ()
        if status == "observation-invalid":
            status = "completed"
            artifact_ids = ("pathlight-observation-invalid",)
        elif status.startswith("actual:"):
            _prefix, amount = status.split(":", 1)
            status = "completed"
            artifact_ids = (f"pathlight-actual-microusd.{amount}",)
        return BenchmarkRunResult(
            status,
            (BenchmarkTaskResult(self.task_id.rsplit(".", 1)[0], status, 10 if status == "completed" else 0, artifact_ids),),
        )


class NetworkFailure(Exception):
    pass


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

    def host_factory(*, task: object, **_kwargs: object) -> object:
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


class TestExecute(unittest.TestCase):
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
            ("actual", {"bright.biology.baseline": ["actual:17"]}, 0, "none", "completed"),
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
                self.assertEqual(receipt["tokens"], 0)
                if name == "actual":
                    self.assertEqual(receipt["cost_microusd"], 17)
                    self.assertEqual(receipt["cost_source"], "actual")
                else:
                    self.assertEqual(receipt["cost_microusd"], 1_000_000)
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
