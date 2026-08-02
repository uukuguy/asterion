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
    PrivateFileError,
    read_private_file_snapshot,
)


_FILES = ("config.json", "batch-state.json", "summary.json", "analysis.json", "results.jsonl")
_LIMITS = {name: 1 << 20 for name in _FILES}
_HEX_SHA256 = frozenset("0123456789abcdef")
_MISSING_EVIDENCE = ("sealed-analysis-digest", "sealed-config-digest")


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

    def to_mapping(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "mode": self.mode,
            "metric_name": self.metric_name,
            "metric_value_microunits": self.metric_value_microunits,
            "selected_count": self.selected_count,
            "total_count": self.total_count,
            "failed_count": self.failed_count,
            "corpus_file_count": self.corpus_file_count,
            "dataset_snapshot_sha256": self.dataset_snapshot_sha256,
            "variant": self.variant.to_mapping(),
            "cases": [case.to_mapping() for case in self.cases],
            "source_document_sha256s": list(self.source_document_sha256s),
            "missing_evidence": list(self.missing_evidence),
            "recovered_run_sha256": self.recovered_run_sha256,
        }


def read_completed_dci_run(root: Path, expected_dataset_id: str) -> DciRecoveredRun:
    """Recover one completed DCI batch without retaining private source content."""

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
        return _recover(config, state, summary, analysis, result_rows, expected_dataset_id, documents)
    except (DciRecoveryError, PrivateFileError, ValueError, TypeError, UnicodeError):
        raise DciRecoveryError("DCI recovery evidence is invalid") from None


def _recover(
    config: Mapping[str, object],
    state: Mapping[str, object],
    summary: Mapping[str, object],
    analysis: Mapping[str, object],
    result_rows: tuple[Mapping[str, object], ...],
    expected_dataset_id: str,
    documents: Mapping[str, bytes],
) -> DciRecoveredRun:
    dataset = _mapping(config.get("dataset"))
    dataset_id = _string(dataset.get("dataset_id"))
    if dataset_id != expected_dataset_id:
        raise ValueError
    mode = _mode(config.get("mode"))
    if state.get("status") != "completed":
        raise ValueError
    variant = _variant(config)
    rows = analysis.get("per_query_metrics")
    if type(rows) is not list or not rows:
        raise ValueError
    cases = tuple(_case(row, mode) for row in rows)
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
    mean = sum((Decimal(case.metric_value_microunits) for case in cases), Decimal(0)) / len(cases)
    if abs(Decimal(metric_value) - mean) > 1:
        raise ValueError
    corpus = _mapping(config.get("corpus_content_identity"))
    corpus_file_count = _natural(corpus.get("file_count"))
    dataset_snapshot_sha256 = _sha256(dataset.get("sha256"))
    source_document_sha256s = (_snapshot_digest(documents),)
    document = _run_document(
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
    )
    document["missing_evidence"] = list(_MISSING_EVIDENCE)
    return DciRecoveredRun(
        dataset_id=dataset_id,
        mode=mode,
        metric_name=metric_name,
        metric_value_microunits=metric_value,
        selected_count=selected_count,
        total_count=total_count,
        failed_count=failed_count,
        corpus_file_count=corpus_file_count,
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        variant=variant,
        cases=cases,
        source_document_sha256s=source_document_sha256s,
        missing_evidence=_MISSING_EVIDENCE,
        recovered_run_sha256=_canonical_digest(document),
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


def _variant(config: Mapping[str, object]) -> DciRecoveredVariant:
    runtime = _mapping(config.get("runtime"))
    return DciRecoveredVariant(
        runtime_contract_sha256=_identity(config.get("runtime_contract"), "runtime-contract"),
        model_sha256=_identity(runtime.get("model"), "model"),
        toolset_sha256=_identity(runtime.get("tools"), "toolset"),
        prompt_contract_sha256=_identity(config.get("benchmark_prompt_contract_sha256"), "prompt-contract"),
        context_contract_sha256=_identity(config.get("context_contract"), "context-contract"),
        metric_contract_sha256=_identity(config.get("ranking_metric_contract"), "metric-contract"),
        implementation_sha256=_identity(config.get("implementation_sha256"), "implementation"),
        profile_sha256=_identity(config.get("profile_sha256"), "profile"),
        policy_sha256=_identity(runtime.get("context_policy_identity"), "policy"),
    )


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
    return _natural(selection.get("selected_rows", selection.get("selected_count")))


def _counts(state: Mapping[str, object], summary: Mapping[str, object]) -> tuple[int, int]:
    state_counts = _mapping(state.get("counts"))
    summary_counts = _mapping(summary.get("counts"))
    total = _natural(summary_counts.get("total"))
    failed = _natural(summary_counts.get("failed", summary_counts.get("failed_runs")))
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


def _run_document(
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
) -> dict[str, object]:
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
        "variant": variant,
        "cases": cases,
        "source_document_sha256s": source_document_sha256s,
    }


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


def _identity(value: object, domain: str) -> str:
    if type(value) is str and len(value) == 64 and not (set(value) - _HEX_SHA256):
        return cast(str, value)
    return _domain_digest(domain, value)


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
