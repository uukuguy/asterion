from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from collections.abc import ItemsView, Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from asterion.pathlight import PathlightError
from asterion.pathlight.evaluation import EvaluationRecord
from asterion.pathlight.experiment import (
    CaseTrial,
    DatasetSnapshot,
    EvaluatorContract,
    ExperimentPlan,
    ExperimentBundle,
    ExperimentCatalog,
    SubjectRef,
    Variant,
    validate_case_trial,
    validate_dataset_snapshot,
    validate_evaluator_contract,
    validate_experiment_plan,
    validate_subject_ref,
    validate_variant,
    read_experiment_bundle,
    write_experiment_bundle,
)


_HOSTILE_SENTINEL = "SENTINEL_PRIVATE_PATHLIGHT_EXPERIMENT"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _HostileMapping(Mapping[str, object]):
    def __init__(self, payload: Mapping[str, object], fail_at: str) -> None:
        self._payload = payload
        self._fail_at = fail_at

    def __getitem__(self, key: str) -> object:
        if self._fail_at == "getitem":
            raise RuntimeError(f"{_HOSTILE_SENTINEL}: getitem")
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        if self._fail_at == "pathlight":
            raise PathlightError(f"{_HOSTILE_SENTINEL}: pathlight")
        if self._fail_at == "iter":
            raise RuntimeError(f"{_HOSTILE_SENTINEL}: iter")
        return iter(self._payload)

    def __len__(self) -> int:
        if self._fail_at == "len":
            raise RuntimeError(f"{_HOSTILE_SENTINEL}: len")
        return len(self._payload)

    def items(self) -> ItemsView[str, object]:
        raise RuntimeError(f"{_HOSTILE_SENTINEL}: items")


class _DigestSubclass(str):
    pass


