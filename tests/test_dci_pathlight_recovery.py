"""Regression tests for field-allowlisted DCI run recovery."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from asterion.capabilities.dci.implementation.pathlight.recovery import (
    DciRecoveryError,
    read_completed_dci_run,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "dci" / "pathlight-recovery"
_FILES = ("config.json", "batch-state.json", "summary.json", "analysis.json", "results.jsonl")
_RAW_64_HEX_SECRET = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
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
    _RAW_64_HEX_SECRET,
)
_VARIANT_SOURCES = (
    ("runtime_contract",),
    ("runtime", "model"),
    ("runtime", "tools"),
    ("benchmark_prompt_contract_sha256",),
    ("context_contract",),
    ("ranking_metric_contract",),
    ("implementation_sha256",),
    ("profile_sha256",),
    ("product_effective_config_sha256",),
)


@contextmanager
def private_fixture() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve() / "evidence"
        shutil.copytree(FIXTURE_ROOT, root)
        root.chmod(0o700)
        for name in _FILES:
            (root / name).chmod(0o600)
        _refresh_config_digests(root)
        yield root


def _load(root: Path, name: str) -> dict[str, object]:
    return json.loads((root / name).read_text(encoding="utf-8"))


def _write(root: Path, name: str, value: object) -> None:
    path = root / name
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def _refresh_config_digests(root: Path) -> None:
    config = _load(root, "config.json")
    digests = config["artifact_digests"]
    assert type(digests) is dict
    for name in ("summary.json", "results.jsonl"):
        digests[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    _write(root, "config.json", config)


def _write_results(root: Path, rows: list[dict[str, object]]) -> None:
    path = root / "results.jsonl"
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    path.chmod(0o600)


class TestDciPathlightRecovery(unittest.TestCase):
    def assert_recovery_error(self, root: Path, expected_dataset_id: str = "bright.biology") -> None:
        with self.assertRaises(DciRecoveryError) as raised:
            read_completed_dci_run(root.absolute(), expected_dataset_id=expected_dataset_id)
        self.assertEqual(str(raised.exception), "DCI recovery evidence is invalid")
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        error_closure = repr((raised.exception, raised.exception.__cause__, raised.exception.__context__))
        for secret in _SENTINELS:
            self.assertNotIn(secret, error_closure)

    def test_reader_projects_only_allowlisted_numeric_case_evidence(self) -> None:
        with private_fixture() as root:
            recovered = read_completed_dci_run(root.absolute(), expected_dataset_id="bright.biology")

        public = json.dumps(recovered.to_mapping(), sort_keys=True)
        for secret in _SENTINELS:
            self.assertNotIn(secret, public)
        opaque_variant_digests = (
            recovered.variant.runtime_contract_sha256,
            recovered.variant.model_sha256,
            recovered.variant.toolset_sha256,
            recovered.variant.context_contract_sha256,
            recovered.variant.metric_contract_sha256,
        )
        self.assertNotIn(_RAW_64_HEX_SECRET, opaque_variant_digests)
        self.assertEqual(len(set(opaque_variant_digests)), len(opaque_variant_digests))
        self.assertEqual(len(recovered.cases), 2)
        self.assertRegex(recovered.cases[0].dataset_item_sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(
            (recovered.cases[0].read_call_count, recovered.cases[0].grep_call_count),
            (0, 0),
        )
        self.assertEqual(recovered.metric_value_microunits, 750_000)
        self.assertEqual(recovered.missing_evidence, ("sealed-analysis-digest", "sealed-config-digest"))

    def test_reader_recovers_qa_accuracy_with_boolean_metric_only(self) -> None:
        with private_fixture() as root:
            config = _load(root, "config.json")
            config["mode"] = "qa"
            _write(root, "config.json", config)
            summary = _load(root, "summary.json")
            summary.pop("ndcg_at_10")
            summary["accuracy"] = {"over_total": 0.5}
            _write(root, "summary.json", summary)
            analysis = _load(root, "analysis.json")
            metrics = analysis["per_query_metrics"]
            assert type(metrics) is list
            for index, row in enumerate(metrics):
                assert type(row) is dict
                row.pop("ndcg_at_10")
                row["is_correct"] = index == 1
            _write(root, "analysis.json", analysis)
            results = [json.loads(line) for line in (root / "results.jsonl").read_text(encoding="utf-8").splitlines()]
            assert all(type(row) is dict for row in results)
            for row in results:
                row["mode"] = "qa"
            _write_results(root, results)
            _refresh_config_digests(root)
            recovered = read_completed_dci_run(root.absolute(), expected_dataset_id="bright.biology")

        self.assertEqual(recovered.metric_name, "accuracy")
        self.assertEqual(recovered.metric_value_microunits, 500_000)

    def test_reader_rejects_missing_and_wrong_type_variant_sources(self) -> None:
        for path in _VARIANT_SOURCES:
            for mutation in ("missing", "wrong-type"):
                with self.subTest(path=path, mutation=mutation), private_fixture() as root:
                    config = _load(root, "config.json")
                    owner = config
                    for component in path[:-1]:
                        value = owner[component]
                        assert type(value) is dict
                        owner = value
                    if mutation == "missing":
                        owner.pop(path[-1])
                    else:
                        owner[path[-1]] = ["SENTINEL_PRIVATE_CONFIG_VALUE"]
                    _write(root, "config.json", config)
                    self.assert_recovery_error(root)

    def test_reader_requires_exact_selected_rows_semantics(self) -> None:
        for mutation in ("missing", "wrong-type", "mismatch", "invented-legacy-field"):
            with self.subTest(mutation=mutation), private_fixture() as root:
                config = _load(root, "config.json")
                selection = config["selection"]
                assert type(selection) is dict
                if mutation == "missing":
                    selection.pop("selected_rows")
                elif mutation == "wrong-type":
                    selection["selected_rows"] = "2"
                elif mutation == "mismatch":
                    selection["selected_rows"] = 3
                else:
                    selection.pop("selected_rows")
                    selection["selected_count"] = 2
                    selection["total_count"] = 2
                _write(root, "config.json", config)
                self.assert_recovery_error(root)

    def test_reader_rejects_count_aliases_by_exact_document_schema(self) -> None:
        for document, mutation in (
            ("batch-state.json", "both-equal"),
            ("batch-state.json", "both-contradictory"),
            ("batch-state.json", "wrong-only"),
            ("summary.json", "both-equal"),
            ("summary.json", "both-contradictory"),
            ("summary.json", "wrong-only"),
        ):
            with self.subTest(document=document, mutation=mutation), private_fixture() as root:
                value = _load(root, document)
                counts = value["counts"]
                assert type(counts) is dict
                required = "failed" if document == "batch-state.json" else "failed_runs"
                alias = "failed_runs" if required == "failed" else "failed"
                if mutation == "wrong-only":
                    counts.pop(required)
                    counts[alias] = 0
                else:
                    counts[alias] = 0 if mutation == "both-equal" else 1
                _write(root, document, value)
                if document == "summary.json":
                    _refresh_config_digests(root)
                self.assert_recovery_error(root)

    def test_reader_normalizes_deep_json_recursion_without_context(self) -> None:
        with private_fixture() as root:
            path = root / "config.json"
            path.write_bytes(b"[" * 100_000 + b'"SENTINEL_DEEP_JSON"' + b"]" * 100_000)
            path.chmod(0o600)
            self.assert_recovery_error(root)

    def test_reader_rejects_symlinks_tampering_count_mismatch_and_hostile_types(self) -> None:
        cases = (
            "ancestor-symlink", "final-symlink", "digest-mismatch", "duplicate-query-id",
            "count-mismatch", "aggregate-mismatch", "wrong-dataset", "incomplete-batch",
            "nan-number", "boolean-number", "unknown-tool",
            "oversized-analysis",
        )
        for case in cases:
            with self.subTest(case=case), private_fixture() as root:
                if case == "ancestor-symlink":
                    target = root.parent / "target"
                    root.rename(target)
                    root.symlink_to(target, target_is_directory=True)
                elif case == "final-symlink":
                    target = root / "target.json"
                    target.write_text("{}", encoding="utf-8")
                    target.chmod(0o600)
                    (root / "analysis.json").unlink()
                    (root / "analysis.json").symlink_to(target)
                elif case == "digest-mismatch":
                    config = _load(root, "config.json")
                    digests = config["artifact_digests"]
                    assert type(digests) is dict
                    digests["summary.json"] = "0" * 64
                    _write(root, "config.json", config)
                elif case == "duplicate-query-id":
                    analysis = _load(root, "analysis.json")
                    rows = analysis["per_query_metrics"]
                    assert type(rows) is list and type(rows[1]) is dict
                    rows[1]["query_id"] = "q-001"
                    _write(root, "analysis.json", analysis)
                elif case == "count-mismatch":
                    summary = _load(root, "summary.json")
                    counts = summary["counts"]
                    assert type(counts) is dict
                    counts["total"] = 3
                    _write(root, "summary.json", summary)
                    _refresh_config_digests(root)
                elif case == "aggregate-mismatch":
                    summary = _load(root, "summary.json")
                    summary["ndcg_at_10"] = 0.1
                    _write(root, "summary.json", summary)
                    _refresh_config_digests(root)
                elif case == "wrong-dataset":
                    self.assert_recovery_error(root, expected_dataset_id="bright.robotics")
                    continue
                elif case == "incomplete-batch":
                    state = _load(root, "batch-state.json")
                    state["status"] = "running"
                    _write(root, "batch-state.json", state)
                elif case in {"nan-number", "boolean-number"}:
                    analysis = _load(root, "analysis.json")
                    rows = analysis["per_query_metrics"]
                    assert type(rows) is list and type(rows[0]) is dict
                    rows[0]["wall_time_seconds"] = float("nan") if case == "nan-number" else True
                    _write(root, "analysis.json", analysis)
                elif case == "oversized-analysis":
                    (root / "analysis.json").write_bytes(b"x" * ((1 << 20) + 1))
                    (root / "analysis.json").chmod(0o600)
                else:
                    analysis = _load(root, "analysis.json")
                    rows = analysis["per_query_metrics"]
                    assert type(rows) is list and type(rows[0]) is dict
                    rows[0]["tool_counts"] = {"shell": 1}
                    _write(root, "analysis.json", analysis)
                self.assert_recovery_error(root)


if __name__ == "__main__":
    unittest.main()
