from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from collections.abc import ItemsView, Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from asterion.pathlight import PathlightError
from asterion.pathlight.evaluation import (
    EvaluationBundle,
    EvaluationRecord,
    MetricContract,
    compare_evaluations,
    read_evaluation_bundle,
    validate_evaluation_record,
    validate_metric_contract,
    write_evaluation_bundle as _write_evaluation_bundle,
)


_HOSTILE_SENTINEL = "SENTINEL_PRIVATE_PATHLIGHT_EVALUATION"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _contract() -> MetricContract:
    return MetricContract("accuracy", "ratio", True, "1.0.0")


def write_evaluation_bundle(path: Path, records: tuple[EvaluationRecord, ...]) -> None:
    _write_evaluation_bundle(path, records, (_contract(),))


def evaluation(
    *,
    trace: str = "trace",
    contract: MetricContract | None = None,
    snapshot: str = "dataset",
    scope: str = "scope",
    value_microunits: int | None = 771_000,
    selected_count: int = 2,
    total_count: int = 3,
    status: str = "observed",
) -> EvaluationRecord:
    return EvaluationRecord(
        trace_sha256=_digest(trace),
        metric_contract_sha256=(contract or _contract()).metric_contract_sha256,
        dataset_snapshot_sha256=_digest(snapshot),
        scope_sha256=_digest(scope),
        value_microunits=value_microunits,
        selected_count=selected_count,
        total_count=total_count,
        status=status,  # type: ignore[arg-type]
    )


