"""Experimental, model-relative consequences; no execution authority.

This entire stdlib-only source can be prepended to an IPython model module.
Callbacks describe a hypothetical JSON state, never the real game engine.
The tick limit is per action; callback wall time belongs to the host kernel.
"""

import json as _p7_rollout_json


def _p7_rollout_copy(value):
    """Copy strict JSON, rejecting silent conversion of model objects."""
    def validate(item):
        if item is None or type(item) in (str, bool, int, float):
            return
        if type(item) is list:
            for child in item:
                validate(child)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                validate(child)
            return
        raise ValueError("model state must be JSON")

    validate(value)
    return _p7_rollout_json.loads(_p7_rollout_json.dumps(value, allow_nan=False))


def _p7_rollout_key(state):
    return _p7_rollout_json.dumps(state, sort_keys=True, allow_nan=False)


def _p7_rollout_probe(callback, state, name):
    try:
        value = callback(_p7_rollout_copy(state))
    except Exception as error:
        return "unknown", f"{name}_exception:{type(error).__name__}"
    if name == "terminal":
        if value is None:
            return None, None
        if type(value) is str and value in ("dead", "goal", "unknown"):
            return value, f"terminal_{value}"
        return "unknown", "terminal_invalid"
    if value is None:
        return "unknown", f"{name}_unknown"
    if type(value) is not bool:
        return "unknown", f"{name}_invalid"
    return value, None


def _p7_rollout_classify(state, terminal, settled, collision):
    outcome, reason = _p7_rollout_probe(terminal, state, "terminal")
    if outcome is not None:
        return outcome, reason
    if collision is not None:
        hit, reason = _p7_rollout_probe(collision, state, "collision")
        if hit == "unknown":
            return "unknown", reason
        if hit:
            return "collision", "collision"
    done, reason = _p7_rollout_probe(settled, state, "settled")
    if done == "unknown":
        return "unknown", reason
    if done:
        return "settled", "settled"
    return None, None


def rollout(
    initial_state, actions, *, transition, settled, terminal, collision=None,
    max_ticks_per_action=128,
):
    """Apply one input per action, then None until a consequence is known.

    Only settled segments permit the next input. Collision, death, goal and
    unknown stop the candidate. Full states and unexpanded action suffixes are
    retained. Unknown covers uncertain callbacks, errors, cycles and limits.
    A result describes this model; even a settled result is no safety claim.
    """
    if type(max_ticks_per_action) is not int or max_ticks_per_action <= 0:
        raise ValueError("max_ticks_per_action must be a positive integer")
    result = {
        "outcome": "unknown", "reason": "invalid_initial_state", "ticks": 0,
        "limit": max_ticks_per_action, "state": None, "states": [],
        "actions": [], "evaluated_actions": 0, "segments": [],
        "execution_authority": "none", "claims": "model-relative",
    }
    try:
        state = _p7_rollout_copy(initial_state)
    except Exception:
        return result
    result["state"] = state
    result["states"].append(_p7_rollout_copy(state))
    try:
        copied_actions = _p7_rollout_copy(actions)
        if type(copied_actions) is not list:
            raise ValueError("actions must be a JSON list")
        for action in copied_actions:
            if (
                type(action) is not dict or set(action) != {"name", "data"}
                or action["name"] not in [f"ACTION{i}" for i in range(1, 8)] + ["RESET"]
                or type(action["data"]) is not dict
            ):
                raise ValueError("invalid action")
    except Exception:
        result["reason"] = "invalid_actions"
        return result
    result["actions"] = copied_actions

    outcome, reason = _p7_rollout_probe(terminal, state, "terminal")
    if outcome is not None:
        result.update(outcome=outcome, reason=reason)
        return result
    if not copied_actions:
        outcome, reason = _p7_rollout_classify(state, terminal, settled, collision)
        result.update(outcome=outcome or "unknown", reason=reason or "no_actions")
        return result

    for action_index, action in enumerate(copied_actions):
        # The input tick and subsequent None ticks have different dynamics.
        # An unchanged input state alone is not an autonomous-state cycle.
        seen = set()
        segment = {
            "action_index": action_index, "ticks": 0,
            "outcome": "unknown", "reason": "tick_limit", "state": None,
        }
        for tick in range(1, max_ticks_per_action + 1):
            segment["ticks"] = tick
            result["ticks"] += 1
            try:
                next_state = transition(
                    _p7_rollout_copy(state),
                    _p7_rollout_copy(action) if tick == 1 else None,
                )
            except Exception as error:
                segment["reason"] = f"transition_exception:{type(error).__name__}"
                break
            try:
                state = _p7_rollout_copy(next_state)
            except Exception:
                segment["reason"] = "invalid_transition_state"
                break
            result["states"].append(_p7_rollout_copy(state))
            outcome, reason = _p7_rollout_classify(state, terminal, settled, collision)
            if outcome is not None:
                segment.update(outcome=outcome, reason=reason)
                break
            key = _p7_rollout_key(state)
            if key in seen:
                segment["reason"] = "state_cycle"
                break
            seen.add(key)
        segment["state"] = _p7_rollout_copy(state)
        result["segments"].append(segment)
        result.update(
            outcome=segment["outcome"], reason=segment["reason"],
            state=_p7_rollout_copy(state), evaluated_actions=action_index + 1,
        )
        if segment["outcome"] != "settled":
            break
    return result


