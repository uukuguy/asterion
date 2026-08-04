"""Tests for immutable, evidence-closed Pathlight optimization records."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from asterion.pathlight import PathlightError
from asterion.pathlight.evaluation import EvaluationBundle, EvaluationRecord, MetricContract
from asterion.pathlight.experiment import (
    CaseTrial,
    DatasetSnapshot,
    EvaluatorContract,
    ExperimentBundle,
    ExperimentPlan,
    Variant,
)
from asterion.pathlight.diagnosis import DiagnosisBundle, Finding, Proposal
from asterion.pathlight.optimization import (
    OptimizationBundle,
    OptimizationCatalog,
    OptimizationCriteria,
    OptimizationTrial,
    TrialHistory,
    Decision,
    read_optimization_bundle,
    validate_decision,
    validate_optimization_bundle,
    validate_optimization_closure,
    validate_optimization_criteria,
    validate_optimization_trial,
    write_optimization_bundle,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _variant(label: str) -> Variant:
    return Variant(*(_sha(f"{label}-{field}") for field in range(9)))


def _metric() -> MetricContract:
    return MetricContract("evaluation-score", "microunits", True, "1.0.0")


def _dataset() -> DatasetSnapshot:
    return DatasetSnapshot(_sha("contract"), _sha("content"), 2, "1.0.0")


def _evaluator() -> EvaluatorContract:
    metric = _metric()
    return EvaluatorContract(metric.metric_contract_sha256, "rule", _sha("implementation"), _sha("input"), _sha("output"), _sha("failure"), "1.0.0")


def _plan(baseline: Variant, candidate: Variant) -> ExperimentPlan:
    return ExperimentPlan(
        _dataset().dataset_snapshot_sha256, _sha("scope"), baseline.variant_sha256,
        (candidate.variant_sha256,), _sha("assignment"), (_evaluator().evaluator_contract_sha256,),
        _sha("budget"), _sha("stop"), _sha("authorization"),
    )


def _evaluation(trace: str, value: int) -> EvaluationRecord:
    return EvaluationRecord(
        trace, _metric().metric_contract_sha256, _dataset().dataset_snapshot_sha256, _sha("scope"), value, 1, 1, "observed"
    )


def _case(plan: ExperimentPlan, item: str, variant: Variant, trace: str, evaluation: EvaluationRecord) -> CaseTrial:
    return CaseTrial(plan.experiment_plan_sha256, item, variant.variant_sha256, trace,
                     (evaluation.evaluation_sha256,), "observed", ())


def _trial(
    *,
    role: str = "baseline",
    item: str | None = None,
    value: int = 400_000,
    cost: int = 100,
    elapsed: int = 1_000,
    plan: ExperimentPlan | None = None,
    variant: Variant | None = None,
) -> OptimizationTrial:
    baseline = _variant("baseline")
    candidate = _variant("candidate")
    chosen_plan = plan or _plan(baseline, candidate)
    chosen_variant = variant or (baseline if role == "baseline" else candidate)
    item_digest = item or _sha(f"item-{role}")
    trace = _sha(f"trace-{role}-{item_digest}")
    evaluation = _evaluation(trace, value)
    case = _case(chosen_plan, item_digest, chosen_variant, trace, evaluation)
    return OptimizationTrial(
        chosen_plan.experiment_plan_sha256, case.case_trial_sha256, item_digest, cast(Any, role),
        chosen_variant.variant_sha256, trace, evaluation.evaluation_sha256, "completed",
        None, cost, 10, 20, elapsed,
    )


def _trial_mapping() -> dict[str, object]:
    return _trial().to_mapping()


def _bool_tokens(mapping: dict[str, object]) -> dict[str, object]:
    mapping["input_tokens"] = True
    return mapping


def _unknown_field(mapping: dict[str, object]) -> dict[str, object]:
    mapping["SENTINEL_QUESTION"] = "private"
    return mapping


def _failed_with_evaluation(mapping: dict[str, object]) -> dict[str, object]:
    mapping["status"] = "failed"
    return mapping


class _Closure:
    def __init__(self, *, baseline_values: tuple[int, ...], candidate_values: tuple[int, ...], baseline_cost: int = 100, candidate_cost: int = 120, baseline_time: int = 1_000, candidate_time: int = 1_100, missing_candidate: bool = False) -> None:
        self.baseline = _variant("baseline")
        self.candidate = _variant("candidate")
        self.plan = _plan(self.baseline, self.candidate)
        items = tuple(sorted(_sha(f"item-{index}") for index in range(len(baseline_values))))
        self.items = items
        trials: list[OptimizationTrial] = []
        evaluations: list[EvaluationRecord] = []
        cases: list[CaseTrial] = []
        for index, item in enumerate(items):
            for role, variant, values, cost, elapsed in (
                ("baseline", self.baseline, baseline_values, baseline_cost, baseline_time),
                ("candidate", self.candidate, candidate_values, candidate_cost, candidate_time),
            ):
                if missing_candidate and role == "candidate" and index == len(items) - 1:
                    continue
                trace = _sha(f"trace-{role}-{item}")
                evaluation = _evaluation(trace, values[index])
                case = _case(self.plan, item, variant, trace, evaluation)
                evaluations.append(evaluation)
                cases.append(case)
                trials.append(OptimizationTrial(
                    self.plan.experiment_plan_sha256, case.case_trial_sha256, item, cast(Any, role),
                    variant.variant_sha256, trace, evaluation.evaluation_sha256, "completed", None,
                    cost, 10, 20, elapsed,
                ))
        self.trials = tuple(trials)
        self.evaluations = tuple(evaluations)
        self.cases = tuple(cases)
        self.history_inputs = {
            "experiment_plan": self.plan,
            "baseline_variant": self.baseline,
            "candidate_variant": self.candidate,
            "trials": self.trials,
            "evaluations": self.evaluations,
            "expected_dataset_item_sha256s": self.items,
        }


def _complete_closure(**kwargs: object) -> _Closure:
    values: dict[str, object] = {
        "baseline_values": (400_000, 500_000),
        "candidate_values": (500_000, 550_000),
    }
    values.update(kwargs)
    return _Closure(**values)  # type: ignore[arg-type]


def _missing_candidate_closure() -> _Closure:
    return _Closure(baseline_values=(400_000, 500_000), candidate_values=(500_000, 550_000), missing_candidate=True)


def _derive(history: TrialHistory) -> Decision:
    return Decision.derive(
        proposal_sha256=_sha("proposal"), finding_sha256=_sha("finding"), history=history,
        criteria=OptimizationCriteria(50_000, 250_000, 250_000),
        operator_approval_sha256=_sha("approval"),
    )


def _history_sha() -> str:
    return TrialHistory.build(**_complete_closure().history_inputs).trial_history_sha256


def _optimization_bundle() -> tuple[OptimizationBundle, dict[str, object]]:
    closure = _complete_closure()
    history = TrialHistory.build(**closure.history_inputs)
    decision = _derive(history)
    dataset = _dataset()
    metric = _metric()
    evaluator = _evaluator()
    experiment = ExperimentBundle.build(
        datasets=(dataset,), evaluators=(evaluator,), variants=(closure.baseline, closure.candidate),
        plans=(closure.plan,), trials=closure.cases, evaluations=closure.evaluations,
    )
    sorted_evaluations = tuple(sorted(closure.evaluations, key=lambda value: value.evaluation_sha256))
    document = {"schema": "asterion.pathlight-evaluations/v1", "metric_contracts": [metric.to_mapping()], "evaluations": [value.to_mapping() for value in sorted_evaluations]}
    evaluations = EvaluationBundle((metric,), sorted_evaluations, hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    observed = Finding("observed", _sha("subject"), (closure.evaluations[0].evaluation_sha256,), (), "confirmed", _sha("finding-code"))
    finding = Finding("hypothesis", _sha("subject"), (observed.finding_sha256,), (), "medium", _sha("hypothesis-code"))
    proposal = Proposal(finding.finding_sha256, _sha("change"), _sha("scope"), _sha("criteria"), _sha("stop"), _sha("budget"))
    diagnosis = DiagnosisBundle.build(experiment_bundle_sha256s=(experiment.bundle_sha256,), evaluation_sha256s=tuple(sorted(value.evaluation_sha256 for value in closure.evaluations)), findings=(observed, finding), proposals=(proposal,))
    decision = Decision.derive(
        proposal_sha256=proposal.proposal_sha256, finding_sha256=finding.finding_sha256, history=history,
        criteria=OptimizationCriteria(50_000, 250_000, 250_000), operator_approval_sha256=_sha("approval"),
    )
    bundle = OptimizationBundle.build(
        experiment_bundle_sha256s=(experiment.bundle_sha256,), evaluation_bundle_sha256s=(evaluations.bundle_sha256,),
        diagnosis_bundle_sha256s=(diagnosis.bundle_sha256,), trace_sha256s=tuple(sorted(cast(str, value.trace_sha256) for value in closure.trials)),
        trials=closure.trials, histories=(history,), decisions=(decision,),
    )
    return bundle, cast(dict[str, Any], {
        "workflow_trace_sha256s": tuple(value.trace_sha256 for value in closure.trials),
        "experiment_bundles": (experiment,), "evaluation_bundles": (evaluations,), "diagnosis_bundles": (diagnosis,),
    })


class TestOptimizationContracts(unittest.TestCase):
    def test_trial_is_body_free_canonical_and_content_addressed(self) -> None:
        trial = _trial(role="baseline", item=_sha("case-1"), value=400_000)
        self.assertEqual(validate_optimization_trial(trial.to_mapping()), trial)
        encoded = json.dumps(trial.to_mapping(), sort_keys=True)
        self.assertNotIn("SENTINEL_QUESTION", encoded)
        self.assertRegex(trial.optimization_trial_sha256, r"^[0-9a-f]{64}$")

    def test_trial_rejects_bool_usage_unknown_fields_and_failed_score(self) -> None:
        for mutate in (_bool_tokens, _unknown_field, _failed_with_evaluation):
            with self.subTest(mutate=mutate.__name__):
                with self.assertRaisesRegex(PathlightError, "optimization trial is invalid"):
                    validate_optimization_trial(mutate(_trial_mapping()))

    def test_criteria_rejects_bool_and_bad_digest(self) -> None:
        criteria = OptimizationCriteria(50_000, 250_000, 250_000)
        self.assertEqual(validate_optimization_criteria(criteria.to_mapping()), criteria)
        mapping = criteria.to_mapping()
        mapping["minimum_mean_gain_microunits"] = True
        with self.assertRaises(PathlightError):
            validate_optimization_criteria(mapping)


class TestTrialHistory(unittest.TestCase):
    def test_history_pairs_every_item_and_decision_is_derived(self) -> None:
        closure = _complete_closure(
            baseline_values=(400_000, 500_000), candidate_values=(500_000, 550_000),
            baseline_cost=100, candidate_cost=120, baseline_time=1_000, candidate_time=1_100,
        )
        history = TrialHistory.build(**closure.history_inputs)
        decision = Decision.derive(
            proposal_sha256=_sha("proposal"), finding_sha256=_sha("finding"), history=history,
            criteria=OptimizationCriteria(50_000, 250_000, 250_000), operator_approval_sha256=_sha("approval"),
        )
        self.assertEqual(history.evidence_state, "complete")
        self.assertEqual(decision.result, "accepted")

    def test_incomplete_history_can_only_be_inconclusive(self) -> None:
        history = TrialHistory.build(**_missing_candidate_closure().history_inputs)
        self.assertEqual(_derive(history).result, "inconclusive")

    def test_complete_but_below_threshold_is_rejected(self) -> None:
        history = TrialHistory.build(**_complete_closure(candidate_values=(401_000, 499_000)).history_inputs)
        self.assertEqual(_derive(history).result, "rejected")

    def test_means_use_half_even_rounding_and_zero_baselines_are_bounded(self) -> None:
        tied = TrialHistory.build(**_complete_closure(
            baseline_values=(1, 2), candidate_values=(2, 3),
        ).history_inputs)
        self.assertEqual((tied.baseline_mean_microunits, tied.candidate_mean_microunits), (2, 2))
        zero = TrialHistory.build(**_complete_closure(
            baseline_cost=0, candidate_cost=1, baseline_time=0, candidate_time=1,
        ).history_inputs)
        self.assertEqual((zero.cost_increase_microunits, zero.time_increase_microunits), (1_000_001, 1_000_001))

    def test_decision_rejects_forged_criteria_digest(self) -> None:
        history = TrialHistory.build(**_complete_closure().history_inputs)
        mapping = _derive(history).to_mapping()
        mapping["success_criteria_sha256"] = _sha("forged-criteria")
        unsigned = {key: value for key, value in mapping.items() if key != "decision_sha256"}
        mapping["decision_sha256"] = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self.assertRaises(PathlightError):
            validate_decision(mapping)


class TestOptimizationStorage(unittest.TestCase):
    def test_bundle_round_trip_requires_internal_and_external_closure(self) -> None:
        bundle, dependencies = _optimization_bundle()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-optimization.json"
            write_optimization_bundle(path, bundle)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            loaded = read_optimization_bundle(path)
            validate_optimization_closure(loaded, **cast(Any, dependencies))
            self.assertEqual(loaded, bundle)
            with self.assertRaises(PathlightError):
                validate_optimization_closure(
                    loaded, workflow_trace_sha256s=(), experiment_bundles=(),
                    evaluation_bundles=(), diagnosis_bundles=(),
                )

    def test_catalog_lists_trials_without_private_content(self) -> None:
        bundle, _ = _optimization_bundle()
        catalog = OptimizationCatalog.build((bundle,))
        history = bundle.histories[0]
        values = catalog.list_trials(history.trial_history_sha256, variant_role="candidate")
        self.assertEqual(len(values), 2)
        self.assertNotIn("SENTINEL", json.dumps(values))

    def test_undeclared_external_bundles_cannot_supply_case_evaluation_or_proposal(self) -> None:
        bundle, dependencies = _optimization_bundle()
        unrelated_experiment = ExperimentBundle.build(
            datasets=(), evaluators=(), variants=(), plans=(), trials=(), evaluations=(),
        )
        unrelated_evaluations = EvaluationBundle((), (), hashlib.sha256(
            b'{"evaluations":[],"metric_contracts":[],"schema":"asterion.pathlight-evaluations/v1"}'
        ).hexdigest())
        unrelated_observed = Finding(
            "observed", _sha("unrelated-subject"), (_sha("unrelated-evaluation"),),
            (), "confirmed", _sha("unrelated-finding"),
        )
        unrelated_hypothesis = Finding(
            "hypothesis", _sha("unrelated-subject"), (unrelated_observed.finding_sha256,),
            (), "medium", _sha("unrelated-hypothesis"),
        )
        unrelated_proposal = Proposal(
            unrelated_hypothesis.finding_sha256, _sha("unrelated-change"),
            _sha("unrelated-scope"), _sha("unrelated-criteria"), _sha("unrelated-stop"),
            _sha("unrelated-budget"),
        )
        unrelated_diagnosis = DiagnosisBundle.build(
            experiment_bundle_sha256s=(_sha("unrelated-experiment"),),
            evaluation_sha256s=(_sha("unrelated-evaluation"),),
            findings=(unrelated_observed, unrelated_hypothesis), proposals=(unrelated_proposal,),
        )
        actual_experiments = cast(tuple[ExperimentBundle, ...], dependencies["experiment_bundles"])
        actual_evaluations = cast(tuple[EvaluationBundle, ...], dependencies["evaluation_bundles"])
        actual_diagnoses = cast(tuple[DiagnosisBundle, ...], dependencies["diagnosis_bundles"])
        for kind, experiments, evaluations, diagnoses in (
            ("case", (unrelated_experiment,), actual_evaluations, actual_diagnoses),
            ("evaluation", actual_experiments, (unrelated_evaluations,), actual_diagnoses),
            ("proposal", actual_experiments, actual_evaluations, (unrelated_diagnosis,)),
        ):
            with self.subTest(kind=kind):
                undeclared = OptimizationBundle.build(
                    experiment_bundle_sha256s=tuple(value.bundle_sha256 for value in experiments),
                    evaluation_bundle_sha256s=tuple(value.bundle_sha256 for value in evaluations),
                    diagnosis_bundle_sha256s=tuple(value.bundle_sha256 for value in diagnoses),
                    trace_sha256s=bundle.trace_sha256s, trials=bundle.trials,
                    histories=bundle.histories, decisions=bundle.decisions,
                )
                with self.assertRaises(PathlightError):
                    validate_optimization_closure(
                        undeclared,
                        workflow_trace_sha256s=cast(Any, dependencies["workflow_trace_sha256s"]),
                        experiment_bundles=(unrelated_experiment, *actual_experiments),
                        evaluation_bundles=(unrelated_evaluations, *actual_evaluations),
                        diagnosis_bundles=(unrelated_diagnosis, *actual_diagnoses),
                    )

    def test_store_and_mapping_reject_hostile_inputs(self) -> None:
        bundle, _ = _optimization_bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "pathlight-optimization.json"
            write_optimization_bundle(path, bundle)
            with self.assertRaises(PathlightError):
                write_optimization_bundle(path, bundle)
            path.chmod(0o644)
            with self.assertRaises(PathlightError):
                read_optimization_bundle(path)
        mapping = bundle.to_mapping()
        mapping["trials"] = list(reversed(cast(list[object], mapping["trials"])))
        with self.assertRaises(PathlightError):
            validate_optimization_bundle(mapping)
        history = bundle.histories[0]
        with self.assertRaises(PathlightError):
            OptimizationBundle.build(
                experiment_bundle_sha256s=bundle.experiment_bundle_sha256s,
                evaluation_bundle_sha256s=bundle.evaluation_bundle_sha256s,
                diagnosis_bundle_sha256s=bundle.diagnosis_bundle_sha256s,
                trace_sha256s=bundle.trace_sha256s,
                trials=(bundle.trials[0], bundle.trials[0]), histories=(history,), decisions=bundle.decisions,
            )

    def test_reader_rejects_symlink_and_fifo(self) -> None:
        bundle, _ = _optimization_bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            write_optimization_bundle(target / "pathlight-optimization.json", bundle)
            link = root / "pathlight-optimization.json"
            link.symlink_to(target / "pathlight-optimization.json")
            with self.assertRaises(PathlightError):
                read_optimization_bundle(link)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-optimization.json"
            os.mkfifo(path, 0o600)
            with self.assertRaises(PathlightError):
                read_optimization_bundle(path)
