from __future__ import annotations

import asyncio
import json
import os
import time
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from asterion.control.authority import AuthorityLedger
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.journal import FileCanonicalJournal
from asterion.control.manager import ControlHost
from asterion.control.parity import validate_parity_ledger
from asterion.control.parity_testing import ParityScenarioRegistry
from asterion.control.providers.prime.client import PrimeControlPlaneClient
from asterion.control.providers.prime.parity_testing import (
    PRIME_RLM_BOUNDED_SCENARIO_IDS,
    PRIME_RLM_BOUNDED_VERIFICATION_COMMAND_ID,
    PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS,
    PRIME_RLM_REQUIRED_CHECK_IDS,
    PRIME_RLM_SCENARIO_IDS,
    PRIME_RLM_SCENARIO_MATRIX,
    PRIME_RLM_VERIFICATION_COMMAND_ID,
    build_prime_rlm_observation,
    register_prime_rlm_scenarios,
)
from asterion.control.providers.prime.process import (
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcess,
)
from tests.test_control_authority import _envelope
from tests.test_prime_session_context_parity import _closed_environment, _node_22
from tests.test_prime_verified_loop import _PrivateResolver, _create_command, _prime_plan
from tools.setup_prime_agent import derive_prime_rlm_runtime


ROOT = Path(__file__).resolve().parents[1]
LEDGER = (
    ROOT
    / "tests"
    / "fixtures"
    / "prime-parity"
    / "v1"
    / "prime-agent-0.7.1.json"
)

