"""Start one bounded README-style Prime RLM smoke without checkpoint maintenance."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from asterion.runtime.observation import RunObservationLog
from tools.prime_native_rlm_experiment import (
    native_rlm_model_selector_digest,
    prepare_native_rlm_experiment,
    resolve_native_rlm_model,
    run_native_rlm_controlled_probe,
    run_native_rlm_experiment,
    run_owned_native_rlm_sidecar_probe,
)
from tools.verify_prime_loop import (
    _native_rlm_failure_class,
    _native_rlm_environment,
    _native_rlm_runtime_resources,
    verify_preflight,
)


def _write_result(path: Path, result: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True, separators=(",", ":"))
    os.replace(temporary, path)


def main() -> int:
    result_path = Path(sys.argv[1]) if len(sys.argv) == 2 else None
    log = RunObservationLog(Path("runs/observations"), "prime-readme-rlm-smoke")
    phase = "prime.launch"
    root: Path | None = None
    stderr_path: Path | None = None
    def observe(event_type: str, payload: dict[str, str] | None = None) -> None:
        event = log.record(event_type, payload)
        print(json.dumps(dict(event), sort_keys=True, separators=(",", ":")), flush=True)

    observe("run.started")
    source_root = Path("3th-party/prime-agent")
    try:
        phase = "prime.preflight"
        observe("run.phase", {"phase": phase})
        environment = _native_rlm_environment()
        reservation = prepare_native_rlm_experiment(
            None, max_cost_micros=None, deadline_ms=600_000, environ=environment
        )
        selection = resolve_native_rlm_model(environment)
        resources = _native_rlm_runtime_resources(
            source_root, verify_preflight(source_root)
        )
        root = Path(tempfile.mkdtemp(prefix="asterion-readme-rlm-", dir="/tmp"))
        root.chmod(0o700)
        stderr_path = root / "sidecar.stderr.log"

        async def runner(active: object) -> object:
            nonlocal phase
            phase = "prime.rlm"
            observe("run.phase", {"phase": phase})
            with stderr_path.open("xb") as stderr_sink:
                return await run_owned_native_rlm_sidecar_probe(
                    active,
                    selection,
                    root,
                    resources,
                    environ=environment,
                    private_stderr_sink=stderr_sink,
                    probe=lambda sidecar: run_native_rlm_controlled_probe(
                    sidecar,
                    active,
                    root,
                    exercise_application=False,
                    exercise_checkpoint=False,
                    exercise_cancellation=False,
                    exercise_budget_probe=False,
                    expected_model_selector_digest=native_rlm_model_selector_digest(
                        selection
                    ),
                    ),
                )

        result = asyncio.run(run_native_rlm_experiment(reservation, runner))
        output = {"status": result["status"], "scenario": "readme-rlm-smoke"}
        if result_path is not None:
            _write_result(result_path, output)
        print(json.dumps(dict(log.terminal("completed", "prime.rlm"))), flush=True)
        print(json.dumps(output))
        return 0
    except Exception as error:
        reason = phase
        if root is not None:
            try:
                boundary = (root / "asterion-native-boundary").read_text(
                    encoding="ascii"
                ).strip()
                if boundary in {
                    "daemon-plan", "daemon-start", "lifecycle-server",
                    "operation-host", "sidecar-start", "probe", "cleanup",
                }:
                    reason = f"{phase}.{boundary}"
            except OSError:
                pass
        classified = _native_rlm_failure_class(stderr_path, safe_error=str(error))
        if classified not in {"unavailable", "unknown"}:
            reason = f"{phase}.{classified}"
        output = {"status": "External-limited", "scenario": "readme-rlm-smoke"}
        if result_path is not None:
            _write_result(result_path, output)
        print(json.dumps(dict(log.terminal("external-limited", reason))), flush=True)
        print(json.dumps(output))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
