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
    authority_path: Path,
    max_cost_micros: int,
) -> Mapping[str, object]:
    load_bounded_authority(
        authority_path,
        max_cost_micros=max_cost_micros,
    )
    verify_preflight(source_root)
    raise PrimeExternalLimit(
        "Prime bounded execution requires separately injected run configuration"
    )


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
            prepare_native_rlm_experiment,
            resolve_native_rlm_model,
            run_native_rlm_controlled_probe,
            run_native_rlm_experiment,
            run_owned_native_rlm_sidecar_probe,
            write_native_rlm_experiment_receipt,
        )
    except ModuleNotFoundError:
        from prime_native_rlm_experiment import (
            PrimeRlmExperimentError,
            prepare_native_rlm_experiment,
            resolve_native_rlm_model,
            run_native_rlm_controlled_probe,
            run_native_rlm_experiment,
            run_owned_native_rlm_sidecar_probe,
            write_native_rlm_experiment_receipt,
        )

    if not private_evidence_root.is_dir():
        raise PrimeVerificationError("Prime native RLM evidence root is invalid")
    stage = "preflight"
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

        async def runner(active: object) -> object:
            nonlocal consumed, observation
            consumed = active
            observation = await run_owned_native_rlm_sidecar_probe(
                active,  # type: ignore[arg-type]
                selection,
                run_root,
                resources,
                environ=environment,
                probe=lambda sidecar: run_native_rlm_controlled_probe(
                    sidecar, active, run_root  # type: ignore[arg-type]
                ),
            )
            return observation

        stage = "execution"
        report = asyncio.run(run_native_rlm_experiment(reservation, runner))
        if consumed is None or observation is None:
            raise ValueError
        stage = "receipt"
        receipt = write_native_rlm_experiment_receipt(
            private_evidence_root,
            consumed,  # type: ignore[arg-type]
            terminal=observation.terminal,
            child_started=observation.child_started,
            message_delivered=observation.message_delivered,
            child_deleted=observation.child_deleted,
            usage=observation.usage,
        )
        return {
            "status": report["status"],
            "level": "native-rlm-bounded",
            "terminal": report["terminal"],
            "child_started": receipt["child_started"],
            "message_delivered": receipt["message_delivered"],
            "child_deleted": receipt["child_deleted"],
            "provider_operations": 1,
            "application_operations": 0,
            "full_dataset_ran": False,
        }
    except PrimeRlmExperimentError as error:
        raise PrimeExternalLimit(str(error)) from None
    except (OSError, RuntimeError, TypeError, ValueError):
        raise PrimeExternalLimit(
            f"Prime native RLM probe {stage} did not complete"
        ) from None


def _native_rlm_environment() -> dict[str, str]:
    """Load private experiment credentials only after explicit CLI opt-in."""
    try:
        values = {
            key: value
            for key, value in dotenv_values(Path.cwd() / ".env").items()
            if isinstance(key, str) and isinstance(value, str)
        }
        return {**values, **os.environ}
    except OSError:
        raise PrimeVerificationError("Prime native RLM environment is invalid") from None


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
                project_root / "src" / "asterion" / "control" / "providers" / "prime" / "resources" / "skills" / "asterion-control"
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
                or arguments.authority is None
                or arguments.max_cost_micros is None
            ):
                raise PrimeVerificationError(
                    "Prime bounded verification requires explicit finite authorization"
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
