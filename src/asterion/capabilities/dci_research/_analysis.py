"""Package-owned DCI result aggregation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any


def _number(value: object) -> float | None:
    return (
        float(value)
        if not isinstance(value, bool) and isinstance(value, (int, float))
        else None
    )


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _sum(results: Sequence[Mapping[str, Any]], path: tuple[str, ...]) -> float:
    total = 0.0
    for result in results:
        value: object = result
        for key in path:
            value = value.get(key) if isinstance(value, Mapping) else None
        total += _number(value) or 0.0
    return total


def _compute_run_batch_timing(
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    starts = [_datetime(result.get("agent_started_at")) for result in results]
    ends = [_datetime(result.get("agent_finished_at")) for result in results]
    valid_starts = [value for value in starts if value is not None]
    valid_ends = [value for value in ends if value is not None]
    if not valid_starts or not valid_ends:
        return {
            "started_at": None,
            "finished_at": None,
            "elapsed_wall_clock_seconds": None,
        }
    start = min(valid_starts)
    end = max(valid_ends)
    return {
        "started_at": start.isoformat(),
        "finished_at": end.isoformat(),
        "elapsed_wall_clock_seconds": max(0.0, (end - start).total_seconds()),
    }


def aggregate_results(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(results)
    judged = sum(result.get("is_correct") is not None for result in results)
    correct = sum(result.get("is_correct") is True for result in results)
    failed = sum(result.get("run_status") != "completed" for result in results)
    paths = {
        "wall_time_seconds": ("wall_time_seconds",),
        "launcher_wall_time_seconds": ("launcher_wall_time_seconds",),
        "tool_time_seconds": ("tool_time_seconds",),
        "non_tool_time_seconds": ("non_tool_time_seconds",),
        "event_count": ("event_count",),
        "turn_count": ("turn_count",),
        "tool_call_count": ("tool_metrics", "call_count"),
        "tool_error_count": ("tool_metrics", "error_count"),
        "agent_input_tokens": ("agent_usage", "input_tokens"),
        "agent_output_tokens": ("agent_usage", "output_tokens"),
        "agent_cache_read_tokens": ("agent_usage", "cache_read_tokens"),
        "agent_cache_write_tokens": ("agent_usage", "cache_write_tokens"),
        "agent_total_tokens": ("agent_usage", "total_tokens"),
        "agent_cost_total": ("agent_usage", "cost_total"),
        "judge_input_tokens": ("judge_usage", "input_tokens"),
        "judge_output_tokens": ("judge_usage", "output_tokens"),
        "judge_total_tokens": ("judge_usage", "total_tokens"),
        "judge_cost_total": ("judge_cost_estimate_usd", "total_cost"),
    }
    totals = {name: _sum(results, path) for name, path in paths.items()}
    totals["overall_cost_total"] = (
        totals["agent_cost_total"] + totals["judge_cost_total"]
    )
    ndcg = [
        float(value)
        for result in results
        if (value := _number(result.get("ndcg_at_10"))) is not None
    ]
    resolution_rows = [
        value
        for result in results
        if isinstance((value := result.get("resolution")), Mapping)
    ]
    coverage_values: dict[str, list[float]] = {
        name: [] for name in ("any", "mean", "all")
    }
    localization_numerator = 0.0
    localization_denominator = 0
    retained_values: list[float] = []
    for resolution in resolution_rows:
        resolution_metrics = resolution.get("metrics")
        if not isinstance(resolution_metrics, Mapping):
            continue
        coverage = resolution_metrics.get("coverage")
        if isinstance(coverage, Mapping):
            for name in coverage_values:
                if (number := _number(coverage.get(name))) is not None:
                    coverage_values[name].append(number)
        localization = resolution_metrics.get("localization")
        if isinstance(localization, Mapping):
            value = _number(localization.get("value"))
            matched = localization.get("matched_gold_count")
            if (
                value is not None
                and isinstance(matched, int)
                and not isinstance(matched, bool)
                and matched > 0
            ):
                localization_numerator += value * matched
                localization_denominator += matched
        retained = resolution_metrics.get("retained_coverage")
        if isinstance(retained, Mapping):
            if (number := _number(retained.get("value"))) is not None:
                retained_values.append(number)
    return {
        "schema": "asterion.dci.batch-summary/v1",
        "counts": {
            "total": total,
            "judged": judged,
            "correct": correct,
            "incorrect_or_unjudged": total - correct,
            "failed_runs": failed,
        },
        "accuracy": {
            "over_total": correct / total if total else 0.0,
            "over_judged": correct / judged if judged else 0.0,
        },
        "ndcg_at_10": sum(ndcg) / len(ndcg) if ndcg else None,
        "resolution": {
            "available_queries": len(resolution_rows),
            "coverage": {
                name: sum(values) / len(values) if values else None
                for name, values in coverage_values.items()
            },
            "localization": (
                localization_numerator / localization_denominator
                if localization_denominator
                else None
            ),
            "matched_gold_count": localization_denominator,
            "retained_coverage": (
                sum(retained_values) / len(retained_values)
                if retained_values
                else None
            ),
            "retained_available_queries": len(retained_values),
        },
        "timing": _compute_run_batch_timing(results),
        "totals": totals,
        "averages": {
            name: totals[name] / total if total else 0.0
            for name in (
                "wall_time_seconds",
                "tool_time_seconds",
                "tool_call_count",
                "turn_count",
                "agent_total_tokens",
                "judge_total_tokens",
                "overall_cost_total",
            )
        },
    }


__all__ = ("aggregate_results",)
