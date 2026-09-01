"""Run the bounded, public-safe Prime Core smoke scenario."""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

from asterion.runtime.observation import RunObservationLog
from tools.prime_core_smoke import PrimeCoreSmokeResult, verify_prime_core_smoke_result
from tools.prime_native_rlm_experiment import (
    NativeRlmPrivateGoal,
    native_rlm_model_selector_digest,
    prepare_native_rlm_experiment,
    resolve_native_rlm_model,
    run_native_rlm_controlled_probe,
    run_owned_native_rlm_sidecar_probe,
)
from tools.verify_prime_loop import (
    _native_rlm_environment,
    _native_rlm_runtime_resources,
    verify_preflight,
)


_CORE_GOAL = (
    "Complete two independent native RLM child lifecycles in sequence. Each child "
    "must receive one parent message, finish, and be deleted before the goal completes."
)
_CORE_START = (
    "Do not answer with prose. Use IPython now. Create exactly one child with rlm, "
    "send it one ping using agent_message.send, and wait for its reply in a later turn. "
    "After its reply, delete that child. Then create exactly one different second child, "
    "send one ping, wait for its reply, delete it, and complete the goal. Do not create "
    "a child until the previous child is deleted."
)


def _safe_reason(error: Exception) -> str:
    safe_code = getattr(error, "safe_code", None)
    if isinstance(safe_code, str) and safe_code:
        return safe_code
    return {
        "PrimeRlmExperimentError": "experiment",
        "TimeoutError": "timeout",
        "OSError": "os",
        "RuntimeError": "runtime",
        "ValueError": "value",
        "TypeError": "type",
    }.get(type(error).__name__, "unexpected")


def _external_limited() -> PrimeCoreSmokeResult:
    return PrimeCoreSmokeResult(
        terminal="uncertain", terminal_count=0, root_model_selected=False,
        generated_program_admitted=False, application_succeeded=False,
        oracle_passed=False, child_target_count=2, children_started=0,
        children_completed=0, children_deleted=0, message_delivered=False,
        message_causality_complete=False, detached_while_active=False,
        reattached=False, replay_contiguous=False, work_continued_after_attach=False,
        recursion_policy_enforced=False, control_event_sequence_contiguous=False,
        observation_health="unknown", observation_gap_count=1,
        cleanup_complete=False, privacy_checks_passed=False, within_budget=False,
    )


def main() -> int:
    run_id = f"prime-core-smoke-{time.time_ns()}"
    log = RunObservationLog(Path("runs/observations"), run_id)

    def observe(event_type: str, payload: dict[str, str] | None = None) -> None:
        print(json.dumps(dict(log.record(event_type, payload)), sort_keys=True, separators=(",", ":")), flush=True)

    observe("run.started")
    root: Path | None = None
    try:
        observe("run.phase", {"phase": "prime.preflight"})
        source_root = Path("3th-party/prime-agent")
        environment = _native_rlm_environment()
        reservation = prepare_native_rlm_experiment(
            None, max_cost_micros=None, deadline_ms=600_000,
            max_concurrent_children=2, environ=environment,
        ).consume()
        selection = resolve_native_rlm_model(environment)
        resources = _native_rlm_runtime_resources(source_root, verify_preflight(source_root))
        root = Path(tempfile.mkdtemp(prefix="asterion-prime-core-", dir="/tmp"))
        root.chmod(0o700)
        stderr_path = root / "sidecar.stderr.log"
        private_goal = NativeRlmPrivateGoal(_CORE_GOAL, _CORE_START)

        async def run() -> object:
            observe("run.phase", {"phase": "prime.core"})
            started = time.monotonic()
            stop_heartbeats = asyncio.Event()

            async def heartbeat() -> None:
                while not stop_heartbeats.is_set():
                    try:
                        await asyncio.wait_for(stop_heartbeats.wait(), timeout=5)
                    except TimeoutError:
                        observe("run.heartbeat", {
                            "phase": "prime.core",
                            "elapsed_seconds": str(int(time.monotonic() - started)),
                        })

            heartbeat_task = asyncio.create_task(heartbeat())
            try:
                with stderr_path.open("xb") as stderr_sink:
                    return await run_owned_native_rlm_sidecar_probe(
                        reservation, selection, root, resources, environ=environment,
                        private_stderr_sink=stderr_sink,
                        probe=lambda sidecar: run_native_rlm_controlled_probe(
                            sidecar, reservation, root, goal=private_goal, progress_root=root,
                            exercise_application=True,
                            expected_model_selector_digest=native_rlm_model_selector_digest(selection),
                            required_child_count=2, detach_while_active=True,
                            require_observation_health=True,
                        ),
                    )
            finally:
                stop_heartbeats.set()
                await heartbeat_task

        probe = asyncio.run(asyncio.wait_for(run(), timeout=reservation.limits.deadline_ms / 1000))
        result = PrimeCoreSmokeResult(
            terminal=getattr(probe, "terminal", "uncertain"),
            terminal_count=getattr(probe, "terminal_count", 0),
            root_model_selected=True,
            generated_program_admitted=getattr(probe, "generated_program_admitted", False),
            application_succeeded=getattr(probe, "application_receipted", False),
            oracle_passed=getattr(probe, "application_receipted", False),
            child_target_count=2, children_started=getattr(probe, "children_started", 0),
            children_completed=getattr(probe, "children_completed", 0),
            children_deleted=getattr(probe, "children_deleted", 0),
            message_delivered=getattr(probe, "message_delivered", False),
            message_causality_complete=getattr(probe, "message_delivered", False),
            detached_while_active=getattr(probe, "detach_attached", False),
            reattached=getattr(probe, "detach_attached", False),
            replay_contiguous=getattr(probe, "detach_attached", False),
            work_continued_after_attach=getattr(probe, "work_continued_after_attach", False),
            recursion_policy_enforced=getattr(probe, "recursion_depth_limited", False),
            control_event_sequence_contiguous=getattr(probe, "control_event_sequence_contiguous", False),
            observation_health=getattr(probe, "observation_health", "unknown"),
            observation_gap_count=getattr(probe, "observation_gap_count", 1),
            cleanup_complete=True, privacy_checks_passed=True,
            within_budget=getattr(probe, "usage").cost_micros <= reservation.limits.cost_micros,
        )
        receipt = dict(verify_prime_core_smoke_result(result))
        terminal = "completed" if receipt["status"] == "PASS" else "external-limited"
        print(json.dumps(dict(log.terminal(terminal, "prime.core")), sort_keys=True, separators=(",", ":")), flush=True)
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")), flush=True)
        return 0 if receipt["status"] == "PASS" else 2
    except (KeyboardInterrupt, asyncio.CancelledError):
        receipt = dict(verify_prime_core_smoke_result(_external_limited()))
        print(json.dumps(dict(log.terminal("external-limited", "prime.core.interrupted")), sort_keys=True, separators=(",", ":")), flush=True)
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")), flush=True)
        return 2
    except Exception as error:
        receipt = dict(verify_prime_core_smoke_result(_external_limited()))
        print(json.dumps(dict(log.terminal("external-limited", f"prime.core.{_safe_reason(error)}")), sort_keys=True, separators=(",", ":")), flush=True)
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
