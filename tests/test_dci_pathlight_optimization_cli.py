"""Provider-free preparation and authorization tests for Bright optimization."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from asterion.applications.dci_agent_lite.pathlight_optimization_cli import (
    PLAN_FILENAME,
    _AUTHORIZATION_SCHEMA,
    _diagnosis_digest,
    _digest,
    _proposal_scope,
    main,
    read_optimization_authorization,
    read_optimization_plan,
)
from asterion.pathlight._private_file import write_private_file


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
        selected = {
            dataset: {
                "selected_case_sha256s": sorted(
                    [
                        hashlib.sha256(
                            (
                                "asterion.dci.pathlight.query-id/v1\\0"
                                + json.dumps(str(index), separators=(",", ":"))
                            ).encode()
                        ).hexdigest()
                        for index in range(10)
                    ]
                )
            }
            for dataset in self.datasets
        }
        self.coverage, self.query = _proposal(_proposal_scope(selected))
        self.diagnosis = SimpleNamespace(
            bundle_sha256=_sha("diagnosis"),
            proposals=(self.coverage, self.query),
            findings=(
                SimpleNamespace(finding_sha256=self.coverage.finding_sha256),
                SimpleNamespace(finding_sha256=self.query.finding_sha256),
            ),
        )
        self.config = SimpleNamespace(
            benchmark_inputs=SimpleNamespace(dataset_roots=self.datasets)
        )

    def close(self) -> None:
        self.temp.cleanup()

    def prepare(self) -> tuple[int, dict[str, object], Mock]:
        stdout, stderr = io.StringIO(), io.StringIO()
        provider = Mock()
        with (
            patch(
                "asterion.applications.dci_agent_lite.pathlight_optimization_cli.read_diagnosis_bundle",
                return_value=self.diagnosis,
            ),
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
                    "--diagnosis-file", str(self.root / "diagnosis.json"),
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
        "proposal_sha256": plan["proposal_sha256"],
        "finding_sha256": plan["finding_sha256"],
        "scope_sha256": plan["scope_sha256"],
        "source_lock_sha256": plan["source_lock_sha256"],
        "selected_case_scope_sha256": plan["selected_case_scope_sha256"],
        "baseline_query_plan_sha256": plan["baseline_query_plan_sha256"],
        "candidate_query_plan_sha256": plan["candidate_query_plan_sha256"],
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
        self.assertNotIn("SENTINEL_PRIVATE_QUERY", json.dumps(output))
        provider.assert_not_called()


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
            "proposal_sha256",
            "finding_sha256",
            "scope_sha256",
            "source_lock_sha256",
            "selected_case_scope_sha256",
            "baseline_query_plan_sha256",
            "candidate_query_plan_sha256",
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