def _pinned_prime_source_root() -> Path:
    configured = os.environ.get("ASTERION_PRIME_SOURCE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (ROOT / "3th-party" / "prime-agent").resolve()


PINNED_SOURCE = _pinned_prime_source_root()
RLM_HARNESS = (
    ROOT
    / "tests"
    / "fixtures"
    / "prime_gateway"
    / "v1"
    / "real-prime-rlm-messaging.mjs"
)
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


class _NoopExecutor:
    async def execute(self, proposal: object, signal: object) -> ActionExecutionReceipt:
        del proposal, signal
        raise AssertionError("the native RLM harness must not invoke host execution")


class TestPrimeRlmMessagingParity(unittest.TestCase):
    @unittest.skipUnless(
        PINNED_SOURCE.is_dir() and RLM_HARNESS.is_file() and SIDECAR_ENTRY.is_file(),
        "external pinned Prime RLM harness is unavailable",
    )
    def test_real_daemon_exposes_asterion_rlm_spawn_admission(self) -> None:
        node = _node_22()
        if node is None:
            self.skipTest("an offline pinned Node 22 executable is unavailable")
        kernel_python = Path.home() / ".prime" / "agent" / "kernel-venv" / "bin" / "python"
        if not kernel_python.is_file():
            self.skipTest("an operator Prime kernel is unavailable")
        runtime_entry = derive_prime_rlm_runtime(
            PINNED_SOURCE, lock_path=ARTIFACT_LOCK
        )
        self.assertTrue(runtime_entry.is_file())
        daemon_exit_code: int | None = None

        async def run() -> dict[str, object]:
            nonlocal daemon_exit_code
            with tempfile.TemporaryDirectory(
                prefix="asterion-prime-rlm-", dir="/tmp"
            ) as temporary:
                root = Path(temporary)
                home = root / "home"
                workspace = root / "workspace"
                agent_dir = root / "agent"
                session_dir = root / "sessions"
                gateway_root = root / "gateway"
                for directory in (
                    home,
                    workspace,
                    agent_dir,
                    session_dir,
                    gateway_root,
                    root / "applications",
                ):
                    directory.mkdir(mode=0o700)
                socket_path = root / "prime.sock"
                environment = _closed_environment(home)
                environment["PRIME_AGENT_KERNEL_PYTHON"] = str(kernel_python)
                daemon = await asyncio.create_subprocess_exec(
                    str(node),
                    str(runtime_entry),
                    "--mode",
                    "daemon",
                    "--daemon-socket",
                    str(socket_path),
                    cwd=PINNED_SOURCE,
                    env=environment,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    umask=0o077,
                )
                process: PrimeSidecarProcess | None = None
                host: ControlHost | None = None
                stderr_sink = (root / "sidecar.stderr").open("wb")
                try:
                    deadline = time.monotonic() + 15
                    while not socket_path.exists():
                        if daemon.returncode is not None:
                            self.fail("the pinned Prime daemon did not start")
                        if time.monotonic() >= deadline:
                            self.fail("the pinned Prime daemon did not become ready")
                        await asyncio.sleep(0.025)
                    authority = _envelope(
                        allowed_operations=(
                            "application.invoke",
                            "child.message",
                            "child.spawn",
                        ),
                        execution_domain="trusted-local",
                    )
                    descriptor = {
                        "agentDir": str(agent_dir),
                        "artifactLockPath": str(ARTIFACT_LOCK),
                        "authorityId": authority.authority_id,
                        "authorityRevision": authority.revision,
                        "expectedRuntimeBuildId": "beta",
                        "gatewayRoot": str(gateway_root),
                        "generation": 1,
                        "maxContinuations": 1,
                        "maxControllerTokens": 100,
                        "maxTurns": 1,
                        "model": "claude-sonnet-4-5",
                        "operationHost": {
                            "socketPath": str(root / "prime-operation.sock"),
                            "token": "a" * 64,
                        },
                        "portfolio": [
                            {
                                "kind": "application",
                                "provider_id": grant.provider_id,
                                "application_id": grant.application_id,
                                "version": grant.version,
                                "runtime_id": grant.runtime_id,
                            }
                            for grant in authority.allowed_portfolio
                        ],
                        "primeSocketPath": str(socket_path),
                        "primeSourceRoot": str(PINNED_SOURCE),
                        "provider": "anthropic",
                        "probeReady": False,
                        "rlmMaxChildren": 1,
                        "rlmMaxDepth": 0,
                        "remainingBudget": {
                            "controller_tokens": authority.budget_limit.controller_tokens,
                            "application_tokens": authority.budget_limit.application_tokens,
                            "child_tokens": authority.budget_limit.child_tokens,
                            "aggregate_tokens": authority.budget_limit.aggregate_tokens,
                            "cost_micros": authority.budget_limit.cost_micros,
                            "deadline_ms": authority.max_action_deadline_ms,
                        },
                        "sessionDir": str(session_dir),
                        "sessionId": "session-1",
                        "skillPath": str(
                            ROOT
                            / "src"
                            / "asterion"
                            / "control"
                            / "providers"
                            / "prime"
                            / "resources"
                            / "skills"
                            / "asterion-control"
                        ),
                        "timeoutMs": 5_000,
                        "workspace": str(workspace),
                    }
                    process = await PrimeSidecarProcess.start(
                        PrimeSidecarLaunchOptions(
                            node_executable=node,
                            sidecar_entry=SIDECAR_ENTRY,
                            private_descriptor=descriptor,
                            environ=environment,
                            request_timeout=10,
                            private_stderr_sink=stderr_sink,
                        )
                    )
                    resolver = _PrivateResolver()
                    client = PrimeControlPlaneClient(
                        process=process,
                        private_content=resolver,
                        private_attachments=resolver,
                    )
                    host = ControlHost(
                        session_id="session-1",
                        generation=1,
                        plan=_prime_plan(root),
                        authority=AuthorityLedger(authority),
                        journal=FileCanonicalJournal.open(root / "journal", "session-1"),
                        client=client,
                        action_executor=_NoopExecutor(),
                        clock_ms=lambda: 1_000,
                    )
                    await host.dispatch(_create_command())
                    await host.pump()
                    fixture = await asyncio.create_subprocess_exec(
                        str(node),
                        str(RLM_HARNESS),
                        str(socket_path),
                        str(agent_dir),
                        cwd=ROOT,
                        env=environment,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    while fixture.returncode is None:
                        await host.pump()
                        await asyncio.sleep(0.01)
                    stdout, stderr = await fixture.communicate()
                    self.assertEqual(
                        fixture.returncode,
                        0,
                        stderr.decode("utf-8", errors="replace"),
                    )
                    payload = json.loads(stdout)
                    self.assertNotIn("PRIVATE_RLM_CHILD_GOAL", stdout.decode())
                    payload["lifecycle_types"] = [
                        observation.type for observation in await client.rlm_lifecycle()
                    ]
                    await host.close()
                    host = None
                    process = await PrimeSidecarProcess.start(
                        PrimeSidecarLaunchOptions(
                            node_executable=node,
                            sidecar_entry=SIDECAR_ENTRY,
                            private_descriptor={**descriptor, "recoveryReadOnly": True},
                            environ=environment,
                            request_timeout=10,
                            private_stderr_sink=stderr_sink,
                        )
                    )
                    client = PrimeControlPlaneClient(
                        process=process,
                        private_content=resolver,
                        private_attachments=resolver,
                    )
                    payload["recovered_lifecycle_types"] = [
                        observation.type
                        for observation in await client.rlm_lifecycle()
                    ]
                    return payload
                finally:
                    if host is not None:
                        await host.close()
                    elif process is not None:
                        await process.close()
                    if daemon.returncode is None:
                        cleanup_script = (
                            "import { PrimeDaemonClient } from "
                            + json.dumps(
                                (SIDECAR_ENTRY.parent / "daemon-client.js").as_uri()
                            )
                            + "; const client = new PrimeDaemonClient({clientId: "
                            + json.dumps("asterion-rlm-cleanup")
                            + ", connectTimeoutMs: 3000, requestTimeoutMs: 3000}); "
                            + "await client.connect("
                            + json.dumps(str(socket_path))
                            + "); await client.request({type: 'shutdown', force: true}, "
                            + json.dumps("asterion-rlm-cleanup")
                            + ", 3000); client.close();"
                        )
                        cleanup = await asyncio.create_subprocess_exec(
                            str(node),
                            "--input-type=module",
                            "-e",
                            cleanup_script,
                            stdin=asyncio.subprocess.DEVNULL,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        self.assertEqual(
                            await asyncio.wait_for(cleanup.wait(), timeout=5), 0
                        )
                        await asyncio.wait_for(daemon.wait(), timeout=5)
                    daemon_exit_code = daemon.returncode
                    stderr_sink.close()

        observation = asyncio.run(run())
        self.assertEqual(daemon_exit_code, 0)
        self.assertEqual(
            observation,
            {
                "format": "asterion.prime-rlm-observation/v1",
                "fake_daemon": False,
                "model_credential_reads": 0,
                "provider_operations": 0,
                "spawn_admitted": True,
                "lifecycle_recorded": True,
                "lifecycle_types": [
                    "rlm.child.started",
                    "rlm.child.terminal",
                    "rlm.child.deleted",
                ],
                "recovered_lifecycle_types": [
                    "rlm.child.started",
                    "rlm.child.terminal",
                    "rlm.child.deleted",
                ],
                "message_delivered": True,
                "teardown_recorded": True,
            },
        )

    def test_rlm_adapter_registers_provider_free_and_exact_bounded_evidence(self) -> None:
        observations = tuple(
            build_prime_rlm_observation(
                scenario_id=scenario_id,
                status="PASS",
                checks=PRIME_RLM_REQUIRED_CHECK_IDS[scenario_id],
                real_prime_runtime=True,
                fake_daemon=False,
                provider_operations=(
                    1 if scenario_id in PRIME_RLM_BOUNDED_SCENARIO_IDS else 0
                ),
                model_credential_reads=(
                    1 if scenario_id in PRIME_RLM_BOUNDED_SCENARIO_IDS else 0
                ),
            )
            for scenario_id in PRIME_RLM_SCENARIO_IDS
        )
        registry = ParityScenarioRegistry(
            validate_parity_ledger(json.loads(LEDGER.read_text(encoding="utf-8"))),
            provider_id="asterion.prime-gateway",
        )

        register_prime_rlm_scenarios(
            registry,
            observations,
            provider_factory=lambda: object(),
        )
        report = asyncio.run(registry.run(PRIME_RLM_SCENARIO_IDS))

        self.assertEqual(registry.registered_scenario_ids, PRIME_RLM_SCENARIO_IDS)
        self.assertEqual(report.passed_scenario_ids, PRIME_RLM_SCENARIO_IDS)
        self.assertEqual(report.blocking_scenario_ids, ())

    def test_rlm_observation_only_issues_evidence_for_real_provider_free_runs(self) -> None:
        provider_free = build_prime_rlm_observation(
            scenario_id="prime-parity.rlm.messaging",
            status="PASS",
            checks=PRIME_RLM_REQUIRED_CHECK_IDS["prime-parity.rlm.messaging"],
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=0,
            model_credential_reads=0,
        )
        bounded = build_prime_rlm_observation(
            scenario_id="prime-parity.rlm.child-model",
            status="EXTERNAL-LIMITED",
            checks=(),
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=0,
            model_credential_reads=0,
        )

        self.assertIsNotNone(provider_free.evidence_id)
        self.assertIsNone(bounded.evidence_id)
        self.assertNotIn("PRIVATE", provider_free.serialized_observations)
        with self.assertRaisesRegex(Exception, "Prime RLM observation is invalid"):
            build_prime_rlm_observation(
                scenario_id="prime-parity.rlm.messaging",
                status="PASS",
                checks=("forged-check",),
                real_prime_runtime=True,
                fake_daemon=False,
                provider_operations=0,
                model_credential_reads=0,
            )

    def test_bounded_rlm_observation_requires_the_exact_model_receipt(self) -> None:
        observation = build_prime_rlm_observation(
            scenario_id="prime-parity.rlm.child-model",
            status="PASS",
            checks=PRIME_RLM_REQUIRED_CHECK_IDS["prime-parity.rlm.child-model"],
            real_prime_runtime=True,
            fake_daemon=False,
            provider_operations=1,
            model_credential_reads=1,
        )

        self.assertIsNotNone(observation.evidence_id)
        self.assertEqual(
            observation.command_id,
            PRIME_RLM_BOUNDED_VERIFICATION_COMMAND_ID,
        )
        for changes in (
            {"provider_operations": 0},
            {"model_credential_reads": 0},
            {"checks": ()},
        ):
            with self.subTest(changes=changes):
                values = {
                    "scenario_id": "prime-parity.rlm.child-model",
                    "status": "PASS",
                    "checks": PRIME_RLM_REQUIRED_CHECK_IDS[
                        "prime-parity.rlm.child-model"
                    ],
                    "real_prime_runtime": True,
                    "fake_daemon": False,
                    "provider_operations": 1,
                    "model_credential_reads": 1,
                }
                values.update(changes)
                with self.assertRaisesRegex(
                    Exception, "Prime RLM observation is invalid"
                ):
                    build_prime_rlm_observation(**values)

    def test_provider_free_rlm_evidence_contract_distinguishes_native_paths(self) -> None:
        self.assertEqual(
            PRIME_RLM_VERIFICATION_COMMAND_ID,
            "test.prime-rlm-spawn-admission.provider-free",
        )
        self.assertEqual(
            {
                scenario_id: PRIME_RLM_REQUIRED_CHECK_IDS[scenario_id]
                for scenario_id in PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS
            },
            {
                "prime-parity.rlm.cancellation-teardown": (
                    "native-child-teardown-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
                "prime-parity.rlm.environment": (
                    "closed-home-no-credentials-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
                "prime-parity.rlm.messaging": (
                    "native-family-message-admitted-passed",
                    "native-message-delivery-recorded-passed",
                ),
                "prime-parity.rlm.recovery": (
                    "native-message-recovery-fenced-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
                "prime-parity.rlm.registry-lifecycle": (
                    "native-child-registry-delete-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
                "prime-parity.rlm.usage-cost": (
                    "zero-provider-usage-monotonic-passed",
                    "pinned-prime-rlm-daemon-passed",
                ),
            },
        )

    def test_real_rlm_harness_contract_is_exactly_the_approved_matrix(self) -> None:
        ledger = validate_parity_ledger(json.loads(LEDGER.read_text(encoding="utf-8")))
        scenario_rows = ledger["scenarios"]
        self.assertIsInstance(scenario_rows, tuple)
        assert isinstance(scenario_rows, tuple)
        rows = {
            str(item["scenario_id"]): item
            for item in scenario_rows
            if isinstance(item, Mapping)
            and str(item["scenario_id"]).startswith("prime-parity.rlm.")
        }

        self.assertEqual(tuple(rows), PRIME_RLM_SCENARIO_IDS)
        self.assertEqual(
            PRIME_RLM_PROVIDER_FREE_SCENARIO_IDS,
            (
                "prime-parity.rlm.cancellation-teardown",
                "prime-parity.rlm.environment",
                "prime-parity.rlm.messaging",
                "prime-parity.rlm.recovery",
                "prime-parity.rlm.registry-lifecycle",
                "prime-parity.rlm.usage-cost",
            ),
        )
        self.assertEqual(
            PRIME_RLM_BOUNDED_SCENARIO_IDS,
            (
                "prime-parity.rlm.child-model",
                "prime-parity.rlm.generated-program",
                "prime-parity.rlm.recursion-depth",
            ),
        )
        self.assertEqual(set(PRIME_RLM_SCENARIO_MATRIX), set(rows))
        for scenario_id, contract in PRIME_RLM_SCENARIO_MATRIX.items():
            with self.subTest(scenario_id=scenario_id):
                self.assertEqual(contract["boundary"], rows[scenario_id]["boundary"])
                self.assertEqual(contract["feature_ids"], rows[scenario_id]["feature_ids"])
                self.assertEqual(contract["assertion_ids"], rows[scenario_id]["assertion_ids"])
                self.assertEqual(contract["fault_ids"], rows[scenario_id]["fault_ids"])

    def test_ledger_binds_six_provider_free_and_three_bounded_rlm_results(self) -> None:
        ledger = validate_parity_ledger(json.loads(LEDGER.read_text(encoding="utf-8")))
        expected = {
            "rlm.cancellation-teardown": "evidence.rlm.3be52858774220c8a7ba9a9a561895292bece505a6b282da243996ac3a52b687",
            "rlm.child-model": "evidence.rlm.d3eb0f5bd584f109988294073a2c554b2f98047253894c3a62e2e76cb38ae9f8",
            "rlm.environment": "evidence.rlm.4befbd6e0288efcf04a9a50fc12aaa7620e2c126f13c75b0c3c331770afe9b53",
            "rlm.generated-program": "evidence.rlm.3c7ff625c8f42358623d2c52d84e465116fe3cde63d1c861cce68909cd39d9db",
            "rlm.messaging": "evidence.rlm.fd98de641ce90ea6657295f8f492092c28dca490e849ab00438ec3d3f8d3000c",
            "rlm.recovery": "evidence.rlm.e638c9f2992708cb9dd980a7f6bd2b792a787d4f0f1f5116e3e4d50738d8b6bf",
            "rlm.recursion-depth": "evidence.rlm.ff6a84e3bdfb5ae9b3980c9b887e94264afa34eabc0185f205448dcb1cc12806",
            "rlm.registry-lifecycle": "evidence.rlm.7be120a547f5969762d773ba7bbe122a29ab87b89f67931b9c22e09008fe8f29",
            "rlm.usage-cost": "evidence.rlm.0b41ebbc26f1d298358bae1052fcf47154bbd1f044b82789ac1d1c1a0d40cbfe",
        }
        feature_rows = cast(tuple[Mapping[str, object], ...], ledger["features"])
        features = {
            str(row["feature_id"]): row
            for row in feature_rows
            if str(row["feature_id"]).startswith("rlm.")
        }
        for feature_id, row in features.items():
            with self.subTest(feature_id=feature_id):
                provider_results = cast(
                    tuple[Mapping[str, object], ...], row["provider_results"]
                )
                result = next(
                    item
                    for item in provider_results
                    if item["provider_id"] == "asterion.prime-gateway"
                )
                expected_status = (
                    "bounded-pass"
                    if feature_id
                    in {"rlm.child-model", "rlm.generated-program", "rlm.recursion-depth"}
                    else "provider-free-pass"
                )
                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["evidence_ids"], (expected[feature_id],))
        evidence_rows = cast(tuple[Mapping[str, object], ...], ledger["evidence"])
        evidence = tuple(
            row
            for row in evidence_rows
            if str(row["evidence_id"]).startswith("evidence.rlm.")
        )
        self.assertEqual(
            tuple(row["evidence_id"] for row in evidence),
            tuple(sorted(expected.values())),
        )
        for row in evidence:
            feature_ids = cast(tuple[str, ...], row["feature_ids"])
            bounded = feature_ids[0] in {
                "rlm.child-model",
                "rlm.generated-program",
                "rlm.recursion-depth",
            }
            self.assertEqual(
                row["boundary"],
                "bounded-provider" if bounded else "real-prime-provider-free",
            )
            self.assertEqual(
                row["command_id"],
                PRIME_RLM_BOUNDED_VERIFICATION_COMMAND_ID
                if bounded
                else PRIME_RLM_VERIFICATION_COMMAND_ID,
            )
            self.assertEqual(row["status"], "pass")


if __name__ == "__main__":
    unittest.main()