class PathlightExperimentTests(unittest.TestCase):
    def assertPublicPathlightError(self, error: PathlightError, message: str) -> None:
        self.assertEqual(str(error), message)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertNotIn(_HOSTILE_SENTINEL, repr(error))

    def _complete_bundle_values(
        self,
    ) -> tuple[
        DatasetSnapshot, EvaluatorContract, Variant, ExperimentPlan, CaseTrial, EvaluationRecord
    ]:
        dataset = DatasetSnapshot(_digest("dataset-contract"), _digest("dataset"), 1, "1.0.0")
        evaluator = EvaluatorContract(
            _digest("metric"), "rule", _digest("implementation"), _digest("input"),
            _digest("output"), _digest("failure"), "1.0.0",
        )
        variant = Variant(*(_digest(name) for name in (
            "assembly", "packages", "implementation", "runtime", "model", "tools",
            "prompt", "policy", "change",
        )))
        plan = ExperimentPlan(
            dataset.dataset_snapshot_sha256, _digest("scope"), variant.variant_sha256, (),
            _digest("assignment"), (evaluator.evaluator_contract_sha256,), _digest("budget"),
            _digest("stop"),
        )
        evaluation = EvaluationRecord(
            _digest("trace"), evaluator.metric_contract_sha256, dataset.dataset_snapshot_sha256,
            plan.scope_sha256, 1, 1, 1, "recovered",
        )
        trial = CaseTrial(
            plan.experiment_plan_sha256, _digest("case"), variant.variant_sha256,
            evaluation.trace_sha256, (evaluation.evaluation_sha256,), "recovered", (),
        )
        return dataset, evaluator, variant, plan, trial, evaluation

    def test_bundle_requires_complete_exact_reference_closure(self) -> None:
        dataset, evaluator, variant, plan, trial, evaluation = self._complete_bundle_values()
        bundle = ExperimentBundle.build(
            datasets=(dataset,), evaluators=(evaluator,), variants=(variant,), plans=(plan,),
            trials=(trial,), evaluations=(evaluation,),
        )
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pathlight-experiment.json"
            write_experiment_bundle(bundle, target)
            loaded = read_experiment_bundle(target)
        self.assertEqual(loaded, bundle)
        self.assertEqual(loaded.bundle_sha256, bundle.bundle_sha256)

    def test_bundle_rejects_unresolved_trial_evaluation(self) -> None:
        dataset, evaluator, variant, plan, trial, evaluation = self._complete_bundle_values()
        with self.assertRaises(PathlightError):
            ExperimentBundle.build(
                datasets=(dataset,), evaluators=(evaluator,), variants=(variant,), plans=(plan,),
                trials=(replace(trial, evaluation_sha256s=("0" * 64,)),),
                evaluations=(evaluation,),
            )

    def test_catalog_returns_deterministic_read_only_plan_and_trial_projections(self) -> None:
        dataset, evaluator, variant, plan, trial, evaluation = self._complete_bundle_values()
        bundle = ExperimentBundle.build(
            datasets=(dataset,), evaluators=(evaluator,), variants=(variant,), plans=(plan,),
            trials=(trial,), evaluations=(evaluation,),
        )
        catalog = ExperimentCatalog.build((bundle,))

        self.assertEqual(catalog.show_plan(plan.experiment_plan_sha256)["experiment_plan_sha256"], plan.experiment_plan_sha256)
        rows = catalog.list_trials(plan.experiment_plan_sha256, evidence_state="recovered")
        self.assertEqual(rows[0]["case_trial_sha256"], trial.case_trial_sha256)
        with self.assertRaises(TypeError):
            rows[0]["case_trial_sha256"] = "x"  # type: ignore[index]

        supplied_plans = {plan.experiment_plan_sha256: plan}
        direct_catalog = ExperimentCatalog(supplied_plans, {})
        supplied_plans.clear()
        self.assertEqual(
            direct_catalog.show_plan(plan.experiment_plan_sha256)["experiment_plan_sha256"],
            plan.experiment_plan_sha256,
        )

    def test_builds_digest_only_case_trial_lineage(self) -> None:
        dataset = DatasetSnapshot(
            dataset_contract_sha256=_digest("dataset-contract"),
            content_sha256=_digest("dataset-content"),
            total_count=103,
            snapshot_version="1.0.0",
        )
        evaluator = EvaluatorContract(
            metric_contract_sha256=_digest("metric"),
            evaluator_kind="recovered",
            implementation_sha256=_digest("evaluator"),
            input_contract_sha256=_digest("evaluator-input"),
            output_contract_sha256=_digest("evaluator-output"),
            failure_semantics_sha256=_digest("evaluator-failures"),
            contract_version="1.0.0",
        )
        variant = Variant(
            assembly_sha256=_digest("assembly"),
            package_set_sha256=_digest("packages"),
            implementation_sha256=_digest("implementation"),
            runtime_sha256=_digest("runtime"),
            model_sha256=_digest("model"),
            toolset_sha256=_digest("tools"),
            prompt_contract_sha256=_digest("prompt-contract"),
            policy_sha256=_digest("policy"),
            change_sha256=_digest("observation-baseline"),
        )
        trial = CaseTrial(
            experiment_plan_sha256=_digest("experiment-plan"),
            dataset_item_sha256=_digest("private-query-id"),
            variant_sha256=variant.variant_sha256,
            trace_sha256=_digest("recovered-trace"),
            evaluation_sha256s=(_digest("evaluation"),),
            evidence_state="recovered",
            missing_evidence=("context-frames", "retrieval-coverage"),
        )

        self.assertRegex(trial.case_trial_sha256, r"^[0-9a-f]{64}$")
        self.assertNotIn("private-query-id", json.dumps(trial.to_mapping()))
        self.assertEqual(trial.missing_evidence, tuple(sorted(trial.missing_evidence)))
        self.assertRegex(dataset.dataset_snapshot_sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(evaluator.evaluator_contract_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(validate_case_trial(trial.to_mapping()), trial)

    def test_validates_each_exact_canonical_mapping(self) -> None:
        subject = SubjectRef("trace", _digest("trace"))
        dataset = DatasetSnapshot(
            _digest("dataset-contract"), _digest("dataset-content"), 0, "1.0.0"
        )
        evaluator = EvaluatorContract(
            _digest("metric"),
            "rule",
            _digest("implementation"),
            _digest("input"),
            _digest("output"),
            _digest("failures"),
            "1.0.0",
        )
        variant = Variant(*(_digest(name) for name in (
            "assembly", "packages", "implementation", "runtime", "model", "tools",
            "prompt", "policy", "change",
        )))
        plan = ExperimentPlan(
            dataset.dataset_snapshot_sha256,
            _digest("scope"),
            variant.variant_sha256,
            (),
            _digest("assignment"),
            (evaluator.evaluator_contract_sha256,),
            _digest("budget"),
            _digest("stop-criteria"),
        )

        for validator, value, digest_name in (
            (validate_subject_ref, subject, "subject_ref_sha256"),
            (validate_dataset_snapshot, dataset, "dataset_snapshot_sha256"),
            (validate_evaluator_contract, evaluator, "evaluator_contract_sha256"),
            (validate_variant, variant, "variant_sha256"),
            (validate_experiment_plan, plan, "experiment_plan_sha256"),
        ):
            with self.subTest(validator=validator.__name__):
                mapping = value.to_mapping()
                self.assertEqual(validator(mapping), value)
                self.assertEqual(mapping[digest_name], getattr(value, digest_name))
                mapping["unknown"] = "private value"
                with self.assertRaises(PathlightError):
                    validator(mapping)

    def test_rejects_unknown_fields_subclasses_and_noncanonical_arrays(self) -> None:
        with self.assertRaises(PathlightError):
            validate_case_trial({"schema": "asterion.pathlight-case-trial/v1"})
        with self.assertRaises(PathlightError):
            CaseTrial(
                experiment_plan_sha256=_digest("plan"),
                dataset_item_sha256=_digest("case"),
                variant_sha256=_digest("variant"),
                trace_sha256=_digest("trace"),
                evaluation_sha256s=tuple(reversed(sorted((_digest("a"), _digest("b"))))),
                evidence_state="recovered",
                missing_evidence=(),
            )
        with self.assertRaises(PathlightError):
            SubjectRef("trace", _DigestSubclass(_digest("trace")))
        with self.assertRaises(PathlightError):
            DatasetSnapshot(_digest("contract"), _digest("content"), True, "1.0.0")
        with self.assertRaises(PathlightError):
            CaseTrial(
                _digest("plan"),
                _digest("case"),
                _digest("variant"),
                _digest("trace"),
                (),
                "observed",
                ("private-evidence",),
            )

    def test_experiment_plan_requires_sorted_unique_references_and_stop_criteria(self) -> None:
        candidates = tuple(sorted((_digest("candidate-a"), _digest("candidate-b"))))
        with self.assertRaises(PathlightError):
            ExperimentPlan(
                _digest("dataset"), _digest("scope"), _digest("baseline"),
                tuple(reversed(candidates)), _digest("assignment"), (_digest("evaluator"),),
                _digest("budget"), _digest("stop"),
            )

        with self.assertRaises(PathlightError):
            ExperimentPlan(
                _digest("dataset"), _digest("scope"), _digest("baseline"),
                (_digest("candidate"),), _digest("assignment"), (_digest("evaluator"),),
                _digest("budget"), "invalid",
            )

    def test_public_validators_normalize_hostile_mapping_failures(self) -> None:
        values = (
            (validate_subject_ref, SubjectRef("trace", _digest("trace"))),
            (
                validate_dataset_snapshot,
                DatasetSnapshot(_digest("contract"), _digest("content"), 1, "1.0.0"),
            ),
            (
                validate_evaluator_contract,
                EvaluatorContract(
                    _digest("metric"), "human", _digest("implementation"),
                    _digest("input"), _digest("output"), _digest("failure"), "1.0.0",
                ),
            ),
            (
                validate_variant,
                Variant(*(_digest(name) for name in (
                    "assembly", "packages", "implementation", "runtime", "model", "tools",
                    "prompt", "policy", "change",
                ))),
            ),
            (
                validate_experiment_plan,
                ExperimentPlan(
                    _digest("dataset"), _digest("scope"), _digest("baseline"), (),
                    _digest("assignment"), (), _digest("budget"), _digest("stop"),
                ),
            ),
            (
                validate_case_trial,
                CaseTrial(
                    _digest("plan"), _digest("case"), _digest("variant"), _digest("trace"),
                    (), "missing", (),
                ),
            ),
        )

        for validator, value in values:
            for fail_at in ("iter", "getitem", "pathlight"):
                with self.subTest(validator=validator.__name__, fail_at=fail_at):
                    with self.assertRaises(PathlightError) as raised:
                        validator(_HostileMapping(value.to_mapping(), fail_at))

                    self.assertPublicPathlightError(
                        raised.exception,
                        f"Pathlight {validator.__name__[9:].replace('_', ' ')} is invalid",
                    )

    def test_public_validators_reject_mismatched_supplied_identities(self) -> None:
        subject = SubjectRef("trace", _digest("trace"))
        dataset = DatasetSnapshot(
            _digest("dataset-contract"), _digest("dataset-content"), 1, "1.0.0"
        )
        evaluator = EvaluatorContract(
            _digest("metric"), "rule", _digest("implementation"), _digest("input"),
            _digest("output"), _digest("failure"), "1.0.0",
        )
        variant = Variant(*(_digest(name) for name in (
            "assembly", "packages", "implementation", "runtime", "model", "tools",
            "prompt", "policy", "change",
        )))
        plan = ExperimentPlan(
            dataset.dataset_snapshot_sha256, _digest("scope"), variant.variant_sha256, (),
            _digest("assignment"), (evaluator.evaluator_contract_sha256,),
            _digest("budget"), _digest("stop"),
        )
        trial = CaseTrial(
            plan.experiment_plan_sha256, _digest("case"), variant.variant_sha256,
            _digest("trace"), (), "observed", (),
        )
        cases = (
            (
                validate_subject_ref,
                subject,
                "subject_ref_sha256",
                "Pathlight subject ref is invalid",
            ),
            (
                validate_dataset_snapshot,
                dataset,
                "dataset_snapshot_sha256",
                "Pathlight dataset snapshot is invalid",
            ),
            (
                validate_evaluator_contract,
                evaluator,
                "evaluator_contract_sha256",
                "Pathlight evaluator contract is invalid",
            ),
            (validate_variant, variant, "variant_sha256", "Pathlight variant is invalid"),
            (
                validate_experiment_plan,
                plan,
                "experiment_plan_sha256",
                "Pathlight experiment plan is invalid",
            ),
            (
                validate_case_trial,
                trial,
                "case_trial_sha256",
                "Pathlight case trial is invalid",
            ),
        )

        for validator, value, identity_field, message in cases:
            with self.subTest(validator=validator.__name__):
                mapping = value.to_mapping()
                mapping[identity_field] = _digest(
                    f"{_HOSTILE_SENTINEL}-{identity_field}-mismatch"
                )
                with self.assertRaises(PathlightError) as raised:
                    validator(mapping)

                self.assertPublicPathlightError(raised.exception, message)

    def test_every_identity_input_changes_its_enclosing_content_address(self) -> None:
        subject = SubjectRef("trace", _digest("subject"))
        dataset = DatasetSnapshot(
            _digest("dataset-contract"), _digest("dataset-content"), 1, "1.0.0",
            _digest("parent-snapshot"),
        )
        evaluator = EvaluatorContract(
            _digest("metric"), "judge", _digest("evaluator-implementation"),
            _digest("evaluator-input"), _digest("evaluator-output"),
            _digest("evaluator-failure"), "1.0.0",
        )
        variant = Variant(*(_digest(name) for name in (
            "assembly", "package-set", "implementation", "runtime", "model", "toolset",
            "prompt-contract", "policy", "change",
        )))
        plan = ExperimentPlan(
            dataset.dataset_snapshot_sha256, _digest("scope"), variant.variant_sha256,
            (_digest("candidate"),), _digest("assignment"),
            (evaluator.evaluator_contract_sha256,), _digest("budget"),
            _digest("stop-criteria"), _digest("authorization"),
        )
        trial = CaseTrial(
            plan.experiment_plan_sha256, _digest("dataset-item"), variant.variant_sha256,
            _digest("trace"), (_digest("evaluation"),), "recovered", (),
        )
        alternative_values: dict[tuple[str, str], object] = {
            ("SubjectRef", "subject_kind"): "span",
            ("DatasetSnapshot", "total_count"): 2,
            ("DatasetSnapshot", "snapshot_version"): "1.0.1",
            ("EvaluatorContract", "evaluator_kind"): "human",
            ("EvaluatorContract", "contract_version"): "1.0.1",
            ("CaseTrial", "evidence_state"): "observed",
            ("CaseTrial", "missing_evidence"): ("context-frames",),
        }
        matrices: tuple[tuple[Any, str, tuple[str, ...]], ...] = (
            (subject, "subject_ref_sha256", ("subject_sha256", "subject_kind")),
            (
                dataset,
                "dataset_snapshot_sha256",
                (
                    "dataset_contract_sha256",
                    "content_sha256",
                    "parent_snapshot_sha256",
                    "total_count",
                    "snapshot_version",
                ),
            ),
            (
                evaluator,
                "evaluator_contract_sha256",
                (
                    "metric_contract_sha256",
                    "implementation_sha256",
                    "input_contract_sha256",
                    "output_contract_sha256",
                    "failure_semantics_sha256",
                    "evaluator_kind",
                    "contract_version",
                ),
            ),
            (
                variant,
                "variant_sha256",
                (
                    "assembly_sha256",
                    "package_set_sha256",
                    "implementation_sha256",
                    "runtime_sha256",
                    "model_sha256",
                    "toolset_sha256",
                    "prompt_contract_sha256",
                    "policy_sha256",
                    "change_sha256",
                ),
            ),
            (
                plan,
                "experiment_plan_sha256",
                (
                    "dataset_snapshot_sha256",
                    "scope_sha256",
                    "baseline_variant_sha256",
                    "candidate_variant_sha256s",
                    "assignment_sha256",
                    "evaluator_contract_sha256s",
                    "budget_sha256",
                    "stop_criteria_sha256",
                    "authorization_sha256",
                ),
            ),
            (
                trial,
                "case_trial_sha256",
                (
                    "experiment_plan_sha256",
                    "dataset_item_sha256",
                    "variant_sha256",
                    "trace_sha256",
                    "evaluation_sha256s",
                    "evidence_state",
                    "missing_evidence",
                ),
            ),
        )

        for value, identity_field, input_fields in matrices:
            for input_field in input_fields:
                with self.subTest(type=type(value).__name__, field=input_field):
                    current = getattr(value, input_field)
                    alternative_key = (type(value).__name__, input_field)
                    if alternative_key in alternative_values:
                        replacement = alternative_values[alternative_key]
                    else:
                        replacement = (
                            (_digest(f"changed-{input_field}"),)
                            if type(current) is tuple
                            else _digest(f"changed-{input_field}")
                        )
                    mutated = replace(value, **{input_field: replacement})

                    self.assertNotEqual(
                        getattr(mutated, identity_field), getattr(value, identity_field)
                    )


if __name__ == "__main__":
    unittest.main()
