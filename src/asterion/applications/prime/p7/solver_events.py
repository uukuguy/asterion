"""Public research event payloads, sharing the console's closed validator."""

from collections.abc import Mapping

from .research import copy_json

KINDS = frozenset({"compute_task", "model_revision", "plan", "feedback", "run_control"})
_TEXTS = {
    "goal",
    "question",
    "summary",
    "state_summary",
    "coverage_summary",
    "validation_summary",
    "correction_summary",
    "expected_summary",
    "actual_summary",
    "stop_reason",
    "reason",
}
_LISTS = {"obstacles", "rule_summaries", "unknowns", "assumptions"}


def validate_solver_payload(kind: str, payload: Mapping) -> dict:
    from .console_events import _research_payload

    value = copy_json(payload)
    try:
        valid = kind in KINDS and type(value) is dict and _research_payload(kind, value)
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("solver event unavailable")
    return value


def build_solver_payload(
    kind: str,
    *,
    source_action_sequence: int,
    observation_sha256: str,
    level: int,
    workspace_revision: str | None = None,
    task_id: str | None = None,
    origin: str,
    **fields,
) -> dict:
    from .console_events import public_narrative, public_text

    value = {
        "source_action_sequence": source_action_sequence,
        "observation_sha256": observation_sha256,
        "level": level,
        "workspace_revision": workspace_revision,
        "task_id": task_id,
        "origin": origin,
        **copy_json(fields),
    }
    for key in _TEXTS & value.keys():
        if value[key] is not None:
            value[key] = public_narrative(value[key], 600)
    if "description_zh" in value:
        value["description_zh"] = public_narrative(value["description_zh"], 8000)
    for key in _LISTS & value.keys():
        value[key] = [public_text(v) for v in value[key]][:32]
    return validate_solver_payload(kind, value)
