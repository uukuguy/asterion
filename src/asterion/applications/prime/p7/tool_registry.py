"""Concrete Prime application-tool registration for P7."""

from __future__ import annotations

from asterion.agents.prime.tool_registry import PrimeApplicationToolRegistry


P7_TOOL_MODULE_ID = "prime.p7.application-tools"
P7_TOOL_CAPABILITY_ID = "prime.tool.p7"
P7_APPLICATION_TOOL_NAMES = tuple(sorted({
    "ipython",
    "p7_act_checked",
    "p7_action_effects",
    "p7_cognition",
    "p7_cognition_update",
    "p7_counterfactual_search",
    "p7_frame_at",
    "p7_game_mechanics",
    "p7_history",
    "p7_last_outcome_summary",
    "p7_mechanism_candidates",
    "p7_mechanics_prior",
    "p7_model_search",
    "p7_observation_state",
    "p7_observe",
    "p7_planning_background",
    "p7_playbook",
    "p7_probe_plan",
    "p7_promote_hypothesis",
    "p7_record_hypothesis",
    "p7_retrodiction_status",
    "p7_simulator_status",
    "p7_status",
    "p7_tried_actions",
    "p7_world_model",
}))
P7_TOOL_REGISTRY = PrimeApplicationToolRegistry(
    P7_TOOL_MODULE_ID,
    P7_TOOL_CAPABILITY_ID,
    P7_APPLICATION_TOOL_NAMES,
)


__all__ = (
    "P7_APPLICATION_TOOL_NAMES",
    "P7_TOOL_CAPABILITY_ID",
    "P7_TOOL_MODULE_ID",
    "P7_TOOL_REGISTRY",
)
