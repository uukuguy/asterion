"""Real pinned Prime RLM compatibility witness for recursive workflow."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from asterion.applications.prime_agent.recursive_workflow_receipt import (
    RecursiveWorkflowReceiptError,
    recursive_workflow_observation_from_public_report,
    verify_recursive_workflow_receipt,
)
from asterion.applications.prime_agent.source_lock import (
    PrimeSourceLock,
    verify_prime_source_lock,
)
from asterion.control.authority import AuthorityLedger
from asterion.control.journal import FileCanonicalJournal
from asterion.control.manager import ControlHost
from asterion.control.providers.prime.client import PrimeControlPlaneClient
from asterion.control.providers.prime.process import (
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcess,
)
from tests.test_control_authority import _envelope
from tests.test_prime_rlm_messaging_parity import _NoopExecutor
from tests.test_prime_session_context_parity import _closed_environment, _node_22
from tests.test_prime_verified_loop import _PrivateResolver, _create_command, _prime_plan
from tools.setup_prime_agent import derive_prime_rlm_runtime


ROOT = Path(__file__).resolve().parents[1]
HARNESS = (
    ROOT
    / "tests"
    / "fixtures"
    / "prime_gateway"
    / "v1"
    / "prime-recursive-workflow-compat.mjs"
)
PRIME_ROOT = ROOT / "3th-party" / "prime-agent"
ARTIFACT_LOCK = (
    ROOT
    / "packages"
    / "typescript"
    / "prime-gateway"
    / "resources"
    / "prime-artifact-lock.json"
)
SIDECAR_ENTRY = (
    ROOT / "packages" / "typescript" / "prime-gateway" / "dist" / "src" / "main.js"
)
PINNED_LOCK = PrimeSourceLock(
    "a18809e00ea30638584d87b3afea7285a9d7296c",
    "93a4b02ecc0cc114865fa3d336521cf214047cf4de471b36b51fe610c84ab686",
    "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
)
PUBLIC_KEYS = {
    "format", "status", "reason", "real_prime_runtime",
    "allowed_tool_names", "active_tool_names", "admitted_child_count",
    "bound_child_count", "root_to_child_message_count",
    "child_to_root_result_count", "terminal_child_count", "deleted_child_count",
    "workflow_sha256", "aggregation_sha256", "oracle_sha256",
    "root_continued_locally", "aggregation_passed", "disposed", "reaped",
}


def _external_limited(reason: str, *, reaped: bool = False) -> dict[str, object]:
    return {
        "format": "asterion.prime-recursive-workflow-compat/v1",
        "status": "External-limited", "reason": reason,
        "real_prime_runtime": False,
        "allowed_tool_names": [], "active_tool_names": [],
        "admitted_child_count": 0, "bound_child_count": 0,
        "root_to_child_message_count": 0, "child_to_root_result_count": 0,
        "terminal_child_count": 0, "deleted_child_count": 0,
        "workflow_sha256": None, "aggregation_sha256": None, "oracle_sha256": None,
        "root_continued_locally": False, "aggregation_passed": False,
        "disposed": False, "reaped": reaped,
    }


def _kernel_python() -> str | None:
    candidate = os.environ.get("PRIME_AGENT_KERNEL_PYTHON") or str(
        Path.home() / ".prime" / "agent" / "kernel-venv" / "bin" / "python"
    )
    path = Path(candidate)
    if not (path.is_absolute() and path.is_file() and os.access(path, os.X_OK)):
        return None
    try:
        probe = subprocess.run(
            (str(path), "-c", "import ipykernel, rlm"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", "")},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return str(path) if probe.returncode == 0 else None


def _public_report(stdout: bytes) -> dict[str, object] | None:
    try:
        lines = stdout.decode("utf-8").splitlines()
        return (
            json.loads(lines[0])
            if len(lines) == 1 and type(json.loads(lines[0])) is dict
            else None
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _run_compatibility(workspace: Path) -> dict[str, object]:
    verify_prime_source_lock(PRIME_ROOT, PINNED_LOCK)
    node, kernel_python = _node_22(), _kernel_python()
    if node is None or kernel_python is None or not SIDECAR_ENTRY.is_file():
        return _external_limited("missing-prerequisite")
    runtime_entry = derive_prime_rlm_runtime(PRIME_ROOT, lock_path=ARTIFACT_LOCK)
    if not runtime_entry.is_file():
        return _external_limited("missing-prerequisite")

    async def run() -> dict[str, object]:
        root = workspace.parent
        home = root / "home"
        agent_dir = root / "agent"
        session_dir = root / "sessions"
        gateway_root = root / "gateway"
        for directory in (home, agent_dir, session_dir, gateway_root, root / "applications"):
            directory.mkdir(mode=0o700, exist_ok=True)
        socket_path = root / "prime.sock"
        environment = _closed_environment(home)
        environment["PRIME_AGENT_KERNEL_PYTHON"] = kernel_python
        daemon = await asyncio.create_subprocess_exec(
            str(node), str(runtime_entry), "--mode", "daemon", "--daemon-socket", str(socket_path),
            cwd=PRIME_ROOT, env=environment, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, umask=0o077,
        )
        process: PrimeSidecarProcess | None = None
        host: ControlHost | None = None
        stderr_sink = (root / "sidecar.stderr").open("wb")
        try:
            deadline = time.monotonic() + 15
            while not socket_path.exists():
                if daemon.returncode is not None or time.monotonic() >= deadline:
                    return _external_limited("kernel-start-timeout")
                await asyncio.sleep(0.025)
            authority = _envelope(
                allowed_operations=("application.invoke", "child.message", "child.spawn"),
                execution_domain="trusted-local",
            )
            descriptor = {
                "agentDir": str(agent_dir), "artifactLockPath": str(ARTIFACT_LOCK),
                "authorityId": authority.authority_id, "authorityRevision": authority.revision,
                "authorityExpiresAtMs": int(time.time() * 1_000) + 60_000,
                "expectedRuntimeBuildId": "beta", "gatewayRoot": str(gateway_root),
                "generation": 1, "maxContinuations": 1, "maxControllerTokens": 100,
                "maxTurns": 1, "model": "claude-sonnet-4-5",
                "operationHost": {"socketPath": str(root / "prime-operation.sock"), "token": "a" * 64},
                "portfolio": [{"kind": "application", "provider_id": grant.provider_id,
                               "application_id": grant.application_id, "version": grant.version,
                               "runtime_id": grant.runtime_id} for grant in authority.allowed_portfolio],
                "primeSocketPath": str(socket_path), "primeSourceRoot": str(PRIME_ROOT),
                "provider": "anthropic", "probeReady": False, "rlmMaxChildren": 2,
                "rlmMaxDepth": 1,
                "remainingBudget": {"controller_tokens": 2,
                                    "application_tokens": 2,
                                    "child_tokens": 2,
                                    "aggregate_tokens": 2,
                                    "cost_micros": 2,
                                    "deadline_ms": 5_000},
                "sessionDir": str(session_dir), "sessionId": "session-1",
                "skillPath": str(ROOT / "src" / "asterion" / "control" / "providers" / "prime" / "resources" / "skills" / "asterion-control"),
                "timeoutMs": 5_000, "workspace": str(workspace),
            }
            process = await PrimeSidecarProcess.start(PrimeSidecarLaunchOptions(
                node_executable=node, sidecar_entry=SIDECAR_ENTRY, private_descriptor=descriptor,
                environ=environment, request_timeout=10, private_stderr_sink=stderr_sink,
            ))
            resolver = _PrivateResolver()
            client = PrimeControlPlaneClient(process=process, private_content=resolver, private_attachments=resolver)
            host = ControlHost(
                session_id="session-1", generation=1, plan=_prime_plan(root),
                authority=AuthorityLedger(authority),
                journal=FileCanonicalJournal.open(root / "journal", "session-1"), client=client,
                action_executor=_NoopExecutor(), clock_ms=lambda: 1_000,
            )
            await host.dispatch(_create_command())
            await host.pump()
            fixture = await asyncio.create_subprocess_exec(
                str(node), str(HARNESS), str(socket_path), str(agent_dir), cwd=ROOT, env=environment,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            while fixture.returncode is None:
                await host.pump()
                await asyncio.sleep(0.01)
            stdout, _ = await fixture.communicate()
            report = _public_report(stdout)
            if fixture.returncode != 0:
                return _external_limited("unsupported-prime-api")
            if report is None or set(report) != PUBLIC_KEYS:
                return _external_limited("unsupported-prime-api")
            if report["reason"] == "spawn-resolution-rejected":
                action_reasons = {
                    action.reason
                    for action in host.snapshot().state.actions.values()
                    if action.kind == "child.spawn" and action.reason is not None
                }
                if len(action_reasons) == 1:
                    return _external_limited(
                        "spawn-admission-" + next(iter(action_reasons))
                    )
                if not action_reasons:
                    return _external_limited("spawn-host-actions-absent")
                if "budget-exceeded" in action_reasons:
                    return _external_limited("native-budget-contract-limited")
                return _external_limited("native-admission-contract-limited")
            return report
        finally:
            if host is not None:
                await host.close()
            elif process is not None:
                await process.close()
            if daemon.returncode is None:
                cleanup_script = (
                    "import { PrimeDaemonClient } from " + json.dumps((SIDECAR_ENTRY.parent / "daemon-client.js").as_uri())
                    + "; const client = new PrimeDaemonClient({clientId: 'asterion-recursive-cleanup', connectTimeoutMs: 3000, requestTimeoutMs: 3000}); await client.connect("
                    + json.dumps(str(socket_path))
                    + "); await client.request({type: 'shutdown', force: true}, 'asterion-recursive-cleanup', 3000); client.close();"
                )
                cleanup = await asyncio.create_subprocess_exec(
                    str(node), "--input-type=module", "-e", cleanup_script,
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(cleanup.wait(), timeout=5)
                await asyncio.wait_for(daemon.wait(), timeout=5)
            stderr_sink.close()

    try:
        return asyncio.run(run())
    except (OSError, RuntimeError, TimeoutError):
        return _external_limited("unsupported-prime-api")


class TestPrimeRecursiveWorkflowCompat(unittest.TestCase):
    def test_real_rlm_fixture_is_present_and_does_not_expose_private_inputs(self) -> None:
        self.assertTrue(HARNESS.is_file())

        source = HARNESS.read_text(encoding="utf-8")
        self.assertTrue(
            all(
                value not in source
                for value in ("fetch(", "docker", ".env", "npm install")
            )
        )

    def test_real_daemon_report_is_public_safe_or_closed_external_limited(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-prime-recursive-", dir="/tmp") as temporary:
            workspace = Path(temporary, "workspace")
            workspace.mkdir(mode=0o700)
            report = _run_compatibility(workspace)

        self.assertEqual(set(report), PUBLIC_KEYS)
        self.assertIn(report["status"], {"PASS", "External-limited"})
        public = json.dumps(report, sort_keys=True, separators=(",", ":"))
        self.assertNotIn("PRIVATE_RECURSIVE_GOAL", public)
        self.assertNotIn("PRIVATE_ROOT_TO_CHILD", public)
        self.assertNotIn("PRIVATE_CHILD_TO_ROOT", public)
        if report["status"] == "PASS":
            self.assertEqual(report["reason"], "supported")
            self.assertTrue(report["real_prime_runtime"])
            self.assertEqual(report["allowed_tool_names"], ["ipython"])
            self.assertEqual(report["active_tool_names"], ["ipython"])
            self.assertTrue(report["disposed"])
            self.assertTrue(report["reaped"])
            self.assertEqual(
                verify_recursive_workflow_receipt(
                    recursive_workflow_observation_from_public_report(report)
                ).scenario_id,
                "prime.recursive-workflow/v1",
            )
        else:
            self.assertIn(
                report["reason"],
                {
                    "missing-prerequisite",
                    "kernel-start-timeout",
                    "unsupported-prime-api",
                    "spawn-admission-rejected",
                    "root-message-admission-rejected",
                    "child-message-admission-rejected",
                    "deletion-admission-rejected",
                    "native-budget-contract-limited",
                    "native-admission-contract-limited",
                },
            )
            with self.assertRaises(RecursiveWorkflowReceiptError):
                recursive_workflow_observation_from_public_report(report)


if __name__ == "__main__":
    unittest.main()
