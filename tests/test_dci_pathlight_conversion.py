"""Conversion of recovered DCI evidence into public-safe Pathlight records."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import ClassVar, Iterator
from unittest.mock import patch

from asterion.capabilities.dci.implementation.pathlight.conversion import (
    DciConversionError,
    load_paper_reference,
    recovered_run_to_evaluation_bundle,
    recovered_run_to_experiment,
)
from asterion.capabilities.dci.implementation.pathlight.recovery import (
    DciRecoveredCase,
    DciRecoveredRun,
    DciRecoveredVariant,
    read_completed_dci_run,
)
from asterion.pathlight.experiment import validate_experiment_bundle


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "dci" / "pathlight-recovery"
_FILES = ("config.json", "batch-state.json", "summary.json", "analysis.json", "results.jsonl")
_SENTINELS = (
    "SENTINEL_PRIVATE_PATH",
    "SENTINEL_QUERY",
    "SENTINEL_ANSWER",
    "SENTINEL_FINAL",
    "SENTINEL_JUDGE_REASON",
    "SENTINEL_PRIVATE_DATASET_IDENTITY",
    "SENTINEL_PRIVATE_MODEL",
    "SENTINEL_PRIVATE_PROVIDER",
    "SENTINEL_PRIVATE_SELECTION_ID",
    "SENTINEL_PRIVATE_CONFIG_VALUE",
    "SENTINEL_DEEP_JSON",
    "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
)


class _RecoveredRunSubclass(DciRecoveredRun):
    pass


class _HostileRecoveredVariant(DciRecoveredVariant):
    method_called: ClassVar[bool] = False

    def to_mapping(self) -> dict[str, str]:
        type(self).method_called = True
        raise RuntimeError("SENTINEL_PRIVATE_CONFIG_VALUE")


class _HostileRecoveredCase(DciRecoveredCase):
    method_called: ClassVar[bool] = False

    def to_mapping(self) -> dict[str, object]:
        type(self).method_called = True
        raise RuntimeError("SENTINEL_PRIVATE_CONFIG_VALUE")


@contextmanager
def recovered_fixture() -> Iterator[DciRecoveredRun]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve() / "evidence"
        shutil.copytree(FIXTURE_ROOT, root)
        root.chmod(0o700)
        for name in _FILES:
            (root / name).chmod(0o600)
        config_path = root / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        digests = config["artifact_digests"]
        assert type(digests) is dict
        for name in ("summary.json", "results.jsonl"):
            digests[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
        config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
        config_path.chmod(0o600)
        yield read_completed_dci_run(root, expected_dataset_id="bright.biology")


class TestDciPathlightConversion(unittest.TestCase):
    def setUp(self) -> None:
        self._fixture = recovered_fixture()
        self.recovered = self._fixture.__enter__()

    def tearDown(self) -> None:
        self._fixture.__exit__(None, None, None)

    def assert_conversion_error(self, callback: object) -> None:
        with self.assertRaises(DciConversionError) as raised:
            assert callable(callback)
            callback()
        self.assertEqual(str(raised.exception), "DCI Pathlight conversion is invalid")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        public = repr((raised.exception, raised.exception.__cause__, raised.exception.__context__))
        for sentinel in _SENTINELS:
            self.assertNotIn(sentinel, public)

    def test_resolves_exact_paper_references_without_copying_private_paths(self) -> None:
        expected = {
            "bright.biology": (771000, 103),
            "bright.earth-science": (690000, 116),
            "bright.economics": (468000, 103),
            "bright.robotics": (568000, 101),
            "beir.scifact": (757000, 300),
            "qa.bamboogle": (800000, 125),
        }
        for dataset_id, (score, count) in expected.items():
            with self.subTest(dataset_id=dataset_id):
                reference = load_paper_reference(dataset_id)
                self.assertEqual((reference.value_microunits, reference.total_count), (score, count))
                self.assertEqual(reference.comparison_status, "reference-only")
                self.assertEqual(reference.target_id, "paper.2605.05242v1/dci-agent-cc/main")
                self.assertRegex(reference.target_sha256, r"^[0-9a-f]{64}$")
                self.assertRegex(reference.provenance_sha256, r"^[0-9a-f]{64}$")
                self.assertFalse(hasattr(reference, "candidate_variant_sha256"))
                self.assertFalse(hasattr(reference, "exact_reproduction"))
                public = json.dumps(reference.to_mapping(), sort_keys=True)
                for sentinel in _SENTINELS:
                    self.assertNotIn(sentinel, public)

    def test_conversion_creates_one_trial_and_evaluation_per_case(self) -> None:
        bundle = recovered_run_to_experiment(self.recovered)
        self.assertEqual(len(bundle.trials), self.recovered.selected_count)
        self.assertEqual(len(bundle.evaluations), self.recovered.selected_count + 1)
        self.assertTrue(all(trial.evidence_state == "recovered" for trial in bundle.trials))
        self.assertEqual(len(bundle.datasets), 1)
        self.assertEqual(len(bundle.evaluators), 1)
        self.assertEqual(len(bundle.variants), 1)
        self.assertEqual(len(bundle.plans), 1)
        self.assertEqual(validate_experiment_bundle(bundle.to_mapping()), bundle)

        aggregate = next(
            evaluation
            for evaluation in bundle.evaluations
            if evaluation.selected_count == self.recovered.selected_count
            and evaluation.total_count == self.recovered.total_count
        )
        trial_evaluations = {
            evaluation_id
            for trial in bundle.trials
            for evaluation_id in trial.evaluation_sha256s
        }
        self.assertNotIn(aggregate.evaluation_sha256, trial_evaluations)
        self.assertEqual(
            aggregate.scope_sha256,
            _selected_item_set_scope(
                tuple(case.dataset_item_sha256 for case in self.recovered.cases)
            ),
        )
        self.assertEqual(len(trial_evaluations), self.recovered.selected_count)
        for trial in bundle.trials:
            self.assertEqual(len(trial.evaluation_sha256s), 1)
            evaluation = next(
                value for value in bundle.evaluations if value.evaluation_sha256 == trial.evaluation_sha256s[0]
            )
            self.assertEqual(evaluation.trace_sha256, trial.trace_sha256)
            self.assertEqual(evaluation.scope_sha256, _case_scope(trial.dataset_item_sha256))

    def test_evaluation_bundle_registers_exactly_the_experiment_metric_semantics(self) -> None:
        experiment = recovered_run_to_experiment(self.recovered)
        evaluations = recovered_run_to_evaluation_bundle(self.recovered)
        self.assertEqual(
            tuple(item.evaluation_sha256 for item in evaluations.evaluations),
            tuple(sorted(item.evaluation_sha256 for item in experiment.evaluations)),
        )
        self.assertEqual(len(evaluations.metric_contracts), 1)
        self.assertTrue(
            all(
                item.metric_contract_sha256
                == evaluations.metric_contracts[0].metric_contract_sha256
                for item in evaluations.evaluations
            )
        )

    def test_conversion_is_deterministic_for_direct_reversed_case_tuple(self) -> None:
        forward = recovered_run_to_experiment(self.recovered)
        reversed_run = replace(
            self.recovered, cases=tuple(reversed(self.recovered.cases))
        )
        self.assertEqual(
            reversed_run.recovered_run_sha256, self.recovered.recovered_run_sha256
        )
        reverse = recovered_run_to_experiment(reversed_run)
        self.assertEqual(forward.to_mapping(), reverse.to_mapping())
        self.assertEqual(forward.bundle_sha256, reverse.bundle_sha256)

    def test_conversion_marks_legacy_lineage_and_unavailable_retrieval_evidence(self) -> None:
        bundle = recovered_run_to_experiment(self.recovered)
        expected = {
            "assembly-lineage",
            "package-lineage",
            "trace-graph",
            *self.recovered.missing_evidence,
        }
        for trial in bundle.trials:
            with self.subTest(trial=trial.case_trial_sha256):
                self.assertTrue(expected.issubset(trial.missing_evidence))
                source = next(
                    case
                    for case in self.recovered.cases
                    if case.dataset_item_sha256 == trial.dataset_item_sha256
                )
                if source.resolution_status == "not-available":
                    self.assertIn("retrieval-coverage", trial.missing_evidence)
                self.assertEqual(trial.missing_evidence, tuple(sorted(trial.missing_evidence)))

        unavailable_case = replace(
            self.recovered.cases[0],
            resolution_status="not-available",
            resolution_coverage_microunits=None,
        )
        unavailable_run = replace(
            self.recovered,
            cases=(unavailable_case, *self.recovered.cases[1:]),
        )
        unavailable_bundle = recovered_run_to_experiment(unavailable_run)
        unavailable_trial = next(
            trial
            for trial in unavailable_bundle.trials
            if trial.dataset_item_sha256 == unavailable_case.dataset_item_sha256
        )
        self.assertIn("retrieval-coverage", unavailable_trial.missing_evidence)

    def test_conversion_uses_only_public_safe_recovery_projection(self) -> None:
        public = json.dumps(recovered_run_to_experiment(self.recovered).to_mapping(), sort_keys=True)
        for sentinel in _SENTINELS:
            self.assertNotIn(sentinel, public)

    def test_conversion_fails_closed_for_invalid_reference_and_recovery_contracts(self) -> None:
        changed_index = next(
            index
            for index, case in enumerate(self.recovered.cases)
            if case.metric_value_microunits < 1_000_000
        )
        changed_case = replace(
            self.recovered.cases[changed_index],
            metric_value_microunits=(
                self.recovered.cases[changed_index].metric_value_microunits + 1
            ),
        )
        changed_cases = list(self.recovered.cases)
        changed_cases[changed_index] = changed_case
        one_microunit_mutation = replace(
            self.recovered,
            cases=tuple(changed_cases),
        )
        self.assert_conversion_error(
            lambda: recovered_run_to_experiment(one_microunit_mutation)
        )
        invalid_metric = replace(self.recovered, metric_name="accuracy")
        self.assert_conversion_error(lambda: recovered_run_to_experiment(invalid_metric))
        self.assert_conversion_error(lambda: load_paper_reference("unknown.dataset"))
        with patch(
            "asterion.capabilities.dci.implementation.reproduction.reproduction._resource_mapping",
            return_value={"schema": "invalid", "targets": []},
        ):
            self.assert_conversion_error(lambda: load_paper_reference("bright.biology"))

    def test_conversion_rejects_forged_recovered_objects_and_hostile_serialization(self) -> None:
        mutations = (
            replace(self.recovered, metric_value_microunits=100_000),
            replace(self.recovered, recovered_run_sha256="0" * 64),
            replace(
                self.recovered,
                source_document_sha256s=(
                    self.recovered.source_document_sha256s[0],
                    self.recovered.source_document_sha256s[0],
                ),
            ),
            replace(self.recovered, missing_evidence=tuple(reversed(self.recovered.missing_evidence))),
            replace(
                self.recovered,
                cases=(
                    replace(self.recovered.cases[0], case_source_sha256="1" * 64),
                    *self.recovered.cases[1:],
                ),
            ),
            replace(
                self.recovered,
                cases=(
                    replace(self.recovered.cases[0], dataset_item_sha256="2" * 64),
                    *self.recovered.cases[1:],
                ),
            ),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assert_conversion_error(lambda mutation=mutation: recovered_run_to_experiment(mutation))

        subclass = _RecoveredRunSubclass(
            self.recovered.dataset_id,
            self.recovered.mode,
            self.recovered.metric_name,
            self.recovered.metric_value_microunits,
            self.recovered.selected_count,
            self.recovered.total_count,
            self.recovered.failed_count,
            self.recovered.corpus_file_count,
            self.recovered.dataset_snapshot_sha256,
            self.recovered.variant,
            self.recovered.cases,
            self.recovered.source_document_sha256s,
            self.recovered.missing_evidence,
            self.recovered.recovered_run_sha256,
        )
        self.assert_conversion_error(lambda: recovered_run_to_experiment(subclass))
        with patch.object(
            DciRecoveredRun,
            "to_mapping",
            side_effect=RuntimeError("SENTINEL_PRIVATE_CONFIG_VALUE"),
        ):
            self.assert_conversion_error(lambda: recovered_run_to_experiment(self.recovered))

    def test_conversion_rejects_nested_subclasses_before_calling_their_methods(self) -> None:
        hostile_variant = _HostileRecoveredVariant(
            **self.recovered.variant.to_mapping()
        )
        _HostileRecoveredVariant.method_called = False
        self.assert_conversion_error(
            lambda: recovered_run_to_experiment(
                replace(self.recovered, variant=hostile_variant)
            )
        )
        self.assertFalse(_HostileRecoveredVariant.method_called)

        case_values = self.recovered.cases[0].to_mapping()
        hostile_case = _HostileRecoveredCase(**case_values)  # type: ignore[arg-type]
        _HostileRecoveredCase.method_called = False
        self.assert_conversion_error(
            lambda: recovered_run_to_experiment(
                replace(
                    self.recovered,
                    cases=(hostile_case, *self.recovered.cases[1:]),
                )
            )
        )
        self.assertFalse(_HostileRecoveredCase.method_called)


def _case_scope(dataset_item_sha256: str) -> str:
    """The public domain-separated per-item scope identity."""

    return hashlib.sha256(
        json.dumps(
            {"domain": "asterion.dci.pathlight/case-scope/v1", "value": dataset_item_sha256},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _selected_item_set_scope(dataset_item_sha256s: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "domain": "asterion.dci.pathlight/selected-item-set/v1",
                "value": tuple(sorted(dataset_item_sha256s)),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
