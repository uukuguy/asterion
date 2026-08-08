"""Deterministic, public-safe diagnosis of the fixed recovered DCI cohort."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Literal

from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    AUTHORIZATION_GATE_REPORT_FILENAME,
    DciAggregateWorkflowMetrics,
    DciCoverageDatasetObservation,
    DciCoverageExperimentObservation,
    DciCoverageRecoveryAggregate,
    DciDatasetObservation,
    DciDiagnosisError,
    DciDiagnosisReport,
    DciProposalSummary,
    DciWorkflowMetrics,
    diagnose_recommended_pack,
    coverage_evaluation_values,
    read_authorization_gate_report,
    render_chinese_diagnosis,
    write_authorization_gate_report,
)

from asterion.capabilities.dci.implementation.pathlight.recovery import (
    DciRecoveredCase,
    DciRecoveredRun,
    DciRecoveredVariant,
)
from asterion.capabilities.dci.implementation.pathlight.recovery import _build_recovered_run
from asterion.pathlight.diagnosis import Finding


_DATASETS: tuple[tuple[str, Literal["ir", "qa"], Literal["ndcg-at-10", "accuracy"], int, int, int], ...] = (
    ("beir.scifact", "ir", "ndcg-at-10", 300, 752431, 1234),
    ("bright.biology", "ir", "ndcg-at-10", 103, 445584, 9999),
    ("bright.earth-science", "ir", "ndcg-at-10", 116, 500000, 9999),
    ("bright.economics", "ir", "ndcg-at-10", 103, 400000, 9999),
    ("bright.robotics", "ir", "ndcg-at-10", 101, 550000, 9999),
    ("qa.bamboogle", "qa", "accuracy", 125, 800000, 1234),
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run(
    dataset_id: str,
    mode: Literal["ir", "qa"],
    metric_name: Literal["ndcg-at-10", "accuracy"],
    count: int,
    value: int,
    corpus: int,
) -> DciRecoveredRun:
    variant = DciRecoveredVariant(*(_sha256("SENTINEL_PRIVATE_VARIANT") for _ in range(9)))
    cases = []
    for index in range(count):
        score = value if mode == "ir" else (1_000_000 if index < 100 else 0)
        read_time = 10 + index % 3
        grep_time = 30 + index % 2
        cases.append(
            DciRecoveredCase(
                _sha256(f"{dataset_id}:item:{index:04d}"), score, "completed",
                10 + index % 3, 1_000, 100 + index, read_time + grep_time,
                4, 0, 1, 3, read_time, grep_time,
                8 + index % 4, "not-available", None, _sha256(f"source:{dataset_id}:{index}"),
            )
        )
    cases.sort(key=lambda case: case.dataset_item_sha256)
    return _build_recovered_run(
        dataset_id, mode, metric_name, value, count, count, 0, corpus,
        _sha256(f"snapshot:{dataset_id}"), variant, tuple(cases),
        (_sha256(f"document:{dataset_id}"),),
        ("sealed-analysis-digest", "sealed-config-digest"),
    )


def _with_cases(
    run: DciRecoveredRun,
    cases: tuple[DciRecoveredCase, ...],
    *,
    metric_value_microunits: int | None = None,
) -> DciRecoveredRun:
    return _build_recovered_run(
        run.dataset_id, run.mode, run.metric_name,
        run.metric_value_microunits if metric_value_microunits is None else metric_value_microunits,
        run.selected_count, run.total_count, run.failed_count, run.corpus_file_count,
        run.dataset_snapshot_sha256, run.variant, tuple(sorted(cases, key=lambda case: case.dataset_item_sha256)),
        run.source_document_sha256s, run.missing_evidence,
    )


_COVERAGE_DATASET_IDS = (
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "beir.scifact",
)


def _coverage_pack(
    *, available_queries: int = 10, integrity_failure_count: int = 0
) -> DciCoverageExperimentObservation:
    datasets = tuple(
        DciCoverageDatasetObservation(
            dataset_id=dataset_id,
            coverage_available_queries=available_queries,
            coverage_total_queries=10,
            coverage_median_any_microunits=(
                800_000 if available_queries else None
            ),
            coverage_median_mean_microunits=(
                600_000 if available_queries else None
            ),
            coverage_median_all_microunits=(
                400_000 if available_queries else None
            ),
            retained_available_queries=available_queries,
            retained_median_microunits=(500_000 if available_queries else None),
            tool_observation_count=available_queries * 4,
            surfaced_gold_count=available_queries * 2,
            model_call_count=available_queries,
            context_frame_count=available_queries,
            missing_boundary_count=0,
            integrity_failure_count=integrity_failure_count,
            evidence_sha256=_sha256(f"coverage:{dataset_id}"),
        )
        for dataset_id in _COVERAGE_DATASET_IDS
    )
    return DciCoverageExperimentObservation(
        plan_sha256=_sha256("coverage-plan"),
        proposal_sha256=_sha256("coverage-proposal"),
        scope_sha256=_sha256("coverage-scope"),
        variant_sha256=_sha256("coverage-variant"),
        registry_set_sha256=_sha256("coverage-registry-set"),
        authorization_sha256=_sha256("coverage-authorization"),
        receipt_set_sha256=_sha256("coverage-receipts"),
        datasets=datasets,
        agent_operation_count=available_queries * len(datasets),
        judge_operation_count=0,
        consumed_cost_microusd=1_250_000,
        infrastructure_failure_count=0,
    )


class _RecoveredRunSubclass(DciRecoveredRun):
    pass


class _HostileObservation(DciDatasetObservation):
    method_called = False

    def to_mapping(self) -> dict[str, object]:
        type(self).method_called = True
        raise RuntimeError("SENTINEL_HOSTILE_OBSERVATION")


class _HostileMetrics(DciWorkflowMetrics):
    method_called = False

    def to_mapping(self) -> dict[str, int]:
        type(self).method_called = True
        raise RuntimeError("SENTINEL_HOSTILE_METRICS")


class _HostileFinding(Finding):
    method_called = False

    def to_mapping(self) -> dict[str, object]:
        type(self).method_called = True
        raise RuntimeError("SENTINEL_HOSTILE_FINDING")


class TestDciPathlightDiagnosis(unittest.TestCase):
    def test_recovery_aggregate_keeps_attempt_history_separate_from_valid_coverage(self) -> None:
        coverage = _coverage_pack()
        aggregate = DciCoverageRecoveryAggregate(
            coverage=coverage,
            parent_plan_sha256=_sha256("parent"),
            recovery_plan_sha256=_sha256("recovery"),
            attempted_agent_operation_count=50,
            actual_cost_microusd=5_106_161,
            infrastructure_failure_count=2,
            ledger_sha256=_sha256("ledger"),
        )
        self.assertTrue(aggregate.coverage.complete)
        self.assertEqual(aggregate.attempted_agent_operation_count, 50)
        self.assertEqual(aggregate.infrastructure_failure_count, 2)

    def test_recovery_aggregate_opens_the_coverage_diagnosis_gate(self) -> None:
        aggregate = DciCoverageRecoveryAggregate(
            coverage=_coverage_pack(), parent_plan_sha256=_sha256("parent"),
            recovery_plan_sha256=_sha256("recovery"), attempted_agent_operation_count=50,
            actual_cost_microusd=5_106_161, infrastructure_failure_count=2,
            ledger_sha256=_sha256("ledger"),
        )
        report = diagnose_recommended_pack(tuple(_run(*dataset) for dataset in _DATASETS), coverage_experiment=aggregate)
        self.assertEqual(report.query_decomposition_gate, "ready-for-authorization")

    def setUp(self) -> None:
        self.six_runs = tuple(_run(*dataset) for dataset in _DATASETS)

    def _diagnose(self) -> DciDiagnosisReport:
        return diagnose_recommended_pack(self.six_runs)

    def test_completed_coverage_replaces_only_missing_coverage_and_opens_gate(
        self,
    ) -> None:
        report = diagnose_recommended_pack(
            self.six_runs,
            coverage_experiment=_coverage_pack(),
        )

        self.assertNotIn("retrieval-coverage", report.missing_evidence)
        self.assertEqual(
            report.missing_evidence,
            (
                "assembly-lineage",
                "package-lineage",
                "sealed-analysis-digest",
                "sealed-config-digest",
                "trace-graph",
            ),
        )
        coverage = {
            item.dataset_id: item
            for item in report.observations
            if item.dataset_id in _COVERAGE_DATASET_IDS
        }
        self.assertEqual(set(coverage), set(_COVERAGE_DATASET_IDS))
        for item in coverage.values():
            self.assertEqual(item.coverage_available_queries, 10)
            self.assertEqual(item.coverage_total_queries, 10)
            self.assertEqual(item.coverage_median_any_microunits, 800_000)
            self.assertEqual(item.coverage_median_mean_microunits, 600_000)
            self.assertEqual(item.coverage_median_all_microunits, 400_000)
        self.assertEqual(
            report.query_decomposition_gate,
            "ready-for-authorization",
        )
        self.assertTrue(
            all(not proposal.execution_authorized for proposal in report.proposals)
        )
        coverage = report.coverage_experiment
        self.assertIsNotNone(coverage)
        assert coverage is not None
        contract, evaluations = coverage_evaluation_values(coverage)
        self.assertEqual(contract.metric_name, "coverage")
        self.assertEqual(len(evaluations), 5)
        self.assertTrue(
            {item.evaluation_sha256 for item in evaluations}
            <= set(report.diagnosis_bundle.evaluation_sha256s)
        )
        self.assertTrue(
            {item.evidence_sha256 for item in coverage.datasets}
            .isdisjoint(report.diagnosis_bundle.evaluation_sha256s)
        )

    def test_only_complete_real_diagnosis_can_publish_a_gate_report(self) -> None:
        ready = diagnose_recommended_pack(
            self.six_runs, coverage_experiment=_coverage_pack()
        )
        blocked = diagnose_recommended_pack(
            self.six_runs, coverage_experiment=_coverage_pack(available_queries=9)
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o700)
            path = root / AUTHORIZATION_GATE_REPORT_FILENAME
            write_authorization_gate_report(ready, path)
            stored = read_authorization_gate_report(path)
            self.assertEqual(
                stored["diagnosis_bundle_sha256"], ready.diagnosis_bundle.bundle_sha256
            )
            self.assertEqual(stored["diagnosis_report_sha256"], ready.report_sha256)
            self.assertTrue(stored["coverage_complete"])
            path.unlink()
            with self.assertRaises(DciDiagnosisError):
                write_authorization_gate_report(blocked, path)

    def test_partial_or_integrity_failed_coverage_keeps_gate_blocked(self) -> None:
        for coverage in (
            _coverage_pack(available_queries=9),
            _coverage_pack(integrity_failure_count=1),
        ):
            with self.subTest(coverage=coverage.experiment_sha256):
                report = diagnose_recommended_pack(
                    self.six_runs,
                    coverage_experiment=coverage,
                )
                self.assertIn("retrieval-coverage", report.missing_evidence)
                self.assertEqual(
                    report.query_decomposition_gate,
                    "blocked-by-coverage",
                )
                rendered = render_chinese_diagnosis(report)
                self.assertIn(
                    "覆盖观测未完整，未关闭检索覆盖率缺口",
                    rendered,
                )
                self.assertIn("授权门槛阻塞", rendered)
                self.assertNotIn("只关闭检索覆盖率缺口", rendered)
                self.assertTrue(
                    all(
                        not proposal.execution_authorized
                        for proposal in report.proposals
                    )
                )

    def test_completed_coverage_renderer_is_correlation_only_and_safe(self) -> None:
        report = diagnose_recommended_pack(
            self.six_runs,
            coverage_experiment=_coverage_pack(),
        )
        rendered = render_chinese_diagnosis(report)

        for value in (800_000, 600_000, 400_000, 500_000, 40, 20, 10):
            self.assertIn(str(value), rendered)
        self.assertIn("观测相关性", rendered)
        self.assertIn("不证明因果关系", rendered)
        self.assertIn("可申请单独授权", rendered)
        self.assertIn("当前未授权", rendered)
        for forbidden in (
            "SENTINEL_PRIVATE",
            "source:",
            "item:",
            "provider",
            "model",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_coverage_aggregate_rejects_reordering_subclasses_and_tampering(
        self,
    ) -> None:
        coverage = _coverage_pack()
        with self.assertRaises(ValueError):
            DciCoverageExperimentObservation(
                plan_sha256=coverage.plan_sha256,
                proposal_sha256=coverage.proposal_sha256,
                scope_sha256=coverage.scope_sha256,
                variant_sha256=coverage.variant_sha256,
                registry_set_sha256=coverage.registry_set_sha256,
                authorization_sha256=coverage.authorization_sha256,
                receipt_set_sha256=coverage.receipt_set_sha256,
                datasets=tuple(reversed(coverage.datasets)),
                agent_operation_count=50,
                judge_operation_count=0,
                consumed_cost_microusd=coverage.consumed_cost_microusd,
                infrastructure_failure_count=0,
            )

        class CoverageSubclass(DciCoverageDatasetObservation):
            pass

        first = coverage.datasets[0]
        with self.assertRaises(ValueError):
            CoverageSubclass(
                dataset_id=first.dataset_id,
                coverage_available_queries=first.coverage_available_queries,
                coverage_total_queries=first.coverage_total_queries,
                coverage_median_any_microunits=(
                    first.coverage_median_any_microunits
                ),
                coverage_median_mean_microunits=(
                    first.coverage_median_mean_microunits
                ),
                coverage_median_all_microunits=(
                    first.coverage_median_all_microunits
                ),
                retained_available_queries=first.retained_available_queries,
                retained_median_microunits=first.retained_median_microunits,
                tool_observation_count=first.tool_observation_count,
                surfaced_gold_count=first.surfaced_gold_count,
                model_call_count=first.model_call_count,
                context_frame_count=first.context_frame_count,
                missing_boundary_count=first.missing_boundary_count,
                integrity_failure_count=first.integrity_failure_count,
                evidence_sha256=first.evidence_sha256,
            )

        with self.assertRaises(ValueError):
            DciCoverageDatasetObservation(
                dataset_id=first.dataset_id,
                coverage_available_queries=first.coverage_available_queries,
                coverage_total_queries=first.coverage_total_queries,
                coverage_median_any_microunits=(
                    first.coverage_median_any_microunits
                ),
                coverage_median_mean_microunits=(
                    first.coverage_median_mean_microunits
                ),
                coverage_median_all_microunits=None,
                retained_available_queries=first.retained_available_queries,
                retained_median_microunits=first.retained_median_microunits,
                tool_observation_count=first.tool_observation_count,
                surfaced_gold_count=first.surfaced_gold_count,
                model_call_count=first.model_call_count,
                context_frame_count=first.context_frame_count,
                missing_boundary_count=first.missing_boundary_count,
                integrity_failure_count=first.integrity_failure_count,
                evidence_sha256=first.evidence_sha256,
            )

        object.__setattr__(coverage, "experiment_sha256", "0" * 64)
        with self.assertRaisesRegex(DciDiagnosisError, "^DCI diagnosis is invalid$"):
            diagnose_recommended_pack(
                self.six_runs,
                coverage_experiment=coverage,
            )

    def test_diagnosis_separates_observed_hypothesis_missing_and_reference_only(self) -> None:
        report = self._diagnose()
        self.assertEqual(report.dataset_count, 6)
        self.assertEqual(report.total_case_count, 848)
        self.assertEqual(report.reference_gaps_microunits["bright.biology"], -325416)
        self.assertEqual(report.reference_gaps_microunits["beir.scifact"], -4569)
        self.assertEqual(report.reference_status["bright.biology"], "reference-only")
        self.assertIn("retrieval-coverage", report.missing_evidence)
        self.assertTrue(all(item.category != "observed" or item.confidence == "confirmed" for item in report.findings))
        self.assertTrue(all(proposal.execution_authorized is False for proposal in report.proposals))

    def test_report_and_renderer_are_order_independent_and_public_safe(self) -> None:
        forward = self._diagnose()
        reversed_runs = tuple(replace(run, cases=tuple(reversed(run.cases))) for run in reversed(self.six_runs))
        reverse = diagnose_recommended_pack(reversed_runs)
        self.assertEqual(_json(forward.to_mapping()), _json(reverse.to_mapping()))
        rendered = render_chinese_diagnosis(forward)
        self.assertEqual(rendered, render_chinese_diagnosis(reverse))
        for sentinel in ("SENTINEL_PRIVATE", "source:", "item:"):
            self.assertNotIn(sentinel, _json(forward.to_mapping()) + rendered)
        for section in ("已证实事实", "待验证假设", "反证与不可比较项", "证据缺口", "最小受控实验"):
            self.assertIn(section, rendered)

    def test_fixed_hypotheses_proposals_and_safe_numeric_contracts(self) -> None:
        report = self._diagnose()
        self.assertEqual(report.hypothesis_codes, (
            "retrieval-scale-noise", "query-decomposition", "context-retention", "paper-method-difference",
        ))
        self.assertEqual(tuple(proposal.code for proposal in report.proposals), (
            "coverage-instrumentation", "retrieval-query-decomposition",
        ))
        self.assertEqual(report.proposals[0].agent_operation_cap, 50)
        self.assertEqual(report.proposals[0].max_cost_microusd, 5_000_000)
        self.assertEqual(report.proposals[0].infrastructure_failure_stop, 2)
        self.assertEqual(report.proposals[1].agent_operation_cap, 80)
        self.assertEqual(report.proposals[1].minimum_mean_ndcg_gain_microunits, 50_000)
        self.assertEqual(report.proposals[1].maximum_cost_or_time_increase_microunits, 250_000)
        self.assertTrue(all(proposal.requires_operator_authorization for proposal in report.proposals))
        self.assertTrue(all(not proposal.execution_authorized for proposal in report.proposals))

    def test_resolution_and_complete_read_grep_timing_metrics_are_explicit(self) -> None:
        report = self._diagnose()
        self.assertEqual(
            tuple(item.resolution_available_queries for item in report.observations),
            (0, 0, 0, 0, 0, 0),
        )
        biology = next(item for item in report.observations if item.dataset_id == "bright.biology")
        self.assertEqual(biology.resolution_total_queries, 103)
        self.assertEqual(biology.resolution_coverage_status, "not-available")
        self.assertEqual(biology.workflow_metrics.median_read_time_ns, 11)
        self.assertEqual(biology.workflow_metrics.median_grep_time_ns, 30)
        self.assertEqual(biology.workflow_metrics.read_time_share_microunits, 264919)
        self.assertEqual(biology.workflow_metrics.grep_time_share_microunits, 735080)
        rendered = render_chinese_diagnosis(report)
        for item in report.observations:
            self.assertIn(f"覆盖可用 0/{item.selected_count}", rendered)

    def test_renderer_includes_every_safe_dataset_metric_and_component_relation(self) -> None:
        report = self._diagnose()
        rendered = render_chinese_diagnosis(report)
        for observation in report.observations:
            with self.subTest(dataset=observation.dataset_id):
                metrics = observation.workflow_metrics
                for value in (
                    observation.score_microunits,
                    observation.reference_score_microunits,
                    observation.reference_gap_microunits,
                    observation.corpus_file_count,
                    metrics.zero_score_rate_microunits,
                    metrics.median_agent_total_tokens,
                    metrics.median_tool_call_count,
                    metrics.median_wall_time_ns,
                    metrics.median_tool_time_ns,
                    metrics.median_read_call_count,
                    metrics.median_grep_call_count,
                    metrics.median_read_time_ns,
                    metrics.median_grep_time_ns,
                    metrics.median_question_word_count,
                    metrics.total_tool_error_count,
                    metrics.tool_time_share_microunits,
                    metrics.read_time_share_microunits,
                    metrics.grep_time_share_microunits,
                ):
                    self.assertIn(str(value), rendered)
        self.assertEqual(rendered.count("组件摘要关系："), 30)
        self.assertIn("覆盖率观测：状态 proposed；最多 50 次 Agent 操作", rendered)
        self.assertIn("检索查询分解：状态 proposed；最多 80 次 Agent 操作", rendered)

    def test_aggregate_metrics_exclude_cross_dataset_score_statistics(self) -> None:
        report = self._diagnose()
        self.assertIs(type(report.aggregate_workflow_metrics), DciAggregateWorkflowMetrics)
        self.assertNotIn("zero_score_rate_microunits", report.aggregate_workflow_metrics.to_mapping())
        self.assertFalse(hasattr(report.aggregate_workflow_metrics, "zero_score_rate_microunits"))

        changed_runs = []
        for run in self.six_runs:
            if run.dataset_id != "qa.bamboogle":
                changed_runs.append(run)
                continue
            zero_index = next(
                index for index, case in enumerate(run.cases)
                if case.metric_value_microunits == 0
            )
            changed_cases = list(run.cases)
            changed_cases[zero_index] = replace(
                changed_cases[zero_index], metric_value_microunits=1_000_000
            )
            changed_runs.append(
                _with_cases(
                    run,
                    tuple(changed_cases),
                    metric_value_microunits=808_000,
                )
            )
        changed = diagnose_recommended_pack(tuple(changed_runs))
        self.assertEqual(
            report.aggregate_workflow_metrics.to_mapping(),
            changed.aggregate_workflow_metrics.to_mapping(),
        )

    def test_diagnosis_accepts_parallel_tool_time_above_one_case_wall_time(self) -> None:
        biology = next(run for run in self.six_runs if run.dataset_id == "bright.biology")
        changed_case = replace(
            biology.cases[0], wall_time_ns=1, tool_time_ns=2,
            read_time_ns=1, grep_time_ns=1,
        )
        changed = _with_cases(biology, (changed_case, *biology.cases[1:]))
        runs = tuple(changed if run.dataset_id == "bright.biology" else run for run in self.six_runs)
        report = diagnose_recommended_pack(runs)
        self.assertEqual(report.dataset_count, 6)

    def test_diagnosis_computes_large_nanosecond_time_shares_without_overflow(self) -> None:
        factor = 10_000_000_000
        enlarged = []
        for run in self.six_runs:
            cases = tuple(
                replace(
                    case,
                    wall_time_ns=case.wall_time_ns * factor,
                    tool_time_ns=case.tool_time_ns * factor,
                    read_time_ns=case.read_time_ns * factor,
                    grep_time_ns=case.grep_time_ns * factor,
                )
                for case in run.cases
            )
            enlarged.append(_with_cases(run, cases))
        report = diagnose_recommended_pack(tuple(enlarged))
        self.assertLessEqual(
            report.aggregate_workflow_metrics.tool_time_share_microunits,
            1_000_000,
        )

    def test_proposals_bind_exact_canonical_case_scopes_and_sole_variables(self) -> None:
        report = self._diagnose()
        runs = {run.dataset_id: run for run in self.six_runs}
        bright_ids = (
            "bright.biology", "bright.earth-science", "bright.economics", "bright.robotics"
        )
        coverage_ids = (*bright_ids, "beir.scifact")
        scopes = {
            dataset_id: _domain_digest(
                "proposal-dataset-case-scope",
                {
                    "dataset_id": dataset_id,
                    "case_sha256s": [
                        case.dataset_item_sha256
                        for case in runs[dataset_id].cases[:10]
                    ],
                },
            )
            for dataset_id in coverage_ids
        }
        coverage_scope = _combined_scope(scopes, coverage_ids, "coverage")
        bright_scope = _combined_scope(scopes, bright_ids, "paired-bright")
        coverage, query = report.proposals
        self.assertEqual(coverage.case_scope_sha256, coverage_scope)
        self.assertEqual(query.case_scope_sha256, bright_scope)
        self.assertEqual(coverage.dataset_case_counts, tuple((item, 10) for item in coverage_ids))
        self.assertEqual(query.dataset_case_counts, tuple((item, 10) for item in bright_ids))
        self.assertEqual(
            coverage.dataset_case_scope_sha256s,
            tuple((item, scopes[item]) for item in coverage_ids),
        )
        self.assertEqual(
            query.dataset_case_scope_sha256s,
            tuple((item, scopes[item]) for item in bright_ids),
        )
        self.assertEqual((coverage.baseline_operation_count, coverage.candidate_operation_count), (50, 0))
        self.assertEqual((query.baseline_operation_count, query.candidate_operation_count), (40, 40))
        self.assertEqual(
            coverage.sole_variable_sha256,
            _domain_digest("proposal-sole-variable", "trajectory-coverage-instrumentation-only"),
        )
        self.assertEqual(
            query.sole_variable_sha256,
            _domain_digest("proposal-sole-variable", "retrieval-query-planning"),
        )

        core_by_sha = {
            item.proposal_sha256: item for item in report.diagnosis_bundle.proposals
        }
        coverage_core = core_by_sha[coverage.proposal_sha256]
        query_core = core_by_sha[query.proposal_sha256]
        self.assertEqual(
            coverage_core.change_sha256,
            _domain_digest("proposal-change", {
                "change": "coverage-instrumentation",
                "sole_variable_sha256": coverage.sole_variable_sha256,
            }),
        )
        self.assertEqual(
            coverage_core.scope_sha256,
            _domain_digest("proposal-scope", _scope_mapping(coverage)),
        )
        self.assertEqual(
            coverage_core.success_criteria_sha256,
            _domain_digest("proposal-success", {"trajectory_coverage_recorded": True}),
        )
        self.assertEqual(
            coverage_core.stop_criteria_sha256,
            _domain_digest("proposal-stop", {"infrastructure_failures": 2}),
        )
        self.assertEqual(
            coverage_core.budget_sha256,
            _domain_digest("proposal-budget", {
                "agent_operations": 50, "max_cost_microusd": 5_000_000,
            }),
        )
        self.assertEqual(
            query_core.change_sha256,
            _domain_digest("proposal-change", {
                "change": "retrieval-query-decomposition",
                "sole_variable_sha256": query.sole_variable_sha256,
            }),
        )
        self.assertEqual(
            query_core.scope_sha256,
            _domain_digest("proposal-scope", _scope_mapping(query)),
        )
        self.assertEqual(
            query_core.success_criteria_sha256,
            _domain_digest("proposal-success", {
                "mean_ndcg_gain_microunits": 50_000,
                "maximum_cost_or_time_increase_microunits": 250_000,
            }),
        )
        self.assertEqual(
            query_core.stop_criteria_sha256,
            _domain_digest("proposal-stop", {
                "prerequisite_proposal_sha256": coverage.proposal_sha256,
            }),
        )
        self.assertEqual(
            query_core.budget_sha256,
            _domain_digest("proposal-budget", {
                "agent_operations": 80, "max_cost_microusd": 16_000_000,
            }),
        )

        for attribute, value in (
            ("dataset_case_counts", (("bright.biology", 9), *coverage.dataset_case_counts[1:])),
            (
                "dataset_case_scope_sha256s",
                (("bright.biology", "2" * 64), *coverage.dataset_case_scope_sha256s[1:]),
            ),
            ("case_scope_sha256", "0" * 64),
            ("baseline_operation_count", 49),
            ("sole_variable_sha256", "1" * 64),
        ):
            forged = self._diagnose()
            object.__setattr__(forged.proposals[0], attribute, value)
            object.__setattr__(forged, "report_sha256", _report_digest(forged))
            self._assert_render_error(forged)

        forged = self._diagnose()
        object.__setattr__(forged.proposals[1], "candidate_operation_count", 39)
        object.__setattr__(forged, "report_sha256", _report_digest(forged))
        self._assert_render_error(forged)

    def test_component_matrix_excludes_bamboogle_health_anchor(self) -> None:
        report = self._diagnose()
        self.assertEqual(len(report.component_comparisons), 30)
        self.assertNotIn(
            "qa.bamboogle",
            {item.dataset_id for item in report.component_comparisons},
        )

    def test_renderer_rejects_self_consistent_forged_nested_values_without_leakage(self) -> None:
        mutations: tuple[tuple[str, object], ...] = (
            ("score_microunits", "SENTINEL_RENDER_LEAK"),
            ("selected_count", True),
            ("failed_count", -1),
            ("corpus_file_count", 1 << 63),
        )
        for attribute, value in mutations:
            with self.subTest(attribute=attribute):
                report = self._diagnose()
                object.__setattr__(report.observations[0], attribute, value)
                object.__setattr__(report, "report_sha256", _report_digest(report))
                self._assert_render_error(report)

        report = self._diagnose()
        object.__setattr__(report, "findings", tuple(reversed(report.findings)))
        object.__setattr__(report, "report_sha256", _report_digest(report))
        self._assert_render_error(report)

        report = self._diagnose()
        object.__setattr__(report.proposals[0], "proposal_sha256", "0" * 64)
        object.__setattr__(report, "report_sha256", _report_digest(report))
        self._assert_render_error(report)

        report = self._diagnose()
        object.__setattr__(report, "report_sha256", "0" * 64)
        self._assert_render_error(report)

    def test_renderer_rejects_malicious_subclasses_without_calling_methods(self) -> None:
        report = self._diagnose()
        source = report.observations[0]
        hostile = object.__new__(_HostileObservation)
        for field_name in source.__dataclass_fields__:
            object.__setattr__(hostile, field_name, getattr(source, field_name))
        _HostileObservation.method_called = False
        object.__setattr__(report, "observations", (hostile, *report.observations[1:]))
        self._assert_render_error(report)
        self.assertFalse(_HostileObservation.method_called)

        report = self._diagnose()
        source_metrics = report.observations[0].workflow_metrics
        hostile_metrics = object.__new__(_HostileMetrics)
        for field_name in source_metrics.__dataclass_fields__:
            object.__setattr__(hostile_metrics, field_name, getattr(source_metrics, field_name))
        _HostileMetrics.method_called = False
        object.__setattr__(report.observations[0], "workflow_metrics", hostile_metrics)
        self._assert_render_error(report)
        self.assertFalse(_HostileMetrics.method_called)

        report = self._diagnose()
        source_finding = report.diagnosis_bundle.findings[0]
        hostile_finding = object.__new__(_HostileFinding)
        for field_name in source_finding.__dataclass_fields__:
            object.__setattr__(hostile_finding, field_name, getattr(source_finding, field_name))
        _HostileFinding.method_called = False
        object.__setattr__(
            report.diagnosis_bundle,
            "findings",
            (hostile_finding, *report.diagnosis_bundle.findings[1:]),
        )
        self._assert_render_error(report)
        self.assertFalse(_HostileFinding.method_called)

    def test_report_models_reject_nonexact_or_out_of_range_values(self) -> None:
        report = self._diagnose()
        metrics = report.aggregate_workflow_metrics
        invalid_metrics = (
            ("read_time_share_microunits", -1),
            ("grep_time_share_microunits", 1_000_001),
            ("median_read_time_ns", 1 << 63),
        )
        for attribute, value in invalid_metrics:
            mapping: dict[str, object] = {}
            mapping.update(metrics.to_mapping())
            mapping[attribute] = value
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                DciAggregateWorkflowMetrics(**mapping)  # type: ignore[arg-type]

        dataset_metrics = report.observations[0].workflow_metrics.to_mapping()
        dataset_metrics["zero_score_rate_microunits"] = True
        with self.assertRaises(ValueError):
            DciWorkflowMetrics(**dataset_metrics)

        with self.assertRaises(ValueError):
            replace(report.observations[0], dataset_id="SENTINEL_UNKNOWN_DATASET")
        with self.assertRaises(ValueError):
            replace(report.component_comparisons[0], component="unknown")
        with self.assertRaises(ValueError):
            replace(report.proposals[0], max_cost_microusd=-1)
        with self.assertRaises(ValueError):
            replace(report, findings=tuple(reversed(report.findings)))

    def _assert_render_error(self, report: DciDiagnosisReport) -> None:
        with self.assertRaisesRegex(DciDiagnosisError, "^DCI diagnosis is invalid$") as raised:
            render_chinese_diagnosis(report)
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn("SENTINEL", repr(raised.exception))

    def test_fails_closed_for_wrong_pack_or_hostile_values(self) -> None:
        original = self.six_runs[0]
        subclass = _RecoveredRunSubclass(
            original.dataset_id, original.mode, original.metric_name,
            original.metric_value_microunits, original.selected_count, original.total_count,
            original.failed_count, original.corpus_file_count, original.dataset_snapshot_sha256,
            original.variant, original.cases, original.source_document_sha256s,
            original.missing_evidence, original.recovered_run_sha256,
        )
        invalid_inputs = (
            self.six_runs[:-1], self.six_runs + (self.six_runs[0],),
            (*self.six_runs[:-1], self.six_runs[0]),
            tuple(replace(run, metric_name="accuracy") if run.dataset_id == "bright.biology" else run for run in self.six_runs),
            tuple(replace(run, total_count=run.total_count + 1) if run.dataset_id == "bright.biology" else run for run in self.six_runs),
            (subclass, *self.six_runs[1:]),
            tuple(replace(run, missing_evidence=("unknown-evidence-code",)) if run.dataset_id == "bright.biology" else run for run in self.six_runs),
            tuple(
                _with_cases(
                    run,
                    (replace(run.cases[0], resolution_status="available", resolution_coverage_microunits=0), *run.cases[1:]),
                ) if run.dataset_id == "bright.biology" else run
                for run in self.six_runs
            ),
        )
        for index, runs in enumerate(invalid_inputs):
            with self.subTest(index=index), self.assertRaisesRegex(DciDiagnosisError, "^DCI diagnosis is invalid$") as raised:
                diagnose_recommended_pack(runs)
            self.assertIsNone(raised.exception.__cause__)
            self.assertNotIn("SENTINEL", str(raised.exception))


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _report_digest(report: DciDiagnosisReport) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "domain": "asterion.dci.pathlight.diagnosis/report/v1",
                "value": report._unsigned_mapping(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _domain_digest(domain: str, value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "domain": f"asterion.dci.pathlight.diagnosis/{domain}/v1",
                "value": value,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _combined_scope(
    scopes: dict[str, str], dataset_ids: tuple[str, ...], purpose: str
) -> str:
    return _domain_digest(
        "proposal-case-scope",
        {
            "datasets": [
                {
                    "dataset_id": dataset_id,
                    "case_count": 10,
                    "case_scope_sha256": scopes[dataset_id],
                    "role": (
                        "scifact-anchor"
                        if dataset_id == "beir.scifact"
                        else "bright-target"
                    ),
                }
                for dataset_id in dataset_ids
            ],
            "purpose": purpose,
            "total_case_count": len(dataset_ids) * 10,
        },
    )


def _scope_mapping(proposal: DciProposalSummary) -> dict[str, object]:
    return {
        "case_scope_sha256": proposal.case_scope_sha256,
        "dataset_case_counts": [list(item) for item in proposal.dataset_case_counts],
        "dataset_case_scope_sha256s": [
            list(item) for item in proposal.dataset_case_scope_sha256s
        ],
        "baseline_operation_count": proposal.baseline_operation_count,
        "candidate_operation_count": proposal.candidate_operation_count,
    }


if __name__ == "__main__":
    unittest.main()
