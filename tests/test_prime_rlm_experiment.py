from __future__ import annotations

import json
import os
import asyncio
import tempfile
import unittest
from pathlib import Path

from asterion.control.authority import BudgetUsage
from tools.prime_native_rlm_experiment import (
    build_native_rlm_daemon_environment,
    build_native_rlm_daemon_plan,
    build_native_rlm_sidecar_descriptor,
    execute_native_rlm_sidecar_probe,
    start_native_rlm_sidecar,
    launch_owned_native_rlm_daemon,
    run_owned_native_rlm_sidecar_probe,
    start_native_rlm_daemon,
    resolve_native_rlm_model,
    NativeRlmProbeResult,
    NativeRlmRuntimeResources,
    PrimeRlmExperimentError,
    prepare_native_rlm_experiment,
    run_native_rlm_experiment,
    write_native_rlm_experiment_receipt,
)


def _authority(**changes: object) -> dict[str, object]:
    authority: dict[str, object] = {
        "authority_id": "authority-1",
        "revision": 1,
        "allowed_portfolio": [
            {
                "provider_id": "example.provider",
                "application_id": "alpha",
                "version": "1.0.0",
                "runtime_id": "fake.runtime",
            }
        ],
        "allowed_operations": [
            "application.invoke",
            "checkpoint.create",
            "child.cancel",
            "child.message",
            "child.spawn",
            "goal.complete",
            "goal.fail",
            "rlm.child.delete",
            "rlm.child.message",
            "rlm.child.spawn",
        ],
        "budget_limit": {
            "controller_tokens": 100,
            "application_tokens": 100,
            "child_tokens": 100,
            "aggregate_tokens": 300,
            "cost_micros": 500_000,
        },
        "expires_at_ms": 100_000,
        "max_action_deadline_ms": 600_000,
        "max_recursion_depth": 1,
        "max_concurrent_children": 1,
        "execution_domain": "trusted-local",
        "host_service_grants": ["artifact.write"],
        "cancelled": False,
    }
    authority.update(changes)
    return {"format": "asterion.prime-bounded-authorization/v1", "authority": authority}


