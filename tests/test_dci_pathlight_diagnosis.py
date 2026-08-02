"""Deterministic, public-safe diagnosis of the fixed recovered DCI cohort."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from typing import Literal

from asterion.capabilities.dci.implementation.pathlight.diagnosis import (
    DciDatasetObservation,
    DciDiagnosisError,
    DciDiagnosisReport,
    DciWorkflowMetrics,
    diagnose_recommended_pack,
    render_chinese_diagnosis,
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


def _with_cases(run: DciRecoveredRun, cases: tuple[DciRecoveredCase, ...]) -> DciRecoveredRun:
    return _build_recovered_run(
        run.dataset_id, run.mode, run.metric_name, run.metric_value_microunits,
        run.selected_count, run.total_count, run.failed_count, run.corpus_file_count,
        run.dataset_snapshot_sha256, run.variant, tuple(sorted(cases, key=lambda case: case.dataset_item_sha256)),
        run.source_document_sha256s, run.missing_evidence,
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
    def setUp(self) -> None:
        self.six_runs = tuple(_run(*dataset) for dataset in _DATASETS)

    def _diagnose(self) -> DciDiagnosisReport:
        return diagnose_recommended_pack(self.six_runs)

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
            ("zero_score_rate_microunits", True),
            ("read_time_share_microunits", -1),
            ("grep_time_share_microunits", 1_000_001),
            ("median_read_time_ns", 1 << 63),
        )
        for attribute, value in invalid_metrics:
            mapping: dict[str, object] = {}
            mapping.update(metrics.to_mapping())
            mapping[attribute] = value
            with self.subTest(attribute=attribute), self.assertRaises(ValueError):
                DciWorkflowMetrics(**mapping)  # type: ignore[arg-type]

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


if __name__ == "__main__":
    unittest.main()
