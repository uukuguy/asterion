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


def _p7_rollout_supported_actions(value):
    if value is Ellipsis or value is None:
        return value
    names = [f"ACTION{i}" for i in range(1, 8)] + ["RESET"]
    if type(value) not in (list, tuple) or any(
        type(name) is not str or name not in names for name in value
    ):
        raise ValueError("supported_actions must be a list or tuple of action names")
    return list(value)


def _p7_rollout_risk_new(checker, supported_actions=...):
    action_coverage = (
        "unchecked" if supported_actions is Ellipsis else
        "undeclared" if supported_actions is None else "declared"
    )
    return {
        "status": "unassessed", "findings": [],
        "coverage": {
            "checker_supplied": checker is not None, "evaluated_ticks": 0,
            "unassessed_ticks": 0, "errors": [], "partial": True,
            "action_coverage": action_coverage,
        },
    }


def _p7_rollout_risk_refresh(risk):
    kinds = [finding["type"] for finding in risk["findings"]]
    coverage = risk["coverage"]
    if "predicted_death" in kinds:
        risk["status"] = "predicted_death"
    elif "conditional_fatal" in kinds:
        risk["status"] = "conditional_fatal"
    elif (
        not coverage["checker_supplied"] or not coverage["evaluated_ticks"]
        or coverage["unassessed_ticks"] or coverage["errors"] or coverage["partial"]
    ):
        risk["status"] = "unassessed"
    else:
        risk["status"] = "no_identified_fatal"


def _p7_rollout_risk_error(risk, tick, reason):
    risk["coverage"]["unassessed_ticks"] += 1
    risk["coverage"]["errors"].append({"tick": tick, "reason": reason})


def _p7_rollout_risk_check(risk, checker, before, after, action, tick):
    if checker is None:
        risk["coverage"]["unassessed_ticks"] += 1
        return
    try:
        payload = _p7_rollout_copy(checker(
            _p7_rollout_copy(before), _p7_rollout_copy(after), _p7_rollout_copy(action),
        ))
    except Exception as error:
        _p7_rollout_risk_error(risk, tick, f"risk_check_exception:{type(error).__name__}")
        return
    envelope = payload if type(payload) is dict else None
    findings = envelope.get("findings") if envelope is not None else payload
    if type(findings) is not list:
        _p7_rollout_risk_error(risk, tick, "risk_check_invalid")
        return
    invalid = envelope is not None and (
        set(envelope) != {"findings", "coverage", "reason"}
        or envelope.get("coverage") not in ("covered", "unknown")
        or type(envelope.get("reason")) is not str
        or not envelope["reason"].strip()
    )
    for finding in findings:
        if (
            type(finding) is not dict
            or set(finding) != {"id", "type", "condition", "evidence"}
            or type(finding["id"]) is not str or not finding["id"].strip()
            or finding["type"] not in ("predicted_death", "conditional_fatal")
            or type(finding["condition"]) not in (str, dict, list)
            or not finding["condition"]
            or type(finding["evidence"]) not in (str, dict, list)
            or not finding["evidence"]
        ):
            invalid = True
        else:
            risk["findings"].append(finding)
    if invalid:
        _p7_rollout_risk_error(risk, tick, "risk_check_invalid")
    elif envelope is not None and envelope["coverage"] == "unknown":
        _p7_rollout_risk_error(risk, tick, "risk_coverage_unknown")
        risk["coverage"]["errors"][-1]["model_reason"] = envelope["reason"]
    else:
        risk["coverage"]["evaluated_ticks"] += 1


def _p7_rollout_risk_death(risk, tick, action_index):
    risk["findings"].append({
        "id": "rollout.terminal-dead", "type": "predicted_death",
        "condition": {"terminal": "dead"},
        "evidence": {"source": "terminal", "tick": tick, "action_index": action_index},
    })