def replay_cases(
    cases, *, transition, settled, terminal, collision=None, max_ticks_per_action=128,
):
    """Backtest all recorded cases, preserving uncertainty and counterexamples.

    Predictions are interpretable game-state expectations for the existing
    behavioral diff. A checked backtest is evidence about these cases only.
    """
    backtests = []
    predictions = []
    state_names = {
        "dead": "GAME_OVER", "goal": "WIN", "settled": "NOT_FINISHED",
        "collision": "NOT_FINISHED",
    }
    for case in cases:
        sequence = case.get("sequence")
        expected = case.get("expected_outcome")
        missing_state = case.get("initial_state") is None
        result = rollout(
            case.get("initial_state"), case.get("actions"), transition=transition,
            settled=settled,
            terminal=(lambda state: "unknown") if missing_state else terminal,
            collision=collision,
            max_ticks_per_action=max_ticks_per_action,
        )
        if missing_state:
            result["reason"] = "missing_initial_state"
        elif (
            result["actions"] and result["evaluated_actions"] == 0
            and result["outcome"] in ("dead", "goal")
        ):
            result.update(outcome="unknown", reason="initial_terminal_no_transition")
        predicted = result["outcome"]
        partial = (
            predicted == "collision"
            and result["evaluated_actions"] < len(result["actions"])
        )
        if predicted == "unknown" or expected not in state_names or partial:
            status = "unknown"
        else:
            status = "checked" if predicted == expected else "counterexample"
        backtests.append({
            "sequence": _p7_rollout_copy(sequence), "expected_outcome": expected,
            "predicted_outcome": predicted, "status": status, "rollout": result,
        })
        if predicted in state_names and not partial:
            predictions.append({
                "sequence": _p7_rollout_copy(sequence),
                "expect": {"state": state_names[predicted]},
            })
    statuses = [case["status"] for case in backtests]
    status = (
        "counterexample" if "counterexample" in statuses else
        "unknown" if not statuses or "unknown" in statuses else "checked"
    )
    return {
        "backtests": backtests, "predictions": predictions, "status": status,
        "execution_authority": "none", "claims": "model-relative",
    }


def evaluate_candidates(
    initial_state, candidates, *, transition, settled, terminal, collision=None,
    max_ticks_per_action=128, backtest=None,
):
    """Exclude only model-predicted death; retain unknown and other boundaries.

    An explicitly supplied backtest must be checked to use its model's death
    predictions. Other statuses downgrade all candidate outcomes to unknown.
    """
    evaluations = []
    predicted_dead = []
    unknown = []
    remaining = []
    checked = backtest is None or (
        type(backtest) is dict and backtest.get("status") == "checked"
    )
    for index, actions in enumerate(candidates):
        result = rollout(
            initial_state, actions, transition=transition, settled=settled,
            terminal=terminal, collision=collision,
            max_ticks_per_action=max_ticks_per_action,
        )
        outcome = result["outcome"] if checked else "unknown"
        evaluations.append({
            "candidate_index": index, "outcome": outcome,
            "reason": result["reason"] if checked else "backtest_not_checked",
            "rollout": result,
        })
        if outcome == "dead":
            predicted_dead.append(index)
        else:
            remaining.append(index)
        if outcome == "unknown":
            unknown.append(index)
    return {
        "evaluations": evaluations, "predicted_dead": predicted_dead,
        "unknown": unknown, "remaining": remaining,
        "execution_authority": "none", "claims": "model-relative",
    }