def _rehash(document: dict[str, object]) -> None:
    document["bundle_sha256"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in document.items() if key != "bundle_sha256"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


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


class _HostileMetricContract(MetricContract):
    def to_mapping(self) -> dict[str, object]:
        raise RuntimeError(f"{_HOSTILE_SENTINEL}: metric contract")


class _HostileEvaluationRecord(EvaluationRecord):
    def to_mapping(self) -> dict[str, object]:
        raise RuntimeError(f"{_HOSTILE_SENTINEL}: evaluation record")


class PathlightEvaluationTests(unittest.TestCase):
    def assertPublicPathlightError(self, error: PathlightError, message: str) -> None:
        self.assertEqual(str(error), message)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertNotIn(_HOSTILE_SENTINEL, repr(error))

    def test_metric_contract_has_a_computed_canonical_digest(self) -> None:
        contract = _contract()

        self.assertEqual(
            contract.metric_contract_sha256,
            hashlib.sha256(
                json.dumps(
                    {
                        "metric_name": "accuracy",
                        "unit": "ratio",
                        "higher_is_better": True,
                        "contract_version": "1.0.0",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )
        with self.assertRaises((AttributeError, TypeError)):
            contract.metric_name = "coverage"  # type: ignore[misc]

    def test_record_has_a_computed_canonical_digest_and_exact_mapping(self) -> None:
        record = evaluation()
        mapping = record.to_mapping()

        self.assertEqual(validate_evaluation_record(mapping), record)
        self.assertEqual(mapping["evaluation_sha256"], record.evaluation_sha256)
        for field, value in {
            "unknown": "private payload",
            "trace_sha256": "sentinel-private-content",
            "evaluation_sha256": "0" * 64,
        }.items():
            with self.subTest(field=field):
                mutated = dict(mapping)
                mutated[field] = value
                with self.assertRaises(PathlightError):
                    validate_evaluation_record(mutated)

    def test_public_validators_normalize_hostile_mapping_failures(self) -> None:
        contract = _contract()
        record = evaluation(contract=contract)
        cases = (
            (
                validate_metric_contract,
                contract.to_mapping(),
                "Pathlight metric contract is invalid",
            ),
            (
                validate_evaluation_record,
                record.to_mapping(),
                "Pathlight evaluation record is invalid",
            ),
        )

        for validator, payload, message in cases:
            for fail_at in ("iter", "getitem", "pathlight"):
                with self.subTest(validator=validator.__name__, fail_at=fail_at):
                    hostile = _HostileMapping(payload, fail_at)
                    with self.assertRaises(PathlightError) as raised:
                        validator(hostile)

                    self.assertPublicPathlightError(raised.exception, message)

    def test_rejects_invalid_contract_and_record_values(self) -> None:
        for args in (
            ("not-a-metric", "ratio", True, "1.0.0"),
            ("accuracy", "private-unit", True, "1.0.0"),
            ("accuracy", "ratio", 1, "1.0.0"),
            ("accuracy", "ratio", True, "1.0"),
        ):
            with self.subTest(contract=args), self.assertRaises(PathlightError):
                MetricContract(*args)  # type: ignore[arg-type]
        for field, value in {
            "selected_count": True,
            "total_count": -1,
            "value_microunits": True,
            "status": "private-value",
        }.items():
            with self.subTest(field=field), self.assertRaises(PathlightError):
                evaluation(**{field: value})  # type: ignore[arg-type]
        with self.assertRaises(PathlightError):
            evaluation(selected_count=4, total_count=3)
        with self.assertRaises(PathlightError):
            evaluation(status="missing", value_microunits=0)
        with self.assertRaises(PathlightError):
            evaluation(status="recovered", value_microunits=None)

    def test_rejects_nonstring_contract_and_status_values_without_type_errors(self) -> None:
        for field, values in {
            "metric_name": ([], {}),
            "unit": ([], {}),
        }.items():
            for value in values:
                with self.subTest(field=field, value=type(value).__name__), self.assertRaises(
                    PathlightError
                ):
                    arguments: dict[str, object] = {
                        "metric_name": "accuracy",
                        "unit": "ratio",
                        "higher_is_better": True,
                        "contract_version": "1.0.0",
                    }
                    arguments[field] = value
                    MetricContract(**arguments)  # type: ignore[arg-type]
        for value in ([], {}):
            with self.subTest(field="status", value=type(value).__name__), self.assertRaises(
                PathlightError
            ):
                evaluation(status=value)  # type: ignore[arg-type]

    def test_reader_normalizes_nonstring_status_json_values(self) -> None:
        record = evaluation()
        for value in ([], {}):
            with self.subTest(value=type(value).__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory).resolve() / "pathlight-evaluations.json"
                write_evaluation_bundle(path, (record,))
                document = json.loads(path.read_text(encoding="utf-8"))
                document["evaluations"][0]["status"] = value
                document["evaluations"][0]["evaluation_sha256"] = _digest("changed")
                _rehash(document)
                path.write_text(json.dumps(document), encoding="utf-8")

                with self.assertRaises(PathlightError):
                    read_evaluation_bundle(path)

    def test_compares_only_same_contract_snapshot_scope_and_coverage(self) -> None:
        baseline = evaluation(value_microunits=771_000)
        candidate = evaluation(trace="candidate", value_microunits=445_600)

        comparison = compare_evaluations(baseline, candidate)

        self.assertEqual(comparison.status, "comparable")
        self.assertEqual(comparison.delta_microunits, -325_400)
        self.assertEqual(comparison.reasons, ())

    def test_rejects_every_incompatible_dimension(self) -> None:
        base = evaluation()
        changed = {
            "metric_contract_sha256": _digest("other-contract"),
            "dataset_snapshot_sha256": _digest("other-dataset"),
            "scope_sha256": _digest("other-scope"),
            "selected_count": 1,
            "total_count": 4,
        }
        for field, value in changed.items():
            with self.subTest(field=field):
                comparison = compare_evaluations(base, replace(base, **{field: value}))
                self.assertEqual(comparison.status, "not-comparable")
                self.assertIsNone(comparison.delta_microunits)
                self.assertEqual(comparison.reasons, (field,))

    def test_missing_value_has_an_exact_noncomparability_reason(self) -> None:
        comparison = compare_evaluations(
            evaluation(status="missing", value_microunits=None), evaluation(trace="candidate")
        )

        self.assertEqual(comparison.status, "not-comparable")
        self.assertEqual(comparison.reasons, ("baseline.value_microunits",))

    def test_writes_and_reads_immutable_canonical_bundle(self) -> None:
        first = evaluation(trace="first")
        second = evaluation(trace="second")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-evaluations.json"
            write_evaluation_bundle(path, (second, first))

            payload = json.loads(path.read_text(encoding="utf-8"))
            bundle = read_evaluation_bundle(path)

            self.assertEqual(payload["schema"], "asterion.pathlight-evaluations/v1")
            self.assertEqual(
                [item["evaluation_sha256"] for item in payload["evaluations"]],
                sorted((first.evaluation_sha256, second.evaluation_sha256)),
            )
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertIsInstance(bundle, EvaluationBundle)
            self.assertEqual(bundle.evaluations, tuple(sorted((first, second), key=lambda item: item.evaluation_sha256)))
            with self.assertRaises((AttributeError, TypeError)):
                bundle.evaluations[0].status = "missing"  # type: ignore[misc]

    def test_writer_forces_mode_0600_under_restrictive_umask(self) -> None:
        record = evaluation()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-evaluations.json"
            previous_umask = os.umask(0o777)
            try:
                write_evaluation_bundle(path, (record,))
            finally:
                os.umask(previous_umask)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_writer_retains_invalid_private_output_when_mode_cannot_be_set(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-evaluations.json"
            with patch(
                "asterion.pathlight.evaluation.os.fchmod", side_effect=OSError("blocked")
            ), self.assertRaises(PathlightError):
                write_evaluation_bundle(path, (evaluation(),))

            self.assertTrue(path.exists())
            with self.assertRaises(PathlightError):
                read_evaluation_bundle(path)

    def test_writer_never_unlinks_a_replacement_after_a_mode_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "pathlight-evaluations.json"
            partial = root / "partial.json"
            replacement = root / "replacement.json"
            replacement.write_text("replacement", encoding="utf-8")

            def replace_then_fail(descriptor: int, mode: int) -> None:
                del descriptor, mode
                path.rename(partial)
                replacement.rename(path)
                raise OSError("blocked")

            with patch(
                "asterion.pathlight.evaluation.os.fchmod", side_effect=replace_then_fail
            ), patch("asterion.pathlight.evaluation.os.unlink") as unlink, self.assertRaises(
                PathlightError
            ):
                write_evaluation_bundle(path, (evaluation(),))

            unlink.assert_not_called()
            self.assertEqual(path.read_text(encoding="utf-8"), "replacement")

    def test_writer_normalizes_close_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-evaluations.json"
            original_close = os.close

            def close_then_fail(descriptor: int) -> None:
                original_close(descriptor)
                raise OSError("close failed")

            with patch(
                "asterion.pathlight.evaluation.os.close", side_effect=close_then_fail
            ), self.assertRaises(PathlightError):
                write_evaluation_bundle(path, (evaluation(),))

    def test_partial_write_remains_private_and_is_rejected_by_reader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-evaluations.json"
            original_write = os.write

            def write_partial_then_fail(descriptor: int, data: bytes) -> int:
                original_write(descriptor, data[:1])
                raise OSError("write failed")

            with patch(
                "asterion.pathlight.evaluation.os.write", side_effect=write_partial_then_fail
            ), self.assertRaises(PathlightError):
                write_evaluation_bundle(path, (evaluation(),))

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(PathlightError):
                read_evaluation_bundle(path)

    def test_bundle_rejects_a_noncanonical_digest(self) -> None:
        record = evaluation()

        with self.assertRaises(PathlightError):
            EvaluationBundle((_contract(),), (record,), "0" * 64)

    def test_bundle_normalizes_hostile_value_subclasses(self) -> None:
        contract = _contract()
        record = evaluation(contract=contract)
        bundle_digest = hashlib.sha256(
            json.dumps(
                {
                    "schema": "asterion.pathlight-evaluations/v1",
                    "metric_contracts": [contract.to_mapping()],
                    "evaluations": [record.to_mapping()],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        cases = (
            (
                (_HostileMetricContract("accuracy", "ratio", True, "1.0.0"),),
                (record,),
                "Pathlight evaluation bundle contracts are invalid",
            ),
            (
                (contract,),
                (
                    _HostileEvaluationRecord(
                        trace_sha256=record.trace_sha256,
                        metric_contract_sha256=record.metric_contract_sha256,
                        dataset_snapshot_sha256=record.dataset_snapshot_sha256,
                        scope_sha256=record.scope_sha256,
                        value_microunits=record.value_microunits,
                        selected_count=record.selected_count,
                        total_count=record.total_count,
                        status=record.status,
                    ),
                ),
                "Pathlight evaluation bundle is invalid",
            ),
        )

        for contracts, records, message in cases:
            with self.subTest(message=message):
                with self.assertRaises(PathlightError) as raised:
                    EvaluationBundle(contracts, records, bundle_digest)

                self.assertPublicPathlightError(raised.exception, message)

    def test_bundle_carries_contract_registry_and_requires_exact_record_binding(self) -> None:
        contract = _contract()
        record = evaluation(contract=contract)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "pathlight-evaluations.json"
            _write_evaluation_bundle(path, (record,), (contract,))
            bundle = read_evaluation_bundle(path)

        self.assertEqual(bundle.metric_contracts, (contract,))
        with self.assertRaises(PathlightError):
            EvaluationBundle((), (record,), bundle.bundle_sha256)

    def test_bundle_revalidates_tampered_metric_contract_identity(self) -> None:
        contract = _contract()
        record = evaluation(contract=contract)
        object.__setattr__(contract, "metric_name", "coverage")
        bundle_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "schema": "asterion.pathlight-evaluations/v1",
                    "metric_contracts": [contract.to_mapping()],
                    "evaluations": [record.to_mapping()],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        with self.assertRaises(PathlightError):
            EvaluationBundle((contract,), (record,), bundle_sha256)

    def test_bundle_revalidates_tampered_evaluation_identity(self) -> None:
        contract = _contract()
        record = evaluation(contract=contract)
        object.__setattr__(record, "value_microunits", 1)
        bundle_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "schema": "asterion.pathlight-evaluations/v1",
                    "metric_contracts": [contract.to_mapping()],
                    "evaluations": [record.to_mapping()],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        with self.assertRaises(PathlightError):
            EvaluationBundle((contract,), (record,), bundle_sha256)

    def test_bundle_rejects_duplicates_tampering_and_unsafe_paths(self) -> None:
        record = evaluation()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "pathlight-evaluations.json"
            with self.assertRaises(PathlightError):
                write_evaluation_bundle(path, (record, record))
            self.assertFalse(path.exists())
            write_evaluation_bundle(path, (record,))
            with self.assertRaises(PathlightError):
                write_evaluation_bundle(path, (record,))
            document = json.loads(path.read_text(encoding="utf-8"))
            document["evaluations"].append(document["evaluations"][0])
            _rehash(document)
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(PathlightError):
                read_evaluation_bundle(path)

    def test_reader_rejects_symlink_ancestor_and_final_replacement(self) -> None:
        record = evaluation()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "target"
            target.mkdir()
            write_evaluation_bundle(target / "pathlight-evaluations.json", (record,))
            (root / "ancestor").symlink_to(target, target_is_directory=True)
            with self.assertRaises(PathlightError):
                read_evaluation_bundle(root / "ancestor" / "pathlight-evaluations.json")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "pathlight-evaluations.json"
            replacement = root / "replacement.json"
            write_evaluation_bundle(path, (record,))
            replacement.write_bytes(path.read_bytes())
            original_open = os.open

            def replace_before_final_open(
                name: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                if name == "pathlight-evaluations.json" and dir_fd is not None:
                    path.rename(root / "original.json")
                    path.symlink_to(replacement)
                return original_open(name, flags, mode, dir_fd=dir_fd)

            with patch(
                "asterion.pathlight.evaluation.os.open", side_effect=replace_before_final_open
            ), self.assertRaises(PathlightError):
                read_evaluation_bundle(path)


if __name__ == "__main__":
    unittest.main()
