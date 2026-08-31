"""Run provider-free, external preflight, or explicitly bounded Prime gates."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from dotenv import dotenv_values

from asterion.control.authority import (
    AuthorityEnvelope,
    AuthorityError,
    BudgetLimit,
    PortfolioGrant,
)

try:
    from tools.setup_prime_agent import (
        PrimeSetupError,
        derive_prime_rlm_runtime,
        verify_prime_source,
    )
except ModuleNotFoundError:  # Direct ``python tools/verify_prime_loop.py`` execution.
    from setup_prime_agent import PrimeSetupError, derive_prime_rlm_runtime, verify_prime_source


BOUNDED_AUTHORIZATION_FORMAT = "asterion.prime-bounded-authorization/v1"
EXPECTED_SCENARIO_IDS = (
    "prime-loop-application",
    "prime-loop-child",
    "prime-loop-detach-attach",
    "prime-loop-checkpoint",
    "prime-loop-gateway-crash",
    "prime-loop-supervisor-crash",
    "prime-loop-worker-crash",
    "prime-loop-cancel",
    "prime-loop-budget",
    "prime-loop-redaction",
)
REQUIRED_BOUNDED_OPERATIONS = frozenset(
    {
        "application.invoke",
        "checkpoint.create",
        "child.cancel",
        "child.message",
        "child.spawn",
        "goal.complete",
        "goal.fail",
    }
)
REQUIRED_BOUNDED_RLM_OPERATIONS = frozenset(
    {"rlm.child.delete", "rlm.child.message", "rlm.child.spawn"}
)
_DEFAULT_BOUNDED_MAX_COST_MICROS = 500_000


class PrimeVerificationError(RuntimeError):
    """Raised with a fixed public-safe verification failure."""


class PrimeExternalLimit(PrimeVerificationError):
    """Raised when an implemented external boundary is not locally ready."""


class ScenarioResult(Protocol):
    @property
    def scenario_id(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def provider_operations(self) -> int: ...

    @property
    def application_operations(self) -> int: ...


def verify_provider_free(
    run_scenarios: Callable[[], Sequence[ScenarioResult]] | None = None,
) -> Mapping[str, object]:
    if run_scenarios is None:
        project_root = str(Path(__file__).resolve().parents[1])
        added_path = project_root not in sys.path
        if added_path:
            sys.path.insert(0, project_root)
        try:
            module = importlib.import_module("tests.test_prime_verified_loop")
            run_prime_loop_scenarios = module.run_prime_loop_scenarios
        finally:
            if added_path:
                sys.path.remove(project_root)

        def run_default_scenarios() -> Sequence[ScenarioResult]:
            return run_prime_loop_scenarios(fake_prime=True)

        run_scenarios = run_default_scenarios
    try:
        results = tuple(run_scenarios())
        ids = tuple(result.scenario_id for result in results)
        provider_operations = sum(result.provider_operations for result in results)
        application_operations = sum(
            result.application_operations for result in results
        )
        if (
            ids != EXPECTED_SCENARIO_IDS
            or any(result.status != "PASS" for result in results)
            or provider_operations != 0
        ):
            raise ValueError
    except Exception:
        raise PrimeVerificationError("Prime provider-free loop did not pass") from None
    return {
        "status": "PASS",
        "level": "provider-free",
        "scenario_count": len(results),
        "provider_operations": provider_operations,
        "application_operations": application_operations,
        "full_dataset_ran": False,
    }


def load_bounded_authority(
    path: Path,
    *,
    max_cost_micros: int,
    now_ms: int | None = None,
) -> AuthorityEnvelope:
    try:
        if (
            isinstance(max_cost_micros, bool)
            or not isinstance(max_cost_micros, int)
            or max_cost_micros < 1
        ):
            raise TypeError
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {"format", "authority"}:
            raise TypeError
        if value["format"] != BOUNDED_AUTHORIZATION_FORMAT:
            raise TypeError
        raw = value["authority"]
        if not isinstance(raw, dict) or set(raw) != {
            "authority_id",
            "revision",
            "allowed_portfolio",
            "allowed_operations",
            "budget_limit",
            "expires_at_ms",
            "max_action_deadline_ms",
            "max_recursion_depth",
            "max_concurrent_children",
            "execution_domain",
            "host_service_grants",
            "cancelled",
        }:
            raise TypeError
        portfolio = raw["allowed_portfolio"]
        budget = raw["budget_limit"]
        if not isinstance(portfolio, list) or not isinstance(budget, dict):
            raise TypeError
        envelope = AuthorityEnvelope(
            authority_id=raw["authority_id"],
            revision=raw["revision"],
            allowed_portfolio=tuple(PortfolioGrant(**item) for item in portfolio),
            allowed_operations=tuple(raw["allowed_operations"]),
            budget_limit=BudgetLimit(**budget),
            expires_at_ms=raw["expires_at_ms"],
            max_action_deadline_ms=raw["max_action_deadline_ms"],
            max_recursion_depth=raw["max_recursion_depth"],
            max_concurrent_children=raw["max_concurrent_children"],
            execution_domain=raw["execution_domain"],
            host_service_grants=tuple(raw["host_service_grants"]),
            cancelled=raw["cancelled"],
        )
        current = int(time.time() * 1000) if now_ms is None else now_ms
        limit = envelope.budget_limit
        if (
            envelope.execution_domain != "trusted-local"
            or envelope.cancelled
            or envelope.expires_at_ms <= current
            or envelope.max_recursion_depth > 1
            or envelope.max_concurrent_children > 1
            or envelope.max_concurrent_children < 1
            or not REQUIRED_BOUNDED_OPERATIONS.issubset(envelope.allowed_operations)
            or any(
                value < 1
                for value in (
                    limit.controller_tokens,
                    limit.application_tokens,
                    limit.child_tokens,
                    limit.aggregate_tokens,
                    limit.cost_micros,
                )
            )
            or limit.aggregate_tokens
            < limit.controller_tokens + limit.application_tokens + limit.child_tokens
            or limit.cost_micros > max_cost_micros
        ):
            raise TypeError
        return envelope
    except (
        OSError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        AuthorityError,
    ):
        raise PrimeVerificationError(
            "Prime bounded authorization is invalid or inconsistent"
        ) from None


def load_bounded_rlm_authority(
    path: Path,
    *,
    max_cost_micros: int,
    now_ms: int | None = None,
) -> AuthorityEnvelope:
    """Load only the one-child, one-depth native RLM authorization subset."""
    try:
        envelope = load_bounded_authority(
            path, max_cost_micros=max_cost_micros, now_ms=now_ms
        )
        if (
            not REQUIRED_BOUNDED_RLM_OPERATIONS.issubset(
                envelope.allowed_operations
            )
            or envelope.max_recursion_depth != 1
            or envelope.max_concurrent_children != 1
        ):
            raise ValueError
        return envelope
    except PrimeVerificationError:
        raise
    except (TypeError, ValueError):
        raise PrimeVerificationError(
            "Prime bounded authorization is invalid or inconsistent"
        ) from None


_HANDSHAKE_SCRIPT = r"""
import { pathToFileURL } from 'node:url';
const socketPath = process.argv[1];
const entry = process.argv[2];
const { PrimeDaemonClient, PRIME_DAEMON_PROTOCOL_NAME } = await import(pathToFileURL(entry));
const client = new PrimeDaemonClient({
  clientId: 'asterion-preflight',
  connectTimeoutMs: 3000,
  requestTimeoutMs: 3000,
});
try {
  await client.connect(socketPath);
  const hello = client.hello;
  if (hello === undefined) throw new Error('Prime daemon hello is unavailable');
  console.log(JSON.stringify({
    protocol_name: PRIME_DAEMON_PROTOCOL_NAME,
    protocol_version: hello.protocolVersion,
    schema_id: hello.schemaId,
    schema_revision: hello.schemaRevision,
    app_version: hello.appVersion,
    runtime_build_id: hello.runtimeBuildId,
  }));
} finally {
  client.close();
}
"""


def verify_preflight(source_root: Path) -> Mapping[str, object]:
    node = _prime_node_executable()
    try:
        source_report = verify_prime_source(source_root, node_executable=str(node))
    except PrimeSetupError as error:
        raise PrimeExternalLimit(str(error)) from None
    source = source_root.resolve()
    try:
        daemon_entry = derive_prime_rlm_runtime(source)
    except PrimeSetupError as error:
        raise PrimeExternalLimit(str(error)) from None
    package_root = (
        Path(__file__).resolve().parents[1] / "packages/typescript/prime-gateway"
    )
    gateway_entry = package_root / "dist/src/index.js"
    if not daemon_entry.is_file():
        raise PrimeExternalLimit("Prime dependencies are not installed")
    build = _command(("npm", "run", "build"), package_root, _safe_environment())
    if build.returncode != 0 or not gateway_entry.is_file():
        raise PrimeExternalLimit("Prime gateway build is unavailable")
    with tempfile.TemporaryDirectory(
        prefix="asterion-prime-preflight-", dir="/tmp"
    ) as temporary:
        private_root = Path(temporary)
        socket_path = private_root / "prime.sock"
        environment = _safe_environment(private_home=private_root / "home")
        daemon = _start_prime_daemon(
            (
                str(node),
                str(daemon_entry),
                "--mode",
                "daemon",
                "--daemon-socket",
                str(socket_path),
            ),
            source,
            environment,
        )
        try:
            _wait_for_prime_daemon(socket_path, daemon)
            handshake = _command(
                (
                    str(node),
                    "--input-type=module",
                    "-e",
                    _HANDSHAKE_SCRIPT,
                    str(socket_path),
                    str(gateway_entry),
                ),
                package_root,
                environment,
            )
            if handshake.returncode != 0:
                raise PrimeExternalLimit("Prime daemon handshake did not pass")
            payload = json.loads(handshake.stdout)
            if (
                not isinstance(payload, dict)
                or set(payload)
                != {
                    "protocol_name",
                    "protocol_version",
                    "schema_id",
                    "schema_revision",
                    "app_version",
                    "runtime_build_id",
                }
                or payload["protocol_name"] != "prime-agent.daemon"
                or payload["protocol_version"] != source_report.daemon_protocol
                or payload["schema_revision"] != source_report.daemon_schema_revision
                or payload["app_version"] != source_report.package_version
                or not isinstance(payload["runtime_build_id"], str)
                or not payload["runtime_build_id"]
            ):
                raise PrimeExternalLimit("Prime daemon handshake did not pass")
        except (json.JSONDecodeError, TypeError, ValueError):
            raise PrimeExternalLimit("Prime daemon handshake did not pass") from None
        finally:
            _stop_prime_daemon(daemon)
    return {
        "status": "PASS",
        "level": "preflight",
        "source_commit": source_report.source_commit,
        "package_version": source_report.package_version,
        "daemon_protocol": source_report.daemon_protocol,
        "daemon_schema_revision": source_report.daemon_schema_revision,
        "runtime_build_id": payload["runtime_build_id"],
        "provider_operations": 0,
        "application_operations": 0,
        "full_dataset_ran": False,
    }


def _safe_environment(private_home: Path | None = None) -> dict[str, str]:
    environment: dict[str, str] = {}
    for key in ("PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR"):
        value = os.environ.get(key)
        if value:
            environment[key] = value
    if private_home is not None:
        private_home.mkdir(mode=0o700, parents=True, exist_ok=True)
        environment["HOME"] = str(private_home)
    return environment


def _prime_node_executable() -> Path:
    """Select an already-installed Node 22 without changing global Node state."""
    configured = os.environ.get("ASTERION_PRIME_NODE")
    candidates = [] if not configured else [Path(configured)]
    try:
        npm_environment = _safe_environment()
        home = os.environ.get("HOME")
        if home:
            npm_environment["HOME"] = home
        resolved = subprocess.run(
            (
                "npm",
                "exec",
                "--offline",
                "--yes",
                "--package=node@22",
                "--",
                "which",
                "node",
            ),
            cwd=Path(__file__).resolve().parents[1],
            env=npm_environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if resolved.returncode == 0 and resolved.stdout.strip():
            candidates.append(Path(resolved.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        try:
            version = subprocess.run(
                (str(candidate), "--version"),
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if version.returncode == 0 and version.stdout.startswith("v22."):
                return candidate.resolve()
        except (OSError, subprocess.SubprocessError):
            continue
    raise PrimeExternalLimit("Prime setup requires compatible Node.js 22.8.0 through 22.x")


def _start_prime_daemon(
    command: tuple[str, ...], cwd: Path, environment: dict[str, str]
) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        raise PrimeExternalLimit("Prime daemon preflight could not start") from None


def _wait_for_prime_daemon(
    socket_path: Path,
    daemon: subprocess.Popen[bytes],
    *,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if socket_path.exists():
            return
        if daemon.poll() is not None:
            raise PrimeExternalLimit("Prime daemon preflight could not start")
        time.sleep(0.025)
    raise PrimeExternalLimit("Prime daemon preflight could not start")


def _stop_prime_daemon(daemon: subprocess.Popen[bytes]) -> None:
    if daemon.poll() is not None:
        return
    try:
        daemon.terminate()
        daemon.wait(timeout=5)
    except subprocess.TimeoutExpired:
        daemon.kill()
        try:
            daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise PrimeExternalLimit(
                "Prime daemon preflight could not stop"
            ) from None
    except (OSError, subprocess.SubprocessError):
        raise PrimeExternalLimit("Prime daemon preflight could not stop") from None


def _command(
    command: tuple[str, ...], cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        raise PrimeExternalLimit("Prime external preflight is unavailable") from None


def _bounded_external_limit(
    source_root: Path,
    authority_path: Path | None,
    max_cost_micros: int | None,
) -> Mapping[str, object]:
    if authority_path is not None:
        load_bounded_rlm_authority(
            authority_path,
            max_cost_micros=(
                _DEFAULT_BOUNDED_MAX_COST_MICROS
                if max_cost_micros is None
                else max_cost_micros
            ),
        )
    report = _native_rlm_bounded_external_limit(
        source_root,
        authority_path,
        max_cost_micros,
        _default_native_rlm_evidence_root(),
    )
    if report.get("status") != "PASS":
        raise PrimeExternalLimit("Prime bounded execution did not complete")
    return {
        "status": "PASS",
        "level": "bounded",
        "terminal": "completed",
        "provider_operations": 1,
        "application_operations": 1,
        "full_dataset_ran": False,
    }


def _native_rlm_public_usage(value: object) -> dict[str, int]:
    """Project only finite, body-free counters from a native probe receipt."""

    try:
        if not isinstance(value, Mapping) or frozenset(value) not in {
            frozenset(("aggregate_tokens", "cost_micros")),
            frozenset((
                "controller_tokens",
                "application_tokens",
                "child_tokens",
                "aggregate_tokens",
                "cost_micros",
            )),
        }:
            raise ValueError
        aggregate_tokens = value["aggregate_tokens"]
        cost_micros = value["cost_micros"]
        if (
            isinstance(aggregate_tokens, bool)
            or not isinstance(aggregate_tokens, int)
            or aggregate_tokens < 1
            or isinstance(cost_micros, bool)
            or not isinstance(cost_micros, int)
            or cost_micros < 0
        ):
            raise ValueError
        if "controller_tokens" in value:
            components = (
                value["controller_tokens"],
                value["application_tokens"],
                value["child_tokens"],
            )
            if (
                any(
                    isinstance(component, bool)
                    or not isinstance(component, int)
                    or component < 0
                    for component in components
                )
                or sum(components) != aggregate_tokens
            ):
                raise ValueError
        return {
            "aggregate_tokens": aggregate_tokens,
            "cost_micros": cost_micros,
        }
    except (KeyError, TypeError, ValueError):
        raise PrimeVerificationError("Prime native RLM usage is invalid") from None


def _native_rlm_bounded_external_limit(
    source_root: Path,
    authority_path: Path | None,
    max_cost_micros: int | None,
    private_evidence_root: Path,
) -> Mapping[str, object]:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    try:
        from tools.prime_native_rlm_experiment import (
            PrimeRlmExperimentError,
            native_rlm_model_selector_digest,
            prepare_native_rlm_experiment,
            resolve_native_rlm_model,
            run_native_rlm_controlled_probe,
            run_native_rlm_maintenance_probe,
            run_native_rlm_experiment,
            run_owned_native_rlm_sidecar_probe,
            write_native_rlm_experiment_receipt,
            write_native_rlm_model_evidence_receipt,
        )
        from tools.prime_bounded_loop_experiment import (
            assertions_from_native_probe_observation,
            reduce_native_probe_observation,
            write_bounded_loop_receipt,
        )
    except ModuleNotFoundError:
        from prime_native_rlm_experiment import (
            PrimeRlmExperimentError,
            native_rlm_model_selector_digest,
            prepare_native_rlm_experiment,
            resolve_native_rlm_model,
            run_native_rlm_controlled_probe,
            run_native_rlm_maintenance_probe,
            run_native_rlm_experiment,
            run_owned_native_rlm_sidecar_probe,
            write_native_rlm_experiment_receipt,
            write_native_rlm_model_evidence_receipt,
        )
        from prime_bounded_loop_experiment import (
            assertions_from_native_probe_observation,
            reduce_native_probe_observation,
            write_bounded_loop_receipt,
        )

    if (
        not private_evidence_root.is_dir()
        or private_evidence_root.is_symlink()
    ):
        raise PrimeVerificationError("Prime native RLM evidence root is invalid")
    try:
        evidence_run_root = Path(
            tempfile.mkdtemp(prefix="run-", dir=private_evidence_root)
        )
        evidence_run_root.chmod(0o700)
    except OSError:
        raise PrimeVerificationError("Prime native RLM evidence root is invalid") from None
    stage = "preflight"
    stderr_path: Path | None = None
    run_root: Path | None = None
    preflight = verify_preflight(source_root)
    stage = "environment"
    environment = _native_rlm_environment()
    try:
        stage = "authorization"
        reservation = prepare_native_rlm_experiment(
            authority_path,
            max_cost_micros=max_cost_micros,
            deadline_ms=600_000,
            environ=environment,
        )
        selection = resolve_native_rlm_model(environment)
        stage = "runtime"
        resources = _native_rlm_runtime_resources(source_root, preflight)
        stage = "workspace"
        # Unix-domain socket paths are bounded well below a typical repository
        # path. Keep live Prime IPC under a short private /tmp directory; only
        # the redacted receipt belongs in the operator-selected evidence root.
        run_root = Path(tempfile.mkdtemp(prefix="asterion-rlm-", dir="/tmp"))
        run_root.chmod(0o700)
        consumed: object | None = None
        observation: object | None = None

        stderr_path = run_root / "sidecar.stderr.log"
        with stderr_path.open("xb") as stderr_sink:
            async def runner(active: object) -> object:
                nonlocal consumed, observation
                consumed = active
                maintenance_root = run_root / "maintenance"
                maintenance_root.mkdir(mode=0o700)
                maintenance = await run_owned_native_rlm_sidecar_probe(
                    active,  # type: ignore[arg-type]
                    selection,
                    maintenance_root,
                    resources,
                    environ=environment,
                    session_id="native-rlm-maintenance",
                    probe=lambda sidecar: run_native_rlm_maintenance_probe(
                        sidecar,
                        active,  # type: ignore[arg-type]
                        maintenance_root,
                    ),
                    private_stderr_sink=stderr_sink,
                )
                (evidence_run_root / "native-rlm-runner-stage").write_text(
                    "maintenance-return\n", encoding="ascii"
                )
                rlm_root = run_root / "rlm"
                rlm_root.mkdir(mode=0o700)
                (evidence_run_root / "native-rlm-runner-stage").write_text(
                    "observation-root\n", encoding="ascii"
                )
                (evidence_run_root / "native-rlm-progress.json").write_text(
                    '{"format":"asterion.prime-native-rlm-progress/v1","stage":"observation-starting"}\n',
                    encoding="ascii",
                )
                (evidence_run_root / "native-rlm-runner-stage").write_text(
                    "observation-call\n", encoding="ascii"
                )
                observation = await run_owned_native_rlm_sidecar_probe(
                    active,  # type: ignore[arg-type]
                    selection,
                    rlm_root,
                    resources,
                    environ=environment,
                    probe=lambda sidecar: run_native_rlm_controlled_probe(
                        sidecar,
                        active,
                        rlm_root,
                        progress_root=evidence_run_root,  # type: ignore[arg-type]
                        exercise_application=True,
                        exercise_checkpoint=False,
                        exercise_cancellation=False,
                        exercise_budget_probe=True,
                        expected_model_selector_digest=native_rlm_model_selector_digest(
                            selection
                        ),
                    ),
                    private_stderr_sink=stderr_sink,
                )
                observation = replace(
                    observation,
                    checkpoint_recovered=maintenance.checkpoint_recovered,
                    cancelled=maintenance.cancelled,
                    observed_event_types=(
                        *maintenance.observed_event_types,
                        *observation.observed_event_types,
                    ),
                    causal_identities={
                        **maintenance.causal_identities,
                        **observation.causal_identities,
                    },
                )
                return observation

            stage = "execution"
            report = asyncio.run(run_native_rlm_experiment(reservation, runner))
        if consumed is None or observation is None:
            raise ValueError
        stage = "receipt"
        receipt = write_native_rlm_experiment_receipt(
            evidence_run_root,
            consumed,  # type: ignore[arg-type]
            terminal=observation.terminal,
            child_started=observation.child_started,
            message_delivered=observation.message_delivered,
            child_deleted=observation.child_deleted,
            usage=observation.usage,
            checkpoint_recovered=observation.checkpoint_recovered,
            detach_attached=observation.detach_attached,
            cancelled=observation.cancelled,
            budget_limited=observation.budget_limited,
        )
        bounded_receipt = reduce_native_probe_observation(
            session_events=observation.observed_event_types,
            application_receipted=observation.application_receipted,
            child_completed=(
                observation.terminal == "completed"
                and observation.child_started
                and observation.child_deleted
            ),
            detached_attached=observation.detach_attached,
            checkpoint_recovered=observation.checkpoint_recovered,
            cancelled=observation.cancelled,
            budget_limited=observation.budget_limited,
            usage={"aggregate_tokens": observation.usage.aggregate_tokens},
            causal_identities=observation.causal_identities,
        )
        write_bounded_loop_receipt(
            evidence_run_root,
            assertions_from_native_probe_observation(
                session_events=observation.observed_event_types,
                application_receipted=observation.application_receipted,
                child_completed=(observation.terminal == "completed" and observation.child_started and observation.child_deleted),
                detached_attached=observation.detach_attached,
                checkpoint_recovered=observation.checkpoint_recovered,
                cancelled=observation.cancelled,
                budget_limited=observation.budget_limited,
            ),
            usage=bounded_receipt["usage"],
            causal_digests=bounded_receipt["causal_digests"],
        )
        model_receipt = write_native_rlm_model_evidence_receipt(
            evidence_run_root,
            consumed,  # type: ignore[arg-type]
            {
                "child_model_selected": observation.child_model_selected,
                "generated_program_admitted": observation.generated_program_admitted,
                "recursion_depth_limited": observation.recursion_depth_limited,
            },
        )
        return {
            "status": report["status"],
            "level": "native-rlm-bounded",
            "terminal": report["terminal"],
            "child_started": receipt["child_started"],
            "message_delivered": receipt["message_delivered"],
            "child_deleted": receipt["child_deleted"],
            "checkpoint_recovered": receipt["checkpoint_recovered"],
            "detach_attached": receipt["detach_attached"],
            "cancelled": receipt["cancelled"],
            "budget_limited": receipt["budget_limited"],
            "child_model_selected": model_receipt["child_model_selected"],
            "generated_program_admitted": model_receipt[
                "generated_program_admitted"
            ],
            "recursion_depth_limited": model_receipt["recursion_depth_limited"],
            "provider_operations": 1,
            "application_operations": 1,
            "usage": _native_rlm_public_usage(receipt["usage"]),
            "full_dataset_ran": False,
        }
    except PrimeRlmExperimentError as error:
        _write_native_rlm_external_limit_evidence(
            evidence_run_root,
            stage,
            stderr_path=stderr_path,
            safe_error=str(error),
            progress_path=(
                run_root / "rlm" / "native-rlm-progress.json"
                if run_root is not None
                else None
            ),
        )
        raise PrimeExternalLimit(str(error)) from None
    except (OSError, RuntimeError, TypeError, ValueError):
        _write_native_rlm_external_limit_evidence(
            evidence_run_root, stage, stderr_path=stderr_path
        )
        raise PrimeExternalLimit(
            f"Prime native RLM probe {stage} did not complete"
        ) from None


def _write_native_rlm_external_limit_evidence(
    root: Path,
    stage: str,
    *,
    stderr_path: Path | None = None,
    safe_error: str | None = None,
    progress_path: Path | None = None,
) -> None:
    """Persist only the safe terminal category when a bounded probe cannot finish."""

    if not isinstance(root, Path) or not root.is_dir() or not isinstance(stage, str):
        return
    payload = {
        "format": "asterion.prime-native-rlm-external-limit/v1",
        "failure_class": _native_rlm_failure_class(stderr_path, safe_error=safe_error, progress_path=progress_path),
        "stage": stage if stage in {"authorization", "runtime", "workspace", "execution", "receipt"} else "preflight",
        "status": "External-limited",
    }
    target = root / "native-rlm-external-limit.json"
    temporary = root / ".native-rlm-external-limit.tmp"
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        os.replace(temporary, target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _native_rlm_failure_class(
    stderr_path: Path | None, *, safe_error: str | None = None, progress_path: Path | None = None
) -> str:
    """Classify private sidecar diagnostics without retaining their content."""
    if isinstance(safe_error, str) and safe_error.startswith(
        "Native RLM controlled probe start "
    ):
        # A best-effort cancellation during outer cleanup is expected after a
        # root-start failure.  Preserve the earlier public stage instead of
        # reporting that cleanup's terminal event as its cause.
        return "root_start"
    if isinstance(progress_path, Path):
        try:
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            if (
                isinstance(progress, Mapping)
                and progress.get("format") == "asterion.prime-native-rlm-progress/v1"
                and progress.get("stage") == "start"
            ):
                return "root_start"
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    private_category: str | None = None
    if isinstance(stderr_path, Path):
        try:
            content = stderr_path.read_bytes()[-65_536:].lower()
        except OSError:
            content = b""
        checkpoint_stages = (
            "idle",
            "prepare",
            "stop",
            "relaunch",
            "attach",
            "recover",
            "capsule",
            "manager-open",
            "manager-create",
        )
        attach_failure = next(
            (
                category
                for category in ("validation", "connection", "timeout", "response")
                if f"asterion-prime-checkpoint-attach-failed:{category}".encode() in content
            ),
            None,
        )
        recovery_failure = next(
            (
                category
                for category in (
                    "identity", "protocol", "replay", "snapshot", "sequence",
                    "summary", "goal", "cursor", "response",
                )
                if f"asterion-prime-checkpoint-recovery-invalid:{category}".encode()
                in content
            ),
            None,
        )
        shutdown_failure = next(
            (
                category
                for category in ("connection", "response")
                if f"asterion-prime-checkpoint-shutdown-failed:{category}".encode()
                in content
            ),
            None,
        )
        stop_stage = max(
            (
                (content.rfind(f"asterion-prime-checkpoint-stop:{stage}".encode()), stage)
                for stage in ("shim", "shutdown")
                if f"asterion-prime-checkpoint-stop:{stage}".encode() in content
            ),
            default=(-1, None),
        )[1]
        checkpoint_stage = max(
            (
                (content.rfind(f"asterion-prime-checkpoint-stage:{stage}".encode()), stage)
                for stage in checkpoint_stages
                if f"asterion-prime-checkpoint-stage:{stage}".encode() in content
            ),
            default=(-1, None),
        )[1]
        lifecycle_stage = max(
            (
                (content.rfind(f"asterion-prime-checkpoint-lifecycle:{stage}".encode()), stage)
                for stage in ("connect", "request", "accepted", "response", "complete", "unavailable", "refused", "denied", "failed")
                if f"asterion-prime-checkpoint-lifecycle:{stage}".encode() in content
            ),
            default=(-1, None),
        )[1]
        maintenance_completed = (
            b"asterion-prime-checkpoint-stage:capsule" in content
            and b"asterion-prime-gateway-cancel-stage:terminal-appended" in content
        )
        if maintenance_completed and (
            recovery_failure is None
            and attach_failure is None
            and shutdown_failure is None
            and b"asterion-prime-gateway-checkpoint-stage:failed" not in content
        ):
            private_category = "observation_unclassified"
        elif recovery_failure is not None:
            private_category = "checkpoint_recovery_" + recovery_failure
        elif attach_failure is not None:
            private_category = "checkpoint_attach_" + attach_failure
        elif shutdown_failure is not None:
            private_category = "checkpoint_shutdown_" + shutdown_failure
        elif stop_stage is not None:
            private_category = "checkpoint_stop_" + stop_stage
        elif b"asterion-prime-checkpoint-coordinator-failed:" in content:
            coordinator_phase = next(
                (phase for phase in ("manifest", "prepare", "shutdown", "fence", "start", "restore", "coordinator")
                 if f"asterion-prime-checkpoint-coordinator-failed:{phase}".encode() in content),
                "coordinator",
            )
            private_category = "checkpoint_coordinator_" + coordinator_phase
        elif b"asterion-prime-checkpoint-lifecycle-failed" in content:
            private_category = "checkpoint_lifecycle"
        elif b"asterion-prime-checkpoint-runtime-stop-failed" in content:
            private_category = "checkpoint_runtime_stop"
        elif lifecycle_stage is not None:
            private_category = "checkpoint_lifecycle_" + lifecycle_stage
        elif checkpoint_stage is not None:
            private_category = "checkpoint_" + checkpoint_stage
        elif b"asterion-prime-gateway-checkpoint-stage:failed" in content:
            private_category = "gateway_checkpoint_failed"
        elif b"asterion-prime-gateway-checkpoint-stage:started" in content:
            private_category = "gateway_checkpoint_started"
        elif b"asterion-prime-gateway-checkpoint-stage:scheduled" in content:
            private_category = "gateway_checkpoint_scheduled"
        elif b"asterion-prime-gateway-cancel-stage:terminal-appended" in content:
            private_category = "gateway_cancel_terminal_appended"
        elif b"asterion-prime-gateway-cancel-stage:goal-updated" in content:
            private_category = "gateway_cancel_goal_updated"
        elif b"asterion-prime-skill-request:dispatch" in content:
            private_category = "skill_dispatch"
        elif b"asterion-prime-cancel-stage:kill-confirmed" in content:
            private_category = "cancel_kill_confirmed"
        elif b"asterion-prime-cancel-stage:abort" in content:
            private_category = "cancel_abort"
        elif b"asterion-prime-cancel-stage:kill" in content:
            private_category = "cancel_kill"
        elif b"asterion-prime-sidecar-failed:checkpoint-request" in content:
            private_category = "sidecar_checkpoint_request"
        elif b"asterion-prime-sidecar-failed:private.read" in content:
            private_category = "sidecar_private_read"
        elif b"asterion-prime-sidecar-failed:action-resolve" in content:
            private_category = "sidecar_action_resolve"
        elif b"asterion-prime-sidecar-failed:session-cancel" in content:
            private_category = "sidecar_session_cancel"
        elif b"asterion-prime-sidecar-failed:session-create" in content:
            private_category = "sidecar_session_create"
        elif b"asterion-prime-sidecar-failed:input-submit" in content:
            private_category = "sidecar_input_submit"
        elif b"asterion-prime-sidecar-failed:events" in content:
            private_category = "sidecar_events"
        elif b"asterion-prime-sidecar-failed:authority.update" in content:
            private_category = "sidecar_authority_update"
        elif b"asterion-prime-sidecar-failed:command.accept" in content:
            private_category = "sidecar_command_accept"
        elif b"asterion-prime-sidecar-stage:" in content:
            sidecar_stage = next(
                (
                    stage
                    for stage in ("descriptor", "sidecar", "serve", "close")
                    if f"asterion-prime-sidecar-stage:{stage}".encode() in content
                ),
                "unknown",
            )
            private_category = "sidecar_" + sidecar_stage
        elif b"asterion-prime-sidecar-failed:" in content:
            private_category = "sidecar_request"
        elif b"asterion-prime-rlm-host-frame:" in content:
            private_category = "rlm_host_frame"
    control_categories = {
        "Native RLM controlled probe running control did not complete": "control",
        "Native RLM controlled probe running event-transition did not complete": "event_transition",
        "Native RLM controlled probe running action-admission did not complete": "action_admission",
        "Native RLM controlled probe running provider-lifecycle did not complete": "provider_lifecycle",
        "Native RLM controlled probe running event-journal did not complete": "event_journal",
        "Native RLM controlled probe running budget-report did not complete": "budget_report",
        "Native RLM controlled probe running event-invalid did not complete": "event_invalid",
    }
    if safe_error in control_categories:
        return control_categories[safe_error]
    if safe_error == "Native RLM controlled probe running event-transport did not complete":
        return private_category or "event_transport"
    if (
        isinstance(safe_error, str)
        and safe_error.startswith(
            "Native RLM controlled probe running action-admission-"
        )
        and safe_error.endswith(" did not complete")
    ):
        action_kind = safe_error.removeprefix(
            "Native RLM controlled probe running action-admission-"
        ).removesuffix(" did not complete")
        if action_kind in {"child-spawn", "child-message", "child-cancel"}:
            return "action_admission_" + action_kind.replace("-", "_")
    if (
        isinstance(safe_error, str)
        and safe_error.startswith("Native RLM controlled probe running event-transition-")
        and safe_error.endswith(" did not complete")
    ):
        event_type = safe_error.removeprefix(
            "Native RLM controlled probe running event-transition-"
        ).removesuffix(" did not complete")
        if event_type in {
            "goal-updated", "budget-reported", "action-proposed",
            "session-running", "session-completed", "session-failed",
            "session-budget-limited", "session-cancelled",
        }:
            return "event_transition_" + event_type.replace("-", "_")
    if private_category is not None:
        return private_category
    if not isinstance(stderr_path, Path):
        return "unavailable"
    patterns = (
        ("credential", (b"unauthorized", b"forbidden", b"api key", b"authentication")),
        ("model", (b"model not found", b"unknown model", b"unsupported model")),
        ("kernel", (b"kernel", b"ipython")),
        ("sidecar", (b"asterion-prime-sidecar-stage:",)),
        ("provider", (b"fetch failed", b"rate limit", b"connection", b"timeout")),
        ("protocol", (b"protocol", b"invalid request", b"schema")),
    )
    for category, markers in patterns:
        if any(marker in content for marker in markers):
            return category
    return "unknown" if content else "unavailable"


def _native_rlm_environment() -> dict[str, str]:
    """Load private experiment credentials only after explicit CLI opt-in."""
    try:
        values = {
            key: value
            for key, value in dotenv_values(Path.cwd() / ".env").items()
            if isinstance(key, str) and isinstance(value, str)
        }
        environment = dict(os.environ)
        for key in (
            "ASTERION_PRIME_EXPERIMENT_MODEL",
            "DEEPSEEK_API_KEY",
            "PRIME_AGENT_KERNEL_PYTHON",
            "PRIME_AGENT_KERNEL_VENV",
        ):
            if key in values:
                environment[key] = values[key]
        if (
            "PRIME_AGENT_KERNEL_PYTHON" not in environment
            and "PRIME_AGENT_KERNEL_VENV" not in environment
        ):
            default_kernel = Path.home() / ".prime" / "agent" / "kernel-venv" / "bin" / "python"
            if default_kernel.is_file() and os.access(default_kernel, os.X_OK):
                environment["PRIME_AGENT_KERNEL_PYTHON"] = str(default_kernel)
        return environment
    except OSError:
        raise PrimeVerificationError("Prime native RLM environment is invalid") from None


def resolve_bounded_prime_environment() -> Mapping[str, str]:
    """Resolve one selected model credential into a minimal private daemon environment."""
    try:
        project_root = str(Path(__file__).resolve().parents[1])
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        try:
            from tools.prime_native_rlm_experiment import (
                PrimeRlmExperimentError,
                resolve_native_rlm_model,
            )
        except ModuleNotFoundError:
            from prime_native_rlm_experiment import (
                PrimeRlmExperimentError,
                resolve_native_rlm_model,
            )
        inherited = _native_rlm_environment()
        selection = resolve_native_rlm_model(inherited)
        credential = inherited.get(selection.credential_env)
        if not isinstance(credential, str) or not credential:
            raise ValueError
        environment = {
            key: inherited[key]
            for key in (
                "HOME",
                "PATH",
                "ASTERION_PRIME_EXPERIMENT_MODEL",
                selection.credential_env,
                "PRIME_AGENT_KERNEL_PYTHON",
                "PRIME_AGENT_KERNEL_VENV",
            )
            if key in inherited
        }
        if "HOME" not in environment or "PATH" not in environment:
            raise ValueError
        return dict(environment)
    except (ImportError, OSError, TypeError, ValueError, PrimeRlmExperimentError):
        raise PrimeExternalLimit("Prime bounded private runtime is unavailable") from None


def _native_rlm_runtime_resources(
    source_root: Path, preflight: Mapping[str, object]
) -> object:
    """Resolve the preflighted, locked launch closure without source discovery."""
    try:
        node = _prime_node_executable()
        runtime_build_id = preflight["runtime_build_id"]
        if not isinstance(node, Path) or not isinstance(runtime_build_id, str):
            raise ValueError
        project_root = Path(__file__).resolve().parents[1]
        try:
            from tools.prime_native_rlm_experiment import NativeRlmRuntimeResources
        except ModuleNotFoundError:
            from prime_native_rlm_experiment import NativeRlmRuntimeResources

        return NativeRlmRuntimeResources(
            node_executable=node,
            daemon_entry=derive_prime_rlm_runtime(source_root),
            sidecar_entry=(
                project_root / "packages" / "typescript" / "prime-gateway" / "dist" / "src" / "main.js"
            ),
            artifact_lock_path=(
                project_root / "packages" / "typescript" / "prime-gateway" / "resources" / "prime-artifact-lock.json"
            ),
            prime_source_root=source_root.resolve(),
            skill_path=(
                project_root / "src" / "asterion" / "control" / "providers" / "prime" / "resources" / "skills" / "prime-native-rlm"
            ),
            expected_runtime_build_id=runtime_build_id,
        )
    except (OSError, PrimeSetupError, TypeError, ValueError):
        raise PrimeExternalLimit("Prime native RLM runtime is unavailable") from None


def _default_native_rlm_evidence_root() -> Path:
    """Create the private, ignored default root only for an explicit probe."""
    try:
        root = Path.cwd() / ".asterion-private" / "prime-rlm"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        root.chmod(0o700)
        if not root.is_dir() or root.stat().st_mode & 0o777 != 0o700:
            raise OSError
        return root
    except OSError:
        raise PrimeVerificationError("Prime native RLM evidence root is invalid") from None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--level", required=True,
        choices=("provider-free", "preflight", "bounded", "native-rlm-bounded"),
    )
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--authority", type=Path)
    parser.add_argument("--max-cost-micros", type=int)
    parser.add_argument("--private-evidence-root", type=Path)
    parser.add_argument("--native-rlm-experiment", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.level == "provider-free":
            if any(
                value is not None
                for value in (
                    arguments.source_root,
                    arguments.authority,
                    arguments.max_cost_micros,
                    arguments.private_evidence_root,
                )
            ):
                raise PrimeVerificationError(
                    "Provider-free verification accepts no external authority"
                )
            report = verify_provider_free()
        elif arguments.level == "preflight":
            if (
                arguments.source_root is None
                or arguments.authority is not None
                or arguments.max_cost_micros is not None
                or arguments.private_evidence_root is not None
                or arguments.native_rlm_experiment
            ):
                raise PrimeVerificationError("Prime preflight arguments are invalid")
            report = verify_preflight(arguments.source_root)
        elif arguments.level == "bounded":
            if (
                arguments.source_root is None
            ):
                raise PrimeVerificationError(
                    "Prime bounded verification requires an explicit source root"
                )
            report = _bounded_external_limit(
                arguments.source_root,
                arguments.authority,
                arguments.max_cost_micros,
            )
        else:
            if (
                arguments.source_root is None
                or not arguments.native_rlm_experiment
            ):
                raise PrimeVerificationError(
                    "Prime native RLM verification requires explicit experiment opt-in"
                )
            evidence_root = (
                _default_native_rlm_evidence_root()
                if arguments.private_evidence_root is None
                else arguments.private_evidence_root
            )
            report = _native_rlm_bounded_external_limit(
                arguments.source_root,
                arguments.authority,
                arguments.max_cost_micros,
                evidence_root,
            )
    except PrimeExternalLimit as error:
        print(
            json.dumps(
                {
                    "status": "External-limited",
                    "level": arguments.level,
                    "reason": str(error),
                    "provider_operations": 0,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 2
    except PrimeVerificationError as error:
        print(f"Prime verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from tools.verify_prime_loop import main as canonical_main

    raise SystemExit(canonical_main())
