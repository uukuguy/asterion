"""Field-allowlisted recovery of completed private DCI batch evidence."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Literal, Mapping, cast

from asterion.pathlight._private_file import (
    read_private_file,
    read_private_file_snapshot,
    write_private_file,
)


_FILES = ("config.json", "batch-state.json", "summary.json", "analysis.json", "results.jsonl")
_LIMITS = {name: 1 << 20 for name in _FILES}
DCI_RECOVERY_FILENAME = "pathlight-dci-recovery.json"
_MAX_RECOVERY_BYTES = 1 << 20
_HEX_SHA256 = frozenset("0123456789abcdef")
_MISSING_EVIDENCE = ("sealed-analysis-digest", "sealed-config-digest")
_LEGACY_MISSING_EVIDENCE = ("legacy-unsigned-artifacts", *_MISSING_EVIDENCE)
_RUN_FIELDS = frozenset(
    {
        "dataset_id",
        "mode",
        "metric_name",
        "metric_value_microunits",
        "selected_count",
        "total_count",
        "failed_count",
        "corpus_file_count",
        "dataset_snapshot_sha256",
        "variant",
        "cases",
        "source_document_sha256s",
        "missing_evidence",
        "recovered_run_sha256",
    }
)
_VARIANT_FIELDS = frozenset(
    {
        "runtime_contract_sha256",
        "model_sha256",
        "toolset_sha256",
        "prompt_contract_sha256",
        "context_contract_sha256",
        "metric_contract_sha256",
        "implementation_sha256",
        "profile_sha256",
        "policy_sha256",
    }
)
_CASE_FIELDS = frozenset(
    {
        "dataset_item_sha256",
        "metric_value_microunits",
        "run_status",
        "agent_total_tokens",
        "overall_cost_microusd",
        "wall_time_ns",
        "tool_time_ns",
        "tool_call_count",
        "tool_error_count",
        "read_call_count",
        "grep_call_count",
        "read_time_ns",
        "grep_time_ns",
        "question_word_count",
        "resolution_status",
        "resolution_coverage_microunits",
        "case_source_sha256",
    }
)


class DciRecoveryError(Exception):
    """A context-free DCI historical-evidence trust-boundary failure."""


@dataclass(frozen=True, slots=True)
class DciRecoveredCase:
    dataset_item_sha256: str
    metric_value_microunits: int
    run_status: Literal["completed", "failed"]
    agent_total_tokens: int
    overall_cost_microusd: int
    wall_time_ns: int
    tool_time_ns: int
    tool_call_count: int
    tool_error_count: int
    read_call_count: int
    grep_call_count: int
    read_time_ns: int
    grep_time_ns: int
    question_word_count: int
    resolution_status: Literal["available", "not-available"]
    resolution_coverage_microunits: int | None
    case_source_sha256: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "dataset_item_sha256": self.dataset_item_sha256,
            "metric_value_microunits": self.metric_value_microunits,
            "run_status": self.run_status,
            "agent_total_tokens": self.agent_total_tokens,
            "overall_cost_microusd": self.overall_cost_microusd,
            "wall_time_ns": self.wall_time_ns,
            "tool_time_ns": self.tool_time_ns,
            "tool_call_count": self.tool_call_count,
            "tool_error_count": self.tool_error_count,
            "read_call_count": self.read_call_count,
            "grep_call_count": self.grep_call_count,
            "read_time_ns": self.read_time_ns,
            "grep_time_ns": self.grep_time_ns,
            "question_word_count": self.question_word_count,
            "resolution_status": self.resolution_status,
            "resolution_coverage_microunits": self.resolution_coverage_microunits,
            "case_source_sha256": self.case_source_sha256,
        }


@dataclass(frozen=True, slots=True)
class DciRecoveredVariant:
    runtime_contract_sha256: str
    model_sha256: str
    toolset_sha256: str
    prompt_contract_sha256: str
    context_contract_sha256: str
    metric_contract_sha256: str
    implementation_sha256: str
    profile_sha256: str
    policy_sha256: str

    def to_mapping(self) -> dict[str, str]:
        return {
            "runtime_contract_sha256": self.runtime_contract_sha256,
            "model_sha256": self.model_sha256,
            "toolset_sha256": self.toolset_sha256,
            "prompt_contract_sha256": self.prompt_contract_sha256,
            "context_contract_sha256": self.context_contract_sha256,
            "metric_contract_sha256": self.metric_contract_sha256,
            "implementation_sha256": self.implementation_sha256,
            "profile_sha256": self.profile_sha256,
            "policy_sha256": self.policy_sha256,
        }


@dataclass(frozen=True, slots=True)
class DciRecoveredRun:
    dataset_id: str
    mode: Literal["ir", "qa"]
    metric_name: Literal["ndcg-at-10", "accuracy"]
    metric_value_microunits: int
    selected_count: int
    total_count: int
    failed_count: int
    corpus_file_count: int
    dataset_snapshot_sha256: str
    variant: DciRecoveredVariant
    cases: tuple[DciRecoveredCase, ...]
    source_document_sha256s: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    recovered_run_sha256: str

    def _unsigned_mapping(self) -> dict[str, object]:
        return _run_unsigned_mapping(
            self.dataset_id,
            self.mode,
            self.metric_name,
            self.metric_value_microunits,
            self.selected_count,
            self.total_count,
            self.failed_count,
            self.corpus_file_count,
            self.dataset_snapshot_sha256,
            self.variant,
            self.cases,
            self.source_document_sha256s,
            self.missing_evidence,
            canonicalize_cases=False,
        )

    def to_mapping(self) -> dict[str, object]:
        return {**self._unsigned_mapping(), "recovered_run_sha256": self.recovered_run_sha256}


def read_completed_dci_run(root: Path, expected_dataset_id: str) -> DciRecoveredRun:
    """Recover one completed DCI batch without retaining private source content."""

    recovered: DciRecoveredRun | None = None
    failed = False
    try:
        if not isinstance(root, Path) or not root.is_absolute() or type(expected_dataset_id) is not str or not expected_dataset_id:
            raise ValueError
        documents = dict(read_private_file_snapshot(root, _FILES, _LIMITS))
        config = _json_mapping(documents["config.json"])
        state = _json_mapping(documents["batch-state.json"])
        summary = _json_mapping(documents["summary.json"])
        analysis = _json_mapping(documents["analysis.json"])
        _validate_artifact_digests(config, documents)
        result_rows = _jsonl_mappings(documents["results.jsonl"])
        recovered = _recover(config, state, summary, analysis, result_rows, expected_dataset_id, documents)
    except Exception:
        failed = True
    if failed or recovered is None:
        raise DciRecoveryError("DCI recovery evidence is invalid")
    return recovered


def read_historical_dci_run(root: Path, expected_dataset_id: str) -> DciRecoveredRun:
    """Read a completed legacy batch for analysis, never for certification."""
    try:
        documents = dict(read_private_file_snapshot(root, _FILES, _LIMITS))
        return _recover(
            _json_mapping(documents["config.json"]),
            _json_mapping(documents["batch-state.json"]),
            _json_mapping(documents["summary.json"]),
            _json_mapping(documents["analysis.json"]),
            _jsonl_mappings(documents["results.jsonl"]),
            expected_dataset_id,
            documents,
            _LEGACY_MISSING_EVIDENCE,
            historical=True,
        )
    except Exception:
        raise DciRecoveryError("DCI historical evidence is invalid") from None


def validate_recovered_run(mapping: Mapping[str, object]) -> DciRecoveredRun:
    """Reconstruct one exact canonical recovered run and verify its content address."""

    recovered: DciRecoveredRun | None = None
    failed = False
    try:
        recovered = _validate_recovered_run_mapping(mapping)
    except Exception:
        failed = True
    if failed or recovered is None:
        raise DciRecoveryError("DCI recovery evidence is invalid")
    return recovered


def write_recovered_run(run: DciRecoveredRun, path: Path) -> None:
    """Exclusively persist one canonical recovered run as a private file."""

    encoded: bytes | None = None
    try:
        if type(run) is not DciRecoveredRun or not isinstance(path, Path) or path.name != DCI_RECOVERY_FILENAME:
            raise ValueError
        canonical = validate_recovered_run(run.to_mapping())
        encoded = _canonical_bytes(canonical.to_mapping())
    except Exception:
        pass
    if encoded is None:
        raise DciRecoveryError("DCI recovery evidence is invalid") from None
    try:
        write_private_file(path, encoded)
    except Exception:
        raise DciRecoveryError("DCI recovery evidence is invalid") from None


def read_recovered_run(path: Path) -> DciRecoveredRun:
    """Read and validate one canonical private recovered-run projection."""

    recovered: DciRecoveredRun | None = None
    try:
        if not isinstance(path, Path) or path.name != DCI_RECOVERY_FILENAME:
            raise ValueError
        encoded = read_private_file(path, _MAX_RECOVERY_BYTES)
        mapping = _json_mapping(encoded)
        recovered = validate_recovered_run(mapping)
        if not hmac.compare_digest(encoded, _canonical_bytes(recovered.to_mapping())):
            raise ValueError
    except Exception:
        pass
    if recovered is None:
        raise DciRecoveryError("DCI recovery evidence is invalid") from None
    return recovered


def _recover(
    config: Mapping[str, object],
    state: Mapping[str, object],
    summary: Mapping[str, object],
    analysis: Mapping[str, object],
    result_rows: tuple[Mapping[str, object], ...],
    expected_dataset_id: str,
    documents: Mapping[str, bytes],
    missing_evidence: tuple[str, ...] = _MISSING_EVIDENCE,
    *,
    historical: bool = False,
) -> DciRecoveredRun:
    dataset = _mapping(config.get("dataset"))
    dataset_id = expected_dataset_id if historical else _string(dataset.get("dataset_id"))
    if dataset_id != expected_dataset_id:
        raise ValueError
    mode = _mode(config.get("mode"))
    if state.get("status") != "completed":
        raise ValueError
    variant = _historical_variant(config, mode) if historical else _variant(config, mode)
    rows = analysis.get("per_query_metrics")
    if type(rows) is not list or not rows:
        raise ValueError
    cases = tuple((_historical_case(row, mode) if historical else _case(row, mode)) for row in rows)
    if len({case.dataset_item_sha256 for case in cases}) != len(cases):
        raise ValueError
    cases = tuple(sorted(cases, key=lambda case: case.dataset_item_sha256))
    _validate_result_rows(result_rows, cases, mode)
    selected_count = _selected_count(config)
    total_count, failed_count = _counts(state, summary)
    if selected_count != len(cases) or total_count != len(cases) or failed_count != sum(case.run_status == "failed" for case in cases):
        raise ValueError
    metric_name: Literal["ndcg-at-10", "accuracy"] = "ndcg-at-10" if mode == "ir" else "accuracy"
    metric_value = _summary_metric(summary, mode)
    _validate_aggregate_metric(metric_value, cases)
    corpus_file_count = (
        _historical_corpus_file_count(config)
        if historical
        else _natural(_mapping(config.get("corpus_content_identity")).get("file_count"))
    )
    dataset_snapshot_sha256 = _sha256(dataset.get("sha256"))
    source_document_sha256s = (_snapshot_digest(documents),)
    return _build_recovered_run(
        dataset_id,
        mode,
        metric_name,
        metric_value,
        selected_count,
        total_count,
        failed_count,
        corpus_file_count,
        dataset_snapshot_sha256,
        variant,
        cases,
        source_document_sha256s,
        missing_evidence,
    )


def _case(value: object, mode: Literal["ir", "qa"]) -> DciRecoveredCase:
    row = _mapping(value)
    query_id = _string(row.get("query_id"))
    dataset_item_sha256 = _domain_digest("query-id", query_id)
    status = row.get("run_status")
    if status not in {"completed", "failed"}:
        raise ValueError
    metric = _metric(row, mode)
    counts = _tool_naturals(row.get("tool_counts"))
    durations = _tool_durations(row.get("tool_durations"))
    tool_calls = _natural(row.get("tool_call_count"))
    tool_time = _scaled(row.get("tool_time_seconds"), Decimal("1000000000"))
    if tool_calls != counts["read"] + counts["grep"] or tool_time != durations["read"] + durations["grep"]:
        raise ValueError
    coverage = row.get("coverage_any")
    if coverage is not None and row.get("resolution_status") != "available":
        raise ValueError
    source = {
        "query_id": query_id,
        "metric": metric,
        "run_status": status,
        "agent_total_tokens": row.get("agent_total_tokens"),
        "overall_cost_total": row.get("overall_cost_total"),
        "wall_time_seconds": row.get("wall_time_seconds"),
        "tool_time_seconds": row.get("tool_time_seconds"),
        "tool_call_count": row.get("tool_call_count"),
        "tool_error_count": row.get("tool_error_count"),
        "tool_counts": row.get("tool_counts"),
        "tool_durations": row.get("tool_durations"),
        "question_word_count": row.get("question_word_count"),
        "resolution_status": row.get("resolution_status"),
        "coverage_any": coverage,
    }
    return DciRecoveredCase(
        dataset_item_sha256=dataset_item_sha256,
        metric_value_microunits=metric,
        run_status=cast(Literal["completed", "failed"], status),
        agent_total_tokens=_natural(row.get("agent_total_tokens")),
        overall_cost_microusd=_scaled(row.get("overall_cost_total"), Decimal("1000000")),
        wall_time_ns=_scaled(row.get("wall_time_seconds"), Decimal("1000000000")),
        tool_time_ns=tool_time,
        tool_call_count=tool_calls,
        tool_error_count=_natural(row.get("tool_error_count")),
        read_call_count=counts["read"],
        grep_call_count=counts["grep"],
        read_time_ns=durations["read"],
        grep_time_ns=durations["grep"],
        question_word_count=_natural(row.get("question_word_count")),
        resolution_status=_resolution_status(row.get("resolution_status")),
        resolution_coverage_microunits=None if coverage is None else _unit(coverage),
        case_source_sha256=_domain_digest("case-source", source),
    )


def _historical_case(value: object, mode: Literal["ir", "qa"]) -> DciRecoveredCase:
    """Preserve aggregate legacy tool use without pretending it used read/grep."""

    row = _mapping(value)
    query_id = _string(row.get("query_id"))
    status = row.get("run_status")
    if status not in {"completed", "failed"}:
        raise ValueError
    coverage = row.get("coverage_any")
    if coverage is not None and row.get("resolution_status") != "available":
        raise ValueError
    metric = _metric(row, mode)
    tool_calls = _natural(row.get("tool_call_count"))
    tool_time = _scaled(row.get("tool_time_seconds"), Decimal("1000000000"))
    source = {
        "query_id": query_id, "metric": metric, "run_status": status,
        "agent_total_tokens": row.get("agent_total_tokens"),
        "overall_cost_total": row.get("overall_cost_total"),
        "wall_time_seconds": row.get("wall_time_seconds"),
        "tool_time_seconds": row.get("tool_time_seconds"),
        "tool_call_count": row.get("tool_call_count"),
        "tool_error_count": row.get("tool_error_count"),
        "question_word_count": row.get("question_word_count"),
        "resolution_status": row.get("resolution_status"), "coverage_any": coverage,
    }
    return DciRecoveredCase(
        dataset_item_sha256=_domain_digest("query-id", query_id),
        metric_value_microunits=metric,
        run_status=cast(Literal["completed", "failed"], status),
        agent_total_tokens=_natural(row.get("agent_total_tokens")),
        overall_cost_microusd=_scaled(row.get("overall_cost_total"), Decimal("1000000")),
        wall_time_ns=_scaled(row.get("wall_time_seconds"), Decimal("1000000000")),
        tool_time_ns=tool_time, tool_call_count=tool_calls,
        tool_error_count=_natural(row.get("tool_error_count")),
        read_call_count=0, grep_call_count=0, read_time_ns=0, grep_time_ns=0,
        question_word_count=_natural(row.get("question_word_count")),
        resolution_status=_resolution_status(row.get("resolution_status")),
        resolution_coverage_microunits=None if coverage is None else _unit(coverage),
        case_source_sha256=_domain_digest("case-source", source),
    )


def _variant(
    config: Mapping[str, object], mode: Literal["ir", "qa"]
) -> DciRecoveredVariant:
    runtime = _mapping(config.get("runtime"))
    return DciRecoveredVariant(
        runtime_contract_sha256=_opaque_identity(config.get("runtime_contract"), "runtime-contract"),
        model_sha256=_opaque_identity(runtime.get("model"), "model"),
        toolset_sha256=_opaque_identity(runtime.get("tools"), "toolset"),
        prompt_contract_sha256=_sha256(config.get("benchmark_prompt_contract_sha256")),
        context_contract_sha256=_opaque_identity(config.get("context_contract"), "context-contract"),
        metric_contract_sha256=(
            _opaque_identity(config.get("ranking_metric_contract"), "metric-contract")
            if mode == "ir"
            else _opaque_identity("accuracy", "metric-contract")
        ),
        implementation_sha256=_sha256(config.get("implementation_sha256")),
        profile_sha256=_sha256(config.get("profile_sha256")),
        policy_sha256=_sha256(config.get("product_effective_config_sha256")),
    )


def _historical_variant(
    config: Mapping[str, object], mode: Literal["ir", "qa"]
) -> DciRecoveredVariant:
    """Project legacy identity hints into opaque, non-comparable identifiers."""

    runtime = _mapping(config.get("runtime"))
    return DciRecoveredVariant(
        runtime_contract_sha256=_domain_digest("legacy-runtime-contract", runtime),
        model_sha256=_domain_digest("legacy-model", runtime.get("model")),
        toolset_sha256=_domain_digest("legacy-toolset", runtime.get("tools")),
        prompt_contract_sha256=_sha256(config.get("benchmark_prompt_contract_sha256")),
        context_contract_sha256=_domain_digest(
            "legacy-context-contract", runtime.get("context_policy_identity")
        ),
        metric_contract_sha256=_opaque_identity(
            "ndcg-at-10" if mode == "ir" else "accuracy", "metric-contract"
        ),
        implementation_sha256=_domain_digest("legacy-schema", config.get("schema")),
        profile_sha256=_domain_digest("legacy-profile", config.get("profile")),
        policy_sha256=_domain_digest("legacy-selection", config.get("selection")),
    )


def _historical_corpus_file_count(config: Mapping[str, object]) -> int:
    """Legacy outputs did not seal corpus inventories; retain an explicit zero."""

    corpus_hint = config.get("corpus_hint")
    if corpus_hint is not None:
        return _natural(_mapping(corpus_hint).get("file_count"))
    return 0


def _validate_artifact_digests(config: Mapping[str, object], documents: Mapping[str, bytes]) -> None:
    digests = _mapping(config.get("artifact_digests"))
    for name in ("summary.json", "results.jsonl"):
        expected = _sha256(digests.get(name))
        actual = hashlib.sha256(documents[name]).hexdigest()
        if not hmac.compare_digest(expected, actual):
            raise ValueError


def _validate_result_rows(
    rows: tuple[Mapping[str, object], ...], cases: tuple[DciRecoveredCase, ...], mode: Literal["ir", "qa"]
) -> None:
    if len(rows) != len(cases):
        raise ValueError
    observed: dict[str, str] = {}
    for row in rows:
        query_id = _string(row.get("query_id"))
        digest = _domain_digest("query-id", query_id)
        status = row.get("status")
        if digest in observed or status not in {"completed", "failed"} or row.get("mode") != mode:
            raise ValueError
        observed[digest] = cast(str, status)
    expected = {case.dataset_item_sha256: case.run_status for case in cases}
    if observed != expected:
        raise ValueError


def _selected_count(config: Mapping[str, object]) -> int:
    selection = _mapping(config.get("selection"))
    return _natural(selection.get("selected_rows"))


def _counts(state: Mapping[str, object], summary: Mapping[str, object]) -> tuple[int, int]:
    state_counts = _mapping(state.get("counts"))
    summary_counts = _mapping(summary.get("counts"))
    if "failed_runs" in state_counts or "failed" in summary_counts:
        raise ValueError
    total = _natural(summary_counts.get("total"))
    failed = _natural(summary_counts.get("failed_runs"))
    if total != _natural(state_counts.get("total")) or failed != _natural(state_counts.get("failed")):
        raise ValueError
    return total, failed


def _summary_metric(summary: Mapping[str, object], mode: Literal["ir", "qa"]) -> int:
    if mode == "ir":
        return _unit(summary.get("ndcg_at_10"))
    accuracy = _mapping(summary.get("accuracy"))
    return _unit(accuracy.get("over_total"))


def _metric(row: Mapping[str, object], mode: Literal["ir", "qa"]) -> int:
    if mode == "ir":
        return _unit(row.get("ndcg_at_10"))
    correct = row.get("is_correct")
    if type(correct) is not bool:
        raise ValueError
    return 1_000_000 if correct else 0


def _tool_naturals(value: object) -> dict[str, int]:
    mapping = {} if value is None else _mapping(value)
    if set(mapping) - {"read", "grep"}:
        raise ValueError
    return {name: _natural(mapping.get(name, 0)) for name in ("read", "grep")}


def _tool_durations(value: object) -> dict[str, int]:
    mapping = {} if value is None else _mapping(value)
    if set(mapping) - {"read", "grep"}:
        raise ValueError
    return {name: _scaled(mapping.get(name, 0), Decimal("1000000000")) for name in ("read", "grep")}


def _run_unsigned_mapping(
    dataset_id: str,
    mode: Literal["ir", "qa"],
    metric_name: Literal["ndcg-at-10", "accuracy"],
    metric_value_microunits: int,
    selected_count: int,
    total_count: int,
    failed_count: int,
    corpus_file_count: int,
    dataset_snapshot_sha256: str,
    variant: DciRecoveredVariant,
    cases: tuple[DciRecoveredCase, ...],
    source_document_sha256s: tuple[str, ...],
    missing_evidence: tuple[str, ...],
    *,
    canonicalize_cases: bool,
) -> dict[str, object]:
    mapped_cases = (
        tuple(sorted(cases, key=lambda case: case.dataset_item_sha256))
        if canonicalize_cases
        else cases
    )
    return {
        "dataset_id": dataset_id,
        "mode": mode,
        "metric_name": metric_name,
        "metric_value_microunits": metric_value_microunits,
        "selected_count": selected_count,
        "total_count": total_count,
        "failed_count": failed_count,
        "corpus_file_count": corpus_file_count,
        "dataset_snapshot_sha256": dataset_snapshot_sha256,
        "variant": variant.to_mapping(),
        "cases": [case.to_mapping() for case in mapped_cases],
        "source_document_sha256s": list(source_document_sha256s),
        "missing_evidence": list(missing_evidence),
    }


def _build_recovered_run(
    dataset_id: str,
    mode: Literal["ir", "qa"],
    metric_name: Literal["ndcg-at-10", "accuracy"],
    metric_value_microunits: int,
    selected_count: int,
    total_count: int,
    failed_count: int,
    corpus_file_count: int,
    dataset_snapshot_sha256: str,
    variant: DciRecoveredVariant,
    cases: tuple[DciRecoveredCase, ...],
    source_document_sha256s: tuple[str, ...],
    missing_evidence: tuple[str, ...],
) -> DciRecoveredRun:
    unsigned = _run_unsigned_mapping(
        dataset_id,
        mode,
        metric_name,
        metric_value_microunits,
        selected_count,
        total_count,
        failed_count,
        corpus_file_count,
        dataset_snapshot_sha256,
        variant,
        cases,
        source_document_sha256s,
        missing_evidence,
        canonicalize_cases=True,
    )
    return DciRecoveredRun(
        dataset_id,
        mode,
        metric_name,
        metric_value_microunits,
        selected_count,
        total_count,
        failed_count,
        corpus_file_count,
        dataset_snapshot_sha256,
        variant,
        cases,
        source_document_sha256s,
        missing_evidence,
        _canonical_digest(unsigned),
    )


def _validate_recovered_run_mapping(mapping: object) -> DciRecoveredRun:
    value = _exact_mapping(mapping, _RUN_FIELDS)
    dataset_id = _string(value["dataset_id"])
    mode = _exact_mode(value["mode"])
    metric_name = _exact_metric_name(value["metric_name"])
    if (mode, metric_name) not in {("ir", "ndcg-at-10"), ("qa", "accuracy")}:
        raise ValueError
    metric_value = _exact_unit(value["metric_value_microunits"])
    selected_count = _exact_natural(value["selected_count"])
    total_count = _exact_natural(value["total_count"])
    failed_count = _exact_natural(value["failed_count"])
    corpus_file_count = _exact_natural(value["corpus_file_count"])
    dataset_snapshot_sha256 = _sha256(value["dataset_snapshot_sha256"])
    variant = _validated_variant(value["variant"])
    missing_evidence = _canonical_string_list(value["missing_evidence"])
    if missing_evidence not in {_MISSING_EVIDENCE, _LEGACY_MISSING_EVIDENCE}:
        raise ValueError
    raw_cases = _exact_list(value["cases"])
    if not raw_cases:
        raise ValueError
    cases = tuple(
        _validated_case(
            item, mode, allow_unclassified_tool_activity=missing_evidence == _LEGACY_MISSING_EVIDENCE
        )
        for item in raw_cases
    )
    case_ids = tuple(case.dataset_item_sha256 for case in cases)
    if case_ids != tuple(sorted(case_ids)) or len(case_ids) != len(set(case_ids)):
        raise ValueError
    source_document_sha256s = _canonical_sha256_list(value["source_document_sha256s"])
    if (
        selected_count != len(cases)
        or total_count != len(cases)
        or failed_count != sum(case.run_status == "failed" for case in cases)
    ):
        raise ValueError
    _validate_aggregate_metric(metric_value, cases)
    recovered = _build_recovered_run(
        dataset_id,
        mode,
        metric_name,
        metric_value,
        selected_count,
        total_count,
        failed_count,
        corpus_file_count,
        dataset_snapshot_sha256,
        variant,
        cases,
        source_document_sha256s,
        missing_evidence,
    )
    supplied = _sha256(value["recovered_run_sha256"])
    if not hmac.compare_digest(supplied, recovered.recovered_run_sha256):
        raise ValueError
    return recovered


def _validated_variant(value: object) -> DciRecoveredVariant:
    mapping = _exact_mapping(value, _VARIANT_FIELDS)
    return DciRecoveredVariant(**{field: _sha256(mapping[field]) for field in _VARIANT_FIELDS})


def _validated_case(
    value: object,
    mode: Literal["ir", "qa"],
    *,
    allow_unclassified_tool_activity: bool = False,
) -> DciRecoveredCase:
    mapping = _exact_mapping(value, _CASE_FIELDS)
    metric_value = _exact_unit(mapping["metric_value_microunits"])
    if mode == "qa" and metric_value not in {0, 1_000_000}:
        raise ValueError
    run_status = _exact_run_status(mapping["run_status"])
    resolution_status = _exact_resolution_status(mapping["resolution_status"])
    resolution_coverage = _exact_optional_unit(mapping["resolution_coverage_microunits"])
    if resolution_coverage is not None and resolution_status != "available":
        raise ValueError
    case = DciRecoveredCase(
        dataset_item_sha256=_sha256(mapping["dataset_item_sha256"]),
        metric_value_microunits=metric_value,
        run_status=run_status,
        agent_total_tokens=_exact_natural(mapping["agent_total_tokens"]),
        overall_cost_microusd=_exact_natural(mapping["overall_cost_microusd"]),
        wall_time_ns=_exact_natural(mapping["wall_time_ns"]),
        tool_time_ns=_exact_natural(mapping["tool_time_ns"]),
        tool_call_count=_exact_natural(mapping["tool_call_count"]),
        tool_error_count=_exact_natural(mapping["tool_error_count"]),
        read_call_count=_exact_natural(mapping["read_call_count"]),
        grep_call_count=_exact_natural(mapping["grep_call_count"]),
        read_time_ns=_exact_natural(mapping["read_time_ns"]),
        grep_time_ns=_exact_natural(mapping["grep_time_ns"]),
        question_word_count=_exact_natural(mapping["question_word_count"]),
        resolution_status=resolution_status,
        resolution_coverage_microunits=resolution_coverage,
        case_source_sha256=_sha256(mapping["case_source_sha256"]),
    )
    if (
        not allow_unclassified_tool_activity
        and case.tool_call_count != case.read_call_count + case.grep_call_count
    ):
        raise ValueError
    if (
        not allow_unclassified_tool_activity
        and case.tool_time_ns != case.read_time_ns + case.grep_time_ns
    ):
        raise ValueError
    return case


def _validate_aggregate_metric(
    metric_value_microunits: int, cases: tuple[DciRecoveredCase, ...]
) -> None:
    mean = sum(
        (Decimal(case.metric_value_microunits) for case in cases), Decimal(0)
    ) / len(cases)
    if abs(Decimal(metric_value_microunits) - mean) > 1:
        raise ValueError


def _exact_mapping(value: object, fields: frozenset[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise ValueError
    return cast(dict[str, object], value)


def _exact_list(value: object) -> list[object]:
    if type(value) is not list:
        raise ValueError
    return cast(list[object], value)


def _canonical_sha256_list(value: object) -> tuple[str, ...]:
    values = tuple(_sha256(item) for item in _exact_list(value))
    if not values or values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError
    return values


def _canonical_string_list(value: object) -> tuple[str, ...]:
    values = tuple(_string(item) for item in _exact_list(value))
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError
    return values


def _exact_mode(value: object) -> Literal["ir", "qa"]:
    if type(value) is not str or value not in {"ir", "qa"}:
        raise ValueError
    return cast(Literal["ir", "qa"], value)


def _exact_metric_name(value: object) -> Literal["ndcg-at-10", "accuracy"]:
    if type(value) is not str or value not in {"ndcg-at-10", "accuracy"}:
        raise ValueError
    return cast(Literal["ndcg-at-10", "accuracy"], value)


def _exact_run_status(value: object) -> Literal["completed", "failed"]:
    if type(value) is not str or value not in {"completed", "failed"}:
        raise ValueError
    return cast(Literal["completed", "failed"], value)


def _exact_resolution_status(value: object) -> Literal["available", "not-available"]:
    if type(value) is not str or value not in {"available", "not-available"}:
        raise ValueError
    return cast(Literal["available", "not-available"], value)


def _exact_natural(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _exact_unit(value: object) -> int:
    value = _exact_natural(value)
    if value > 1_000_000:
        raise ValueError
    return value


def _exact_optional_unit(value: object) -> int | None:
    return None if value is None else _exact_unit(value)


def _json_mapping(raw: bytes) -> Mapping[str, object]:
    value = json.loads(raw.decode("utf-8"), parse_float=Decimal, object_pairs_hook=_unique_object)
    return _mapping(value)


def _jsonl_mappings(raw: bytes) -> tuple[Mapping[str, object], ...]:
    lines = raw.splitlines()
    if not lines:
        raise ValueError
    return tuple(_json_mapping(line) for line in lines)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _mapping(value: object) -> Mapping[str, object]:
    if type(value) is not dict:
        raise ValueError
    return cast(Mapping[str, object], value)


def _string(value: object) -> str:
    if type(value) is not str or not value:
        raise ValueError
    return cast(str, value)


def _mode(value: object) -> Literal["ir", "qa"]:
    if value not in {"ir", "qa"}:
        raise ValueError
    return cast(Literal["ir", "qa"], value)


def _resolution_status(value: object) -> Literal["available", "not-available"]:
    if value not in {"available", "not-available"}:
        raise ValueError
    return cast(Literal["available", "not-available"], value)


def _natural(value: object) -> int:
    number = _decimal(value)
    if number < 0 or number != number.to_integral_value():
        raise ValueError
    return int(number)


def _unit(value: object) -> int:
    number = _decimal(value)
    if number < 0 or number > 1:
        raise ValueError
    return _rounded(number * Decimal("1000000"))


def _scaled(value: object, multiplier: Decimal) -> int:
    number = _decimal(value)
    if number < 0:
        raise ValueError
    return _rounded(number * multiplier)


def _decimal(value: object) -> Decimal:
    if type(value) not in {int, float, Decimal}:
        raise ValueError
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError from None
    if not number.is_finite():
        raise ValueError
    return number


def _rounded(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def _sha256(value: object) -> str:
    value = _string(value)
    if len(value) != 64 or set(value) - _HEX_SHA256:
        raise ValueError
    return value


def _opaque_identity(value: object, domain: str) -> str:
    return _domain_digest(domain, _string(value))


def _snapshot_digest(documents: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256(b"asterion.dci.pathlight.snapshot/v1\\0")
    for name in _FILES:
        digest.update(name.encode("ascii"))
        digest.update(b"\\0")
        digest.update(documents[name])
    return digest.hexdigest()


def _domain_digest(domain: str, value: object) -> str:
    return hashlib.sha256(
        f"asterion.dci.pathlight.{domain}/v1\\0".encode("ascii") + _canonical_bytes(value)
    ).hexdigest()


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, DciRecoveredVariant):
        value = value.to_mapping()
    elif isinstance(value, DciRecoveredCase):
        value = value.to_mapping()
    elif isinstance(value, tuple):
        value = [item.to_mapping() if hasattr(item, "to_mapping") else item for item in value]
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_canonical_default,
    ).encode("utf-8")


def _canonical_default(value: object) -> object:
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, (DciRecoveredCase, DciRecoveredVariant)):
        return value.to_mapping()
    raise TypeError
