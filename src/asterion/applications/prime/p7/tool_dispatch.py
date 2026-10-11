"""P7 tool semantics and accounting, independent of the descriptor transport."""
from __future__ import annotations
import hashlib
import json
import sys
from collections.abc import Mapping
from .broker import ArcBroker
from .ipython_host import p7_client_facade

_BRIDGE_PROTOCOL = 'asterion.prime-ipython/v1'
_NO_PARAM_METHODS = frozenset({'observe', 'status', 'mechanics_prior', 'world_model',
    'planning_background', 'observation_state', 'game_mechanics', 'counterfactual_search',
    'cognition', 'action_effects', 'mechanism_candidates', 'probe_plan', 'simulator_status',
    'retrodiction_status'})


class P7ToolDispatch:
    def __init__(self, host, client, *, run_id):
        from .research_runtime import P7ResearchRuntime
        self._host = host
        self._client = None if isinstance(host, P7ResearchRuntime) else p7_client_facade(client)
        self._method_calls, self._method_failures = {}, {}
        self.identity_sha256 = hashlib.sha256(('p7-services/v1:' + run_id).encode()).hexdigest()
        self._closed = False

    @property
    def bridge_output_bytes(self):
        """Transport the application's exact computation output capacity."""
        limits = getattr(self._host, '_limits', None)
        return (limits.max_output_bytes if limits is not None
                else getattr(self._host, '_max_output_bytes', 64 * 1024))

    def validate_lifecycle(self):
        if self._closed or getattr(self._host, '_closed', True) or getattr(self._host, '_lost', True):
            raise ValueError('P7 services are unavailable')

    async def execute(self, request_id, code, signal):
        return await self._host.execute(request_id, code, signal)

    async def call(self, request_id, method, params, signal, *, params_present=True):
        if not params_present:
            if method not in _NO_PARAM_METHODS:
                raise ValueError('P7 method parameters are unavailable')
            params = {}
        self._signal = signal
        from .research_runtime import P7ResearchRuntime
        if isinstance(self._host, P7ResearchRuntime):
            self._method_calls[method] = min(5000, self._method_calls.get(method, 0) + 1)
            result = await self._host.async_method_call(method, params, signal)
            return {'output': json.dumps(result, allow_nan=False, ensure_ascii=False, separators=(',', ':')),
                    'protocol': _BRIDGE_PROTOCOL, 'request_id': request_id,
                    'status': 'ok', 'type': 'method_result'}
        return self._dispatch_method_call(request_id, method, params)

    def request_stop(self):
        stop = getattr(self._host, 'request_stop', None)
        if callable(stop):
            stop()

    async def close(self):
        await self._host.close()
        self._closed = True

    def private_accounting(self) -> dict[str, int]:
        """Return bounded private counts for bridge dispatch diagnosis."""
        return {
            "method_calls_total": sum(self._method_calls.values()),
            **{f"method_calls_{name}": count for name, count in self._method_calls.items()},
            "method_failures_total": sum(self._method_failures.values()),
            **{
                f"method_failures_{name}": count
                for name, count in self._method_failures.items()
            },
        }

    def _dispatch_method_call(
        self, request_id: str, method: str, params: object
    ) -> dict[str, object]:
        """Dispatch a non-code method invocation to the broker.

        The TypeScript extension registers each p7_client method as its
        own Pi tool. The model invokes the tool with JSON parameters and
        Pi serializes the call through this bridge with ``type ==
        "method_call"`` instead of going through the ipython cell-execution
        path.
        """
        from .operator import _p7_action_plan_names, _p7_action_result_summary
        self._method_calls[method] = min(5000, self._method_calls.get(method, 0) + 1)

        # The research host is an application adapter over Prime computation.
        # Only this actor channel can publish research or submit real plans.
        from .research_runtime import P7ResearchRuntime
        if isinstance(getattr(self, "_host", None), P7ResearchRuntime):
            result = self._host.method_call(method, params, self._signal)
            return {
                "output": json.dumps(result, allow_nan=False, ensure_ascii=False, separators=(",", ":")),
                "protocol": _BRIDGE_PROTOCOL, "request_id": request_id,
                "status": "ok", "type": "method_result",
            }

        def error_response() -> dict[str, object]:
            return {
                "output": "",
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": "error",
                "type": "method_result",
            }

        def ok_response(result: object) -> dict[str, object]:
            try:
                output = json.dumps(
                    result,
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            except (TypeError, ValueError, OverflowError):
                self._method_failures[method] = min(
                    5000, self._method_failures.get(method, 0) + 1
                )
                return error_response()
            if len(output.encode("utf-8")) > 120 * 1024:
                self._method_failures[f"{method}_output_too_large"] = min(
                    5000,
                    self._method_failures.get(f"{method}_output_too_large", 0) + 1,
                )
            return {
                "output": output,
                "protocol": _BRIDGE_PROTOCOL,
                "request_id": request_id,
                "status": "ok",
                "type": "method_result",
            }

        if method == "act_checked":
            plan_summary = _p7_action_plan_names(params)
            if plan_summary != "空计划":
                print(
                    f"[p7] P7动作计划：{plan_summary}。",
                    file=sys.stderr,
                    flush=True,
                )
        try:
            facade = self._client
            if self._first_probe_required(method):
                blocked = {
                    "status": "blocked",
                    "reason": "cognition-first-probe-required",
                    "next": "p7_cognition_update select_experiment, then p7_act_checked",
                    "execution_authority": "none",
                }
                if method == "act_checked":
                    print(
                        f"[p7] P7动作结果：{_p7_action_result_summary(blocked)}",
                        file=sys.stderr,
                        flush=True,
                    )
                return ok_response(blocked)
            if method in {"observe", "status", "mechanics_prior"}:
                if params is not None and (type(params) is not dict or params):
                    return error_response()
                value = getattr(facade, method)()
            elif method in {"world_model", "planning_background", "observation_state", "game_mechanics", "counterfactual_search", "cognition", "action_effects", "mechanism_candidates", "probe_plan", "simulator_status", "retrodiction_status", "model_search"}:
                if params is not None and (type(params) is not dict or params):
                    return error_response()
                value = getattr(facade, method)()
            elif method == "decision":
                if type(params) is not dict:
                    return error_response()
                value = facade.decision(params)
            elif method == "cognition_update":
                if type(params) is not dict or type(params.get("op")) is not str:
                    return error_response()
                value = facade.cognition_update(params)
            elif method == "playbook":
                if params is not None and (type(params) is not int or params < 0):
                    return error_response()
                value = facade.playbook(params)
            elif method == "record_hypothesis":
                if (
                    type(params) is not dict
                    or set(params) != {"layer", "key", "value"}
                    or type(params["layer"]) is not str
                    or type(params["key"]) is not str
                    or not isinstance(params["value"], dict)
                ):
                    return error_response()
                value = facade.record_hypothesis(params["layer"], params["key"], params["value"])
            elif method == "promote_hypothesis":
                if (
                    type(params) is not dict
                    or set(params) != {"key", "evidence_kind"}
                    or type(params["key"]) is not str
                    or type(params["evidence_kind"]) is not str
                ):
                    return error_response()
                value = facade.promote_hypothesis(params["key"], params["evidence_kind"])
            elif method in {"tried_actions", "last_outcome_summary"}:
                if params is not None and (
                    type(params) is not int or params < 0
                ):
                    return error_response()
                value = getattr(facade, method)(params)
            elif method == "history":
                if (
                    type(params) is not dict
                    or set(params) != {"start", "limit"}
                    or type(params["start"]) is not int
                    or params["start"] < 0
                    or type(params["limit"]) is not int
                    or params["limit"] < 1
                ):
                    return error_response()
                value = facade.history(params["start"], params["limit"])
            elif method == "frame_at":
                if (
                    type(params) is not dict
                    or set(params) != {"sequence"}
                    or type(params["sequence"]) is not int
                    or params["sequence"] < 0
                ):
                    return error_response()
                value = facade.frame_at(params["sequence"])
            elif method == "act_checked":
                if (
                    type(params) is not dict
                    or set(params) != {"plan"}
                    or type(params["plan"]) is not list
                ):
                    return error_response()
                value = facade.act_checked(params["plan"])
            else:
                return error_response()
        except BaseException:
            self._method_failures[method] = min(
                5000, self._method_failures.get(method, 0) + 1
            )
            return error_response()
        if method == "act_checked":
            print(
                f"[p7] P7动作结果：{_p7_action_result_summary(value)}",
                file=sys.stderr,
                flush=True,
            )
        return ok_response(value)

    def _first_probe_required(self, method: str) -> bool:
        """Force cognition mode to execute its first selected probe before detours."""
        client = getattr(self._client, "_P7ClientFacade__client", None)
        if not getattr(client, "_cognition_mode", False) or method in {
            "observe", "status", "cognition", "planning_background", "cognition_update", "decision",
        }:
            return False
        broker = getattr(client, "_broker", None)
        if not isinstance(broker, ArcBroker):
            return False
        try:
            snapshot = broker.cognition_projection().get("cognition_session")
        except Exception:
            return False
        if not isinstance(snapshot, Mapping):
            return False
        session_snapshot = snapshot.get("session")
        if not isinstance(session_snapshot, Mapping):
            return False
        blocked = (
            session_snapshot.get("state") in {"OBSERVE", "PROPOSE"}
            and session_snapshot.get("episode_actions") == 0
        )
        if blocked:
            print(
                "[p7-cognition] first-probe-blocked "
                + json.dumps({"method": method, "state": session_snapshot.get("state"), "episode_actions": 0}, separators=(",", ":")),
                file=sys.stderr,
                flush=True,
            )
        return blocked