def _p7_rollout_finish(result):
    result["risk"]["coverage"]["partial"] = (
        result["outcome"] == "unknown"
        or result["evaluated_actions"] < len(result["actions"])
        or bool(result["risk"]["coverage"]["errors"])
    )
    _p7_rollout_risk_refresh(result["risk"])
    return result


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
    max_ticks_per_action=128, risk_check=None, supported_actions=...,
):
    """Apply one input per action, then None until a consequence is known.

    Only settled segments permit the next input. Collision, death, goal and
    unknown stop the candidate. Full states and unexpanded action suffixes are
    retained. Unknown covers uncertain callbacks, errors, cycles and limits.
    A result describes this model; even a settled result is no safety claim.
    risk_check(before, after, action_or_none) declares explicit findings with
    id/type/condition/evidence; type is predicted_death or conditional_fatal.
    It runs before terminal/settled acceptance, with independent coverage.
    A checker may also return {findings, coverage: covered|unknown, reason}.
    Unknown coverage leaves dynamics unchanged and risk unassessed, unless a
    fatal finding exists. No state fields or game rules are inferred here.
    supported_actions omission preserves the legacy API without checking its
    action coverage. Explicit None means undeclared coverage but still runs
    callbacks to retain death warnings. A list/tuple declares canonical action
    names; unsupported inputs stop before transition with an unknown result.
    Declarations describe the model's scope, never verified real rules.
    """
    if type(max_ticks_per_action) is not int or max_ticks_per_action <= 0:
        raise ValueError("max_ticks_per_action must be a positive integer")
    supported_actions = _p7_rollout_supported_actions(supported_actions)
    result = {
        "outcome": "unknown", "reason": "invalid_initial_state", "ticks": 0,
        "limit": max_ticks_per_action, "state": None, "states": [],
        "actions": [], "evaluated_actions": 0, "segments": [],
        "execution_authority": "none", "claims": "model-relative",
        "risk": _p7_rollout_risk_new(risk_check, supported_actions),
    }
    if supported_actions is None:
        result["risk"]["coverage"]["errors"].append({
            "tick": 0, "reason": "action_coverage_undeclared",
        })
    try:
        state = _p7_rollout_copy(initial_state)
    except Exception:
        return _p7_rollout_finish(result)
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
        return _p7_rollout_finish(result)
    result["actions"] = copied_actions

    outcome, reason = _p7_rollout_probe(terminal, state, "terminal")
    if outcome is not None:
        result.update(outcome=outcome, reason=reason)
        if outcome == "dead":
            _p7_rollout_risk_death(result["risk"], 0, None)
        return _p7_rollout_finish(result)
    if not copied_actions:
        outcome, reason = _p7_rollout_classify(state, terminal, settled, collision)
        result.update(outcome=outcome or "unknown", reason=reason or "no_actions")
        return _p7_rollout_finish(result)

    for action_index, action in enumerate(copied_actions):
        if (
            supported_actions is not Ellipsis and supported_actions is not None
            and action["name"] not in supported_actions
        ):
            result.update(outcome="unknown", reason="unsupported_action")
            result["risk"]["coverage"]["action_coverage"] = "unsupported"
            result["risk"]["coverage"]["errors"].append({
                "tick": result["ticks"], "reason": "unsupported_action",
                "action_index": action_index, "action": action["name"],
            })
            break
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
            before_state = state
            tick_action = action if tick == 1 else None
            try:
                next_state = transition(
                    _p7_rollout_copy(state), _p7_rollout_copy(tick_action),
                )
            except Exception as error:
                segment["reason"] = f"transition_exception:{type(error).__name__}"
                _p7_rollout_risk_error(result["risk"], result["ticks"], segment["reason"])
                break
            try:
                state = _p7_rollout_copy(next_state)
            except Exception:
                segment["reason"] = "invalid_transition_state"
                _p7_rollout_risk_error(result["risk"], result["ticks"], segment["reason"])
                break
            result["states"].append(_p7_rollout_copy(state))
            _p7_rollout_risk_check(
                result["risk"], risk_check, before_state, state, tick_action, result["ticks"],
            )
            outcome, reason = _p7_rollout_classify(state, terminal, settled, collision)
            if outcome == "dead":
                _p7_rollout_risk_death(result["risk"], result["ticks"], action_index)
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
    return _p7_rollout_finish(result)


def replay_cases(
    cases, *, transition, settled, terminal, collision=None, max_ticks_per_action=128,
    risk_check=None, supported_actions=...,
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
            risk_check=risk_check,
            supported_actions=supported_actions,
        )
        if missing_state:
            result["reason"] = "missing_initial_state"
        elif (
            result["actions"] and result["evaluated_actions"] == 0
            and result["outcome"] in ("dead", "goal")
        ):
            result.update(outcome="unknown", reason="initial_terminal_no_transition")
        _p7_rollout_finish(result)
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
            "risk": _p7_rollout_copy(result["risk"]),
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
    max_ticks_per_action=128, backtest=None, risk_check=None, supported_actions=...,
):
    """Exclude only model-predicted death; retain unknown and other boundaries.

    An explicitly supplied backtest must be checked to use its model's death
    predictions. Other statuses downgrade all candidate outcomes to unknown.
    """
    evaluations = []
    predicted_dead = []
    unknown = []
    remaining = []
    supported_actions = _p7_rollout_supported_actions(supported_actions)
    combined_risk = _p7_rollout_risk_new(risk_check, supported_actions)
    combined_risk["coverage"]["partial"] = False
    backtest_status = (
        "not_backtested" if backtest is None else
        backtest.get("status", "unknown") if type(backtest) is dict else "unknown"
    )
    checked = backtest is None or (
        type(backtest) is dict and backtest.get("status") == "checked"
    )
    for index, actions in enumerate(candidates):
        result = rollout(
            initial_state, actions, transition=transition, settled=settled,
            terminal=terminal, collision=collision,
            max_ticks_per_action=max_ticks_per_action,
            risk_check=risk_check,
            supported_actions=supported_actions,
        )
        outcome = result["outcome"] if checked else "unknown"
        evaluations.append({
            "candidate_index": index, "outcome": outcome,
            "reason": result["reason"] if checked else "backtest_not_checked",
            "rollout": result,
            "risk": _p7_rollout_copy(result["risk"]),
            "model_confidence": {"backtest_status": backtest_status, "scope": "cases_only"},
        })
        combined_risk["findings"].extend([
            {**finding, "evidence": {
                "candidate_index": index, "evidence": _p7_rollout_copy(finding["evidence"]),
            }} for finding in _p7_rollout_copy(result["risk"]["findings"])
        ])
        source_coverage = result["risk"]["coverage"]
        coverage = combined_risk["coverage"]
        for count in ("evaluated_ticks", "unassessed_ticks"):
            coverage[count] += source_coverage[count]
        coverage["errors"].extend([
            {**error, "candidate_index": index} for error in source_coverage["errors"]
        ])
        coverage["partial"] |= source_coverage["partial"]
        if source_coverage["action_coverage"] == "unsupported":
            coverage["action_coverage"] = "unsupported"
        if outcome == "dead":
            predicted_dead.append(index)
        else:
            remaining.append(index)
        if outcome == "unknown":
            unknown.append(index)
    _p7_rollout_risk_refresh(combined_risk)
    return {
        "evaluations": evaluations, "predicted_dead": predicted_dead,
        "unknown": unknown, "remaining": remaining,
        "execution_authority": "none", "claims": "model-relative",
        "risk": combined_risk,
    }
