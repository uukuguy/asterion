from __future__ import annotations

import json
import os
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from asterion.control.authority import BudgetUsage
import tools.prime_native_rlm_experiment as native_rlm
from tools.prime_native_rlm_experiment import (
    build_native_rlm_daemon_environment,
    build_native_rlm_daemon_plan,
    build_native_rlm_experiment_system,
    build_native_rlm_control_host,
    build_native_rlm_sidecar_descriptor,
    execute_native_rlm_sidecar_probe,
    start_native_rlm_sidecar,
    launch_owned_native_rlm_daemon,
    run_owned_native_rlm_sidecar_probe,
    run_native_rlm_controlled_probe,
    classify_native_rlm_probe_observation,
    observe_native_rlm_probe,
    collect_native_rlm_message_action_ids,
    observe_native_rlm_gateway_probe,
    start_native_rlm_daemon,
    resolve_native_rlm_model,
    NativeRlmProbeResult,
    NativeRlmPrivateGoal,
    NativeRlmRuntimeResources,
    PrimeRlmExperimentError,
    prepare_native_rlm_experiment,
    prepare_native_rlm_workspace,
    native_rlm_session_create_command,
    native_rlm_start_command,
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
    def test_controlled_probe_cancels_created_root_before_closing_after_failure(self) -> None:
        class Host:
            def __init__(self) -> None:
                self.commands = []
                self.closed = False

            async def dispatch(self, command) -> None:
                self.commands.append(command)

            async def pump(self) -> None:
                if len(self.commands) > 1:
                    raise RuntimeError("injected")

            async def close(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = prepare_native_rlm_experiment(
                None,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
                now_ms=1_000,
            )
            host = Host()
            with mock.patch.object(native_rlm, "build_native_rlm_control_host", return_value=host):
                with self.assertRaises(PrimeRlmExperimentError):
                    asyncio.run(
                        run_native_rlm_controlled_probe(
                            object(), reservation, root, progress_root=root
                        )
                    )

            progress = json.loads(
                (root / "native-rlm-progress.json").read_text(encoding="utf-8")
            )
            self.assertEqual(progress["format"], "asterion.prime-native-rlm-progress/v1")
            self.assertEqual(progress["stage"], "running")
            self.assertFalse(progress["child_started"])
            self.assertEqual(
                (root / "native-rlm-progress.json").stat().st_mode & 0o777, 0o600
            )

        self.assertEqual([command.type for command in host.commands], [
            "session.create", "input.submit", "session.cancel",
        ])
        self.assertEqual(host.commands[-1].payload, {"reason_code": "probe-cleanup"})
        self.assertTrue(host.closed)

    def test_controlled_probe_classifies_event_transport_without_details(self) -> None:
        class Host:
            def __init__(self) -> None:
                self.commands = []

            async def dispatch(self, command) -> None:
                self.commands.append(command)

            async def pump(self) -> None:
                if len(self.commands) > 1:
                    raise native_rlm.ControlHostTransportError("SENTINEL_PRIVATE")

            async def close(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = prepare_native_rlm_experiment(
                None, max_cost_micros=None, deadline_ms=None,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}, now_ms=1_000,
            )
            with mock.patch.object(native_rlm, "build_native_rlm_control_host", return_value=Host()):
                with self.assertRaisesRegex(
                    PrimeRlmExperimentError,
                    "Native RLM controlled probe running event-transport did not complete",
                ) as raised:
                    asyncio.run(run_native_rlm_controlled_probe(object(), reservation, root))

        self.assertNotIn("SENTINEL_PRIVATE", str(raised.exception))

    def test_controlled_probe_projects_a_recorded_terminal_after_stream_failure(self) -> None:
        class Host:
            def __init__(self) -> None:
                self.commands = []
                self.closed = False

            async def dispatch(self, command) -> None:
                self.commands.append(command)

            async def pump(self) -> None:
                if len(self.commands) > 1:
                    raise RuntimeError("stream closed")

            def snapshot(self):
                return type(
                    "Snapshot",
                    (),
                    {"state": type("State", (), {"terminal_event_id": "event-3", "session_status": "failed"})()},
                )()

            async def close(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = prepare_native_rlm_experiment(
                None,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
                now_ms=1_000,
            )
            host = Host()
            with mock.patch.object(native_rlm, "build_native_rlm_control_host", return_value=host):
                result = asyncio.run(run_native_rlm_controlled_probe(object(), reservation, root))

        self.assertEqual(result.terminal, "failed")
        self.assertEqual([command.type for command in host.commands], [
            "session.create", "input.submit",
        ])
        self.assertTrue(host.closed)

    def test_controlled_probe_records_failed_terminal_before_lifecycle_read(self) -> None:
        class Host:
            async def dispatch(self, _command) -> None:
                return None

            async def pump(self) -> None:
                return None

            def snapshot(self):
                return type(
                    "Snapshot",
                    (),
                    {
                        "authority_usage": BudgetUsage(1, 0, 0, 1, 0),
                        "state": type(
                            "State",
                            (),
                            {"terminal_event_id": "event-3", "session_status": "failed"},
                        )(),
                    },
                )()

            async def close(self) -> None:
                raise RuntimeError("transport already closed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = prepare_native_rlm_experiment(
                None,
                max_cost_micros=500_000,
                deadline_ms=600_000,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
                now_ms=1_000,
            )
            with mock.patch.object(
                native_rlm, "build_native_rlm_control_host", return_value=Host()
            ), mock.patch.object(
                native_rlm, "observe_native_rlm_gateway_probe", new_callable=mock.AsyncMock
            ) as observe:
                result = asyncio.run(run_native_rlm_controlled_probe(object(), reservation, root))

        self.assertEqual(result.terminal, "failed")
        self.assertEqual(result.usage.controller_tokens, 1)
        observe.assert_not_awaited()

    def test_workspace_preparation_creates_only_private_session_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_native_rlm_workspace(root)

            self.assertEqual(
                sorted(path.name for path in root.iterdir()),
                ["agent", "gateway", "sessions", "workspace"],
            )
            self.assertTrue(
                all(
                    (root / name).stat().st_mode & 0o777 == 0o700
                    for name in ("agent", "gateway", "sessions", "workspace")
                )
            )

    def test_control_only_system_matches_the_default_one_shot_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            system = build_native_rlm_experiment_system(root)
            reservation = prepare_native_rlm_experiment(
                None,
                max_cost_micros=None,
                deadline_ms=None,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
                now_ms=1_000,
            )

            self.assertEqual(system.system_id, "native-rlm-probe")
            self.assertEqual(
                set(system.portfolio_by_identity),
                {
                    (
                        "asterion.prime-gateway",
                        "native-rlm-probe",
                        "0.1.0",
                        "prime.gateway",
                    )
                },
            )
            command = native_rlm_session_create_command(reservation)
            self.assertEqual(command.payload["system_id"], system.system_id)
            self.assertNotIn("spawn", repr(command))
            start = native_rlm_start_command(reservation)
            self.assertEqual(start.type, "input.submit")
            self.assertEqual(start.payload["delivery"], "direct")
            self.assertEqual(start.payload["content_ref"], "native-rlm-start-input")

    def test_private_goal_resolves_only_the_root_reference(self) -> None:
        goal = NativeRlmPrivateGoal("private native instruction")

        self.assertEqual(
            goal.resolve_text("native-rlm-goal", max_bytes=100),
            "private native instruction",
        )
        self.assertEqual(
            goal.resolve_text("native-rlm-start-input", max_bytes=100),
            "private native instruction",
        )
        with self.assertRaises(KeyError):
            goal.resolve_text("other", max_bytes=100)
        self.assertNotIn("private native instruction", repr(goal))

    def test_control_host_rejects_a_non_sidecar_before_opening_private_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reservation = prepare_native_rlm_experiment(
                None,
                max_cost_micros=None,
                deadline_ms=None,
                environ={"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"},
                now_ms=1_000,
            )
            with self.assertRaisesRegex(PrimeRlmExperimentError, "control host"):
                build_native_rlm_control_host(
                    object(), reservation, root, goal=NativeRlmPrivateGoal("private")
                )

    def test_gateway_probe_observer_composes_message_collection_and_lifecycle(self) -> None:
        class Event:
            type = "action.proposed"
            payload = {"kind": "child.message", "action_id": "message-1"}

        class Lifecycle:
            def __init__(self, type, child_id, status=None):
                self.type, self.child_id, self.status = type, child_id, status

        class Binding:
            delivered = True

        class Client:
            async def events(self):
                yield Event()

            async def rlm_lifecycle(self):
                return (Lifecycle("rlm.child.started", "child-1"), Lifecycle("rlm.child.terminal", "child-1", "completed"), Lifecycle("rlm.child.deleted", "child-1"))

            async def rlm_message_binding(self, _action_id):
                return Binding()

        self.assertEqual(
            asyncio.run(observe_native_rlm_gateway_probe(Client(), usage=BudgetUsage(1, 1, 1, 3, 3))).terminal,
            "completed",
        )

    def test_message_action_collector_uses_only_child_message_proposals(self) -> None:
        class Event:
            def __init__(self, type, payload):
                self.type = type
                self.payload = payload

        class Client:
            async def events(self):
                yield Event("action.proposed", {"kind": "child.spawn", "action_id": "spawn-1"})
                yield Event("action.proposed", {"kind": "child.message", "action_id": "message-1"})
                yield Event("action.proposed", {"kind": "child.message", "action_id": "message-1"})
                yield Event("action.succeeded", {"action_id": "message-2"})

        self.assertEqual(
            asyncio.run(collect_native_rlm_message_action_ids(Client())),
            ("message-1",),
        )

    def test_probe_observer_reads_only_closed_gateway_evidence(self) -> None:
        class Lifecycle:
            def __init__(self, type, child_id, status=None):
                self.type = type
                self.child_id = child_id
                self.status = status

        class Binding:
            delivered = True

        class Client:
            async def rlm_lifecycle(self):
                return (
                    Lifecycle("rlm.child.started", "child-1"),
                    Lifecycle("rlm.child.terminal", "child-1", "completed"),
                    Lifecycle("rlm.child.deleted", "child-1"),
                )

            async def rlm_message_binding(self, action_id):
                self.action_id = action_id
                return Binding()

        client = Client()
        result = asyncio.run(observe_native_rlm_probe(
            client, message_action_ids=("action-1",), usage=BudgetUsage(1, 1, 1, 3, 3)
        ))

        self.assertEqual(result.terminal, "completed")
        self.assertEqual(client.action_id, "action-1")

    def test_probe_observation_requires_started_completed_child_and_delivered_message(self) -> None:
        complete = classify_native_rlm_probe_observation(
            (
                {"type": "rlm.child.started", "child_id": "child-1"},
                {"type": "rlm.child.terminal", "child_id": "child-1", "status": "completed"},
                {"type": "rlm.child.deleted", "child_id": "child-1"},
            ),
            message_delivered=True,
            usage=BudgetUsage(1, 1, 1, 3, 3),
        )
        self.assertEqual(complete.terminal, "completed")
        self.assertTrue(complete.child_started)
        self.assertTrue(complete.message_delivered)
        self.assertTrue(complete.child_deleted)

        not_deleted = classify_native_rlm_probe_observation(
            (
                {"type": "rlm.child.started", "child_id": "child-1"},
                {"type": "rlm.child.terminal", "child_id": "child-1", "status": "completed"},
            ),
            message_delivered=True,
            usage=BudgetUsage(1, 1, 1, 3, 3),
        )
        self.assertEqual(not_deleted.terminal, "uncertain")
        self.assertFalse(not_deleted.child_deleted)

        incomplete = classify_native_rlm_probe_observation(
            ({"type": "rlm.child.started", "child_id": "child-1"},),
            message_delivered=False,
            usage=BudgetUsage(1, 1, 1, 3, 3),
        )
        self.assertEqual(incomplete.terminal, "uncertain")

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

            daemon = Daemon()

            async def spawn(*_args, **_kwargs):
                (root / "prime.sock").touch()
                return daemon

            async def start_sidecar(options):
                self.assertEqual(set(options.environ), {"HOME", "PATH"})
                return Sidecar()

            async def probe(_sidecar):
                return NativeRlmProbeResult("completed", True, True, True, BudgetUsage(1, 1, 1, 3, 3))

            async def await_cleanup():
                return None

            async def shutdown(_plan, _resources):
                daemon.returncode = 0

            result = asyncio.run(run_owned_native_rlm_sidecar_probe(
                reservation,
                resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}),
                root,
                resources,
                environ={"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
                probe=probe,
                daemon_spawn=spawn,
                sidecar_starter=start_sidecar,
                owned_worker_cleanup=await_cleanup,
                owned_daemon_shutdown=shutdown,
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

            with (root / "private-stderr.log").open("wb") as stderr_sink:
                asyncio.run(start_native_rlm_sidecar(
                    {"sessionId": "native-rlm-root"}, resources,
                    environ={"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
                    starter=starter,
                    private_stderr_sink=stderr_sink,
                ))

            self.assertEqual(
                seen[0].argv,
                (
                    str(resources.node_executable.resolve(strict=False)),
                    str(resources.sidecar_entry.resolve(strict=False)),
                ),
            )
            self.assertEqual(set(seen[0].environ), {"HOME", "PATH"})
            self.assertIs(seen[0].private_stderr_sink, stderr_sink)
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
            cleanup_observed = []

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

            async def await_owned_worker_cleanup():
                self.assertTrue(sidecar.closed)
                cleanup_observed.append(True)

            async def shutdown(_plan, _resources):
                daemon.returncode = 0

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
                    owned_worker_cleanup=await_owned_worker_cleanup,
                    owned_daemon_shutdown=shutdown,
                )
            )

            self.assertEqual(result.terminal, "completed")
            self.assertTrue(sidecar.closed)
            self.assertEqual(cleanup_observed, [True])
            self.assertFalse(daemon.terminated)

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

            cleanup_observed = []

            class Sidecar:
                async def close(self):
                    raise RuntimeError("SENTINEL_PRIVATE_CLOSE")

            daemon = Daemon()

            async def launch_daemon(plan):
                plan.socket_path.touch()
                return daemon

            async def launch_sidecar(_descriptor, _resources):
                return Sidecar()

            async def fail_probe(_sidecar):
                raise RuntimeError("SENTINEL_PRIVATE_PROBE")

            async def await_owned_worker_cleanup():
                cleanup_observed.append(True)

            async def shutdown(_plan, _resources):
                daemon.returncode = 0

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
                    owned_worker_cleanup=await_owned_worker_cleanup,
                    owned_daemon_shutdown=shutdown,
                ))
            self.assertNotIn("SENTINEL_PRIVATE_PROBE", str(raised.exception))
            self.assertEqual(cleanup_observed, [True])
            self.assertFalse(daemon.terminated)

    def test_sidecar_probe_recovers_only_the_owned_inactive_root(self) -> None:
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

            async def shutdown(_plan, _resources):
                daemon.returncode = 0

            with mock.patch.object(
                native_rlm, "_owned_native_rlm_root_is_inactive", return_value=True
            ) as inactive:
                result = asyncio.run(execute_native_rlm_sidecar_probe(
                    reservation,
                    resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}),
                    root,
                    resources,
                    environ={"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
                    daemon_launcher=launch_daemon,
                    sidecar_launcher=launch_sidecar,
                    probe=fail_probe,
                    owned_daemon_shutdown=shutdown,
                ))

            self.assertTrue(inactive.awaited)
            self.assertEqual(result.terminal, "failed")
            self.assertFalse(result.child_started)
            self.assertEqual(result.usage, BudgetUsage.zero())

    def test_inactive_root_probe_uses_root_sidecar_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resources = NativeRlmRuntimeResources(
                root / "node", root / "daemon.mjs", root / "gateway.mjs", root / "lock.json",
                root / "source", root / "skill", "build-1",
            )
            plan = build_native_rlm_daemon_plan(
                resources.node_executable, resources.daemon_entry, root / "prime.sock",
                resolve_native_rlm_model({"ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}),
                {"HOME": str(root), "PATH": "/bin", "DEEPSEEK_API_KEY": "secret"},
            )
            captured = []

            class Process:
                async def wait(self):
                    return 0

            async def spawn(*args, **kwargs):
                captured.append(args)
                return Process()

            with mock.patch.object(asyncio, "create_subprocess_exec", side_effect=spawn):
                result = asyncio.run(native_rlm._owned_native_rlm_root_is_inactive(plan, resources))

            self.assertTrue(result)
            self.assertIn('clientId: "asterion-native-rlm-root"', captured[0][-1])
            self.assertNotIn("DEEPSEEK_API_KEY", captured[0][-1])

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
        self.assertEqual(reservation.authority.budget_limit.controller_tokens, 50_000)
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
            self.assertEqual(descriptor["maxContinuations"], 3)
            self.assertEqual(descriptor["maxTurns"], 12)
            self.assertEqual(descriptor["remainingBudget"]["cost_micros"], 500_000)
            self.assertEqual(descriptor["rlmMaxChildren"], 1)
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
        self.assertEqual(
            plan.argv,
            (
                "/private/node",
                "/private/prime-cli.js",
                "--mode",
                "daemon",
                "--daemon-socket",
                "/private/prime.sock",
            ),
        )
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

    def test_daemon_environment_forwards_selected_credential_and_kernel_runtime(
        self,
    ) -> None:
        environment = build_native_rlm_daemon_environment(
            {
                "HOME": "/private/home",
                "PATH": "/bin",
                "DEEPSEEK_API_KEY": "secret",
                "PRIME_AGENT_KERNEL_PYTHON": "/private/kernel/python",
                "PRIME_AGENT_KERNEL_VENV": "/private/kernel-venv",
                "OTHER": "no",
            },
            credential_env="DEEPSEEK_API_KEY",
        )
        self.assertEqual(environment["DEEPSEEK_API_KEY"], "secret")
        self.assertEqual(
            environment["PRIME_AGENT_KERNEL_PYTHON"], "/private/kernel/python"
        )
        self.assertEqual(
            environment["PRIME_AGENT_KERNEL_VENV"], "/private/kernel-venv"
        )
        self.assertEqual(
            set(environment),
            {
                "HOME",
                "PATH",
                "DEEPSEEK_API_KEY",
                "PRIME_AGENT_KERNEL_PYTHON",
                "PRIME_AGENT_KERNEL_VENV",
            },
        )
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