class TestNativeRlmExperiment(unittest.TestCase):
    def test_owned_probe_composes_daemon_and_credential_free_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = prepare_native_rlm_experiment(
                None, max_cost_micros=None, deadline_ms=None,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}, now_ms=1_000,
            )
            resources = NativeRlmRuntimeResources(
                root / "node", root / "daemon.mjs", root / "gateway.mjs", root / "lock.json",
                root / "source", root / "skill", "build-1",
            )

            class Daemon:
                returncode = None

                def terminate(self):
                    self.returncode = 0

                async def wait(self):
                    return 0

            class Sidecar:
                async def close(self):
                    return None

            async def spawn(*_args, **_kwargs):
                (root / "prime.sock").touch()
                return Daemon()

            async def start_sidecar(options):
                self.assertEqual(set(options.environ), {"HOME", "PATH"})
                return Sidecar()

            async def probe(_sidecar):
                return NativeRlmProbeResult("completed", True, True, True, BudgetUsage(1, 1, 1, 3, 3))

            result = asyncio.run(run_owned_native_rlm_sidecar_probe(
                reservation,
                resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}),
                root,
                resources,
                environ={"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
                probe=probe,
                daemon_spawn=spawn,
                sidecar_starter=start_sidecar,
            ))
            self.assertEqual(result.terminal, "completed")

    def test_owned_daemon_launch_uses_direct_arguments_and_locked_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = NativeRlmRuntimeResources(
                root / "node", root / "daemon.mjs", root / "gateway.mjs", root / "lock.json",
                root / "source", root / "skill", "build-1",
            )
            plan = build_native_rlm_daemon_plan(
                resources.node_executable,
                resources.daemon_entry,
                root / "prime.sock",
                resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}),
                {"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
            )
            calls = []

            async def spawn(*argv, **options):
                calls.append((argv, options))
                return object()

            process = asyncio.run(launch_owned_native_rlm_daemon(plan, resources, spawn=spawn))

            self.assertIsInstance(process, object)
            self.assertEqual(calls[0][0], plan.argv)
            self.assertEqual(calls[0][1]["cwd"], resources.prime_source_root)
            self.assertEqual(calls[0][1]["env"], dict(plan.environ))
            self.assertNotIn("secret", repr(plan))

    def test_sidecar_start_excludes_model_credential(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = NativeRlmRuntimeResources(
                root / "node", root / "daemon.mjs", root / "gateway.mjs", root / "lock.json",
                root / "source", root / "skill", "build-1",
            )
            seen = []

            async def starter(options):
                seen.append(options)
                return object()

            asyncio.run(start_native_rlm_sidecar(
                {"sessionId": "native-rlm-root"}, resources,
                environ={"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
                starter=starter,
            ))

            self.assertEqual(
                seen[0].argv,
                (
                    str(resources.node_executable.resolve(strict=False)),
                    str(resources.sidecar_entry.resolve(strict=False)),
                ),
            )
            self.assertEqual(set(seen[0].environ), {"HOME", "PATH"})
            self.assertNotIn("secret", repr(seen[0]))

    def test_sidecar_probe_reaps_owned_processes_after_complete_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = prepare_native_rlm_experiment(
                None,
                max_cost_micros=None,
                deadline_ms=None,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
                now_ms=1_000,
            )
            resources = NativeRlmRuntimeResources(
                node_executable=root / "node",
                daemon_entry=root / "prime-daemon.mjs",
                sidecar_entry=root / "gateway.mjs",
                artifact_lock_path=root / "artifact-lock.json",
                prime_source_root=root / "prime-source",
                skill_path=root / "skill",
                expected_runtime_build_id="build-1",
            )

            class Daemon:
                returncode = None
                terminated = False

                def terminate(self):
                    self.terminated = True
                    self.returncode = 0

                async def wait(self):
                    return 0

            class Sidecar:
                closed = False

                async def close(self):
                    self.closed = True

            daemon = Daemon()
            sidecar = Sidecar()

            async def launch_daemon(plan):
                plan.socket_path.touch()
                return daemon

            async def launch_sidecar(descriptor, _resources):
                self.assertEqual(descriptor["rlmMaxDepth"], 1)
                return sidecar

            async def probe(_sidecar):
                return NativeRlmProbeResult(
                    terminal="completed",
                    child_started=True,
                    message_delivered=True,
                    child_deleted=True,
                    usage=BudgetUsage(1, 1, 1, 3, 3),
                )

            result = asyncio.run(
                execute_native_rlm_sidecar_probe(
                    reservation,
                    resolve_native_rlm_model(
                        {"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}
                    ),
                    root,
                    resources,
                    environ={
                        "HOME": str(root / "home"),
                        "PATH": "/bin",
                        "DEEPSEEK_API_KEY": "secret",
                    },
                    daemon_launcher=launch_daemon,
                    sidecar_launcher=launch_sidecar,
                    probe=probe,
                )
            )

            self.assertEqual(result.terminal, "completed")
            self.assertTrue(sidecar.closed)
            self.assertTrue(daemon.terminated)

    def test_sidecar_probe_redacts_failure_and_reaps_owned_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = prepare_native_rlm_experiment(
                None, max_cost_micros=None, deadline_ms=None,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}, now_ms=1_000,
            )
            resources = NativeRlmRuntimeResources(
                root / "node", root / "daemon.mjs", root / "gateway.mjs", root / "lock.json",
                root / "source", root / "skill", "build-1",
            )

            class Daemon:
                returncode = None
                terminated = False

                def terminate(self):
                    self.terminated = True
                    self.returncode = 0

                async def wait(self):
                    return 0

            class Sidecar:
                async def close(self):
                    return None

            daemon = Daemon()

            async def launch_daemon(plan):
                plan.socket_path.touch()
                return daemon

            async def launch_sidecar(_descriptor, _resources):
                return Sidecar()

            async def fail_probe(_sidecar):
                raise RuntimeError("SENTINEL_PRIVATE_PROBE")

            with self.assertRaises(PrimeRlmExperimentError) as raised:
                asyncio.run(execute_native_rlm_sidecar_probe(
                    reservation,
                    resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}),
                    root,
                    resources,
                    environ={"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
                    daemon_launcher=launch_daemon,
                    sidecar_launcher=launch_sidecar,
                    probe=fail_probe,
                ))
            self.assertNotIn("SENTINEL_PRIVATE_PROBE", str(raised.exception))
            self.assertTrue(daemon.terminated)

    def test_preparation_uses_private_default_authority(self) -> None:
        reservation = prepare_native_rlm_experiment(
            None,
            max_cost_micros=None,
            deadline_ms=None,
            environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
            now_ms=1_000,
        )

        self.assertEqual(reservation.authority.allowed_portfolio[0].provider_id, "asterion.prime-gateway")
        self.assertEqual(reservation.authority.max_recursion_depth, 1)
        self.assertEqual(reservation.authority.max_concurrent_children, 1)
        self.assertEqual(reservation.limits.cost_micros, 500_000)
        self.assertEqual(reservation.limits.deadline_ms, 600_000)
        self.assertEqual(len(reservation.configuration_digest), 64)

    def test_sidecar_descriptor_binds_authority_budget_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "authority.json"
            authority.write_text(json.dumps(_authority()), encoding="utf-8")
            reservation = prepare_native_rlm_experiment(authority, max_cost_micros=500_000, deadline_ms=600_000, environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}, now_ms=1_000)
            resources = NativeRlmRuntimeResources(
                node_executable=root / "node",
                daemon_entry=root / "prime-daemon.mjs",
                sidecar_entry=root / "gateway.mjs",
                artifact_lock_path=root / "artifact-lock.json",
                prime_source_root=root / "prime-source",
                skill_path=root / "skill",
                expected_runtime_build_id="build-1",
            )
            descriptor = build_native_rlm_sidecar_descriptor(
                reservation,
                resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}),
                root,
                resources,
            )
            self.assertEqual(descriptor["provider"], "deepseek")
            self.assertEqual(descriptor["model"], "deepseek-v4-flash")
            self.assertEqual(descriptor["remainingBudget"]["cost_micros"], 500_000)
            self.assertEqual(descriptor["rlmMaxDepth"], 1)
            self.assertEqual(descriptor["artifactLockPath"], str(resources.artifact_lock_path))
            self.assertEqual(descriptor["primeSourceRoot"], str(resources.prime_source_root))
            self.assertEqual(descriptor["skillPath"], str(resources.skill_path))
            self.assertEqual(descriptor["expectedRuntimeBuildId"], "build-1")

    def test_daemon_start_waits_for_owned_socket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            socket = root / "prime.sock"
            selection = resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
            plan = build_native_rlm_daemon_plan(Path("node"), Path("cli.js"), socket, selection, {"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"})

            class Process:
                returncode = None

            async def launcher(_plan):
                socket.touch()
                return Process()

            process = asyncio.run(start_native_rlm_daemon(plan, launcher=launcher, timeout_seconds=1))
            self.assertIsInstance(process, Process)

    def test_daemon_start_reaps_owned_process_when_socket_never_appears(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selection = resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"})
            plan = build_native_rlm_daemon_plan(Path("node"), Path("cli.js"), root / "missing.sock", selection, {"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"})

            class Process:
                returncode = None
                terminated = False

                def terminate(self):
                    self.terminated = True
                    self.returncode = 0

                async def wait(self):
                    return 0

            process = Process()

            async def launcher(_plan):
                return process

            with self.assertRaises(PrimeRlmExperimentError):
                asyncio.run(start_native_rlm_daemon(plan, launcher=launcher, timeout_seconds=0.01))
            self.assertTrue(process.terminated)

    def test_daemon_plan_uses_direct_pinned_runtime_and_selected_model(self) -> None:
        selection = resolve_native_rlm_model(
            {"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}
        )
        plan = build_native_rlm_daemon_plan(
            Path("/private/node"), Path("/private/prime-cli.js"), Path("/private/prime.sock"),
            selection, {"HOME": "/private/home", "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
        )
        self.assertEqual(plan.argv, ("/private/node", "/private/prime-cli.js", "--mode", "daemon", "--daemon-socket", "/private/prime.sock", "--provider", "deepseek", "--model", "deepseek-v4-flash"))
        self.assertNotIn("secret", repr(plan))

    def test_resolves_only_the_pinned_deepseek_experiment_model(self) -> None:
        selection = resolve_native_rlm_model(
            {"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}
        )
        self.assertEqual(selection.provider, "deepseek")
        self.assertEqual(selection.model, "deepseek-v4-flash")
        self.assertEqual(selection.credential_env, "DEEPSEEK_API_KEY")
        with self.assertRaises(PrimeRlmExperimentError):
            resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "other"})

    def test_daemon_environment_forwards_only_selected_credential(self) -> None:
        environment = build_native_rlm_daemon_environment(
            {"HOME": "/private/home", "PATH": "/bin", "DEEPSEEK_API_KEY": "secret", "OTHER": "no"},
            credential_env="DEEPSEEK_API_KEY",
        )
        self.assertEqual(environment["DEEPSEEK_API_KEY"], "secret")
        self.assertEqual(set(environment), {"HOME", "PATH", "DEEPSEEK_API_KEY"})
        self.assertNotIn("secret", repr(environment))

    def test_preparation_binds_private_model_as_a_digest_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = Path(directory) / "authority.json"
            authority.write_text(json.dumps(_authority()), encoding="utf-8")

            reservation = prepare_native_rlm_experiment(
                authority,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"},
                now_ms=1_000,
            )

            self.assertEqual(reservation.limits.cost_micros, 500_000)
            self.assertEqual(reservation.limits.deadline_ms, 600_000)
            self.assertEqual(len(reservation.configuration_digest), 64)
            self.assertFalse(reservation.consumed)
            self.assertTrue(reservation.consume().consumed)

    def test_preparation_rejects_invalid_limits_model_and_reuse_without_leaking(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = Path(directory) / "authority.json"
            authority.write_text(json.dumps(_authority()), encoding="utf-8")
            invalid = (
                ({}, 500_000, 600_000),
                ({"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"}, 500_001, 600_000),
                ({"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"}, 500_000, 600_001),
            )
            for environ, cost, deadline in invalid:
                with self.subTest(environ=environ, cost=cost, deadline=deadline), self.assertRaises(
                    PrimeRlmExperimentError
                ) as raised:
                    prepare_native_rlm_experiment(
                        authority,
                        max_cost_micros=cost,
                        deadline_ms=deadline,
                        environ=environ,
                        now_ms=1_000,
                    )
                self.assertNotIn("private-model", str(raised.exception))
            reservation = prepare_native_rlm_experiment(
                authority,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"},
                now_ms=1_000,
            ).consume()
            with self.assertRaises(PrimeRlmExperimentError):
                reservation.consume()

    def test_receipt_requires_complete_bounded_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authority = root / "authority.json"
            authority.write_text(json.dumps(_authority()), encoding="utf-8")
            reservation = prepare_native_rlm_experiment(
                authority,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"},
                now_ms=1_000,
            ).consume()

            report = write_native_rlm_experiment_receipt(
                root,
                reservation,
                terminal="completed",
                child_started=True,
                message_delivered=True,
                child_deleted=True,
                usage=BudgetUsage(1, 1, 1, 3, 3),
            )

            self.assertEqual(report["status"], "PASS")
            self.assertNotIn("private-model", repr(report))
            receipt = root / "native-rlm-experiment-receipt.json"
            self.assertEqual(os.stat(receipt).st_mode & 0o777, 0o600)
            self.assertNotIn("private-model", receipt.read_text(encoding="utf-8"))
            for changes in (
                {"child_deleted": False},
                {"terminal": "uncertain"},
                {"usage": BudgetUsage(1, 1, 1, 3, 500_001)},
            ):
                with self.subTest(changes=changes):
                    arguments = {
                        "child_started": True,
                        "message_delivered": True,
                        "child_deleted": True,
                        "terminal": "completed",
                        "usage": BudgetUsage(1, 1, 1, 3, 3),
                    }
                    arguments.update(changes)
                    self.assertNotEqual(
                        write_native_rlm_experiment_receipt(
                            root, reservation, **arguments,
                        )["status"],
                        "PASS",
                    )

    def test_runner_consumes_once_and_classifies_incomplete_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            authority = Path(directory) / "authority.json"
            authority.write_text(json.dumps(_authority()), encoding="utf-8")
            reservation = prepare_native_rlm_experiment(
                authority, max_cost_micros=500_000, deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "private-model"}, now_ms=1_000,
            )

            async def incomplete(_reservation):
                return NativeRlmProbeResult("completed", True, True, False, BudgetUsage(1, 1, 1, 3, 3))

            report = asyncio.run(run_native_rlm_experiment(reservation, incomplete))
            self.assertEqual(report["status"], "External-limited")
            self.assertNotIn("private-model", repr(report))
