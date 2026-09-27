"""Native P7 application/provider and Asterion-prime binding tests."""

from __future__ import annotations

import json
import asyncio
import tempfile
import tomllib
import unittest
from importlib import metadata
from pathlib import Path
from types import MappingProxyType
from typing import AsyncIterator, cast

from asterion.agents.prime.session import ASTERION_PRIME_LIMITS
from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.applications.discovery import (
    list_application_providers,
    load_application_provider,
    select_application_provider_id,
)
from asterion.applications.first_party_packages import (
    create_prime_arc_agi_3_solver_package,
    create_prime_bounded_autonomy_native_package,
    create_prime_continual_improvement_native_package,
    create_prime_ipython_coding_native_package,
    create_prime_long_session_continuity_native_package,
    create_prime_programmatic_long_context_native_package,
    create_prime_recursive_workflow_native_package,
)
from asterion.applications.provider import (
    compose_installed_provider,
    resolve_installed_provider,
)
from asterion.applications.prime import create_prime_arc_agi_3_solving_provider, create_provider
from asterion.applications.prime.p7.ipython_host import (
    IpythonWorkerResult,
    P7ClientFacade,
    PersistentIpythonHost,
    p7_client_facade,
)
from asterion.applications.prime.p7.game import P7GameSelection
from asterion.applications.prime.p7.operator import (
    P7OperatorError,
    P7RuntimeSelection,
    build_p7_operator_resources,
    p7_runtime_options,
    resolve_p7_runtime,
)
from asterion.applications.prime.p7.prompt import P7_SOLVE_PROMPT
from asterion.applications.prime.p7.private_trace import P7PrivateTraceReceipt
from asterion.capabilities.execution import CapabilityInvocation
from asterion.capabilities.prime_arc_agi_3_solver.host import (
    PrimeArcAgi3SolveReceipt,
)
from asterion.capabilities.prime_arc_agi_3_solver.provider import CAPABILITY_REF
from asterion.applications.prime.runtime_binding import (
    PrimeLaunch,
    _P7SolveEventProjector,
    asterion_prime_runtime_binding,
)
from asterion.capability_packages import CapabilityPackageRef
from asterion.applications.prime.p7.broker import ArcBroker
from asterion.runtime.factory import (
    RuntimeFactoryContext,
    RuntimeFactoryError,
    RuntimeFactoryRegistry,
)
from asterion.runtime.defaults import default_runtime_factory_registry
from asterion.runtime.host import (
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient
from asterion.runtimes.pi_extensions import PiExtensionBinding


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = (
    ROOT / "src/asterion/applications/prime/assemblies/prime-arc-agi-3-solving.json"
)


class _Engine:
    game_id = "ls20-9607627b"
    seed = 0

    def observe(self) -> dict[str, object]:
        return {
            "available_actions": ["ACTION1"],
            "frame": [[[0]]],
            "levels_completed": 0,
            "state": "NOT_FINISHED",
            "win_levels": 7,
        }

    def step(self, action: str) -> dict[str, object]:
        del action
        return self.observe()


class _Worker:
    def __init__(self) -> None:
        self.starts = 0

    async def start(
        self, p7_client: P7ClientFacade, *, signal: CancellationSignal
    ) -> None:
        del p7_client, signal
        self.starts += 1

    async def execute_cell(
        self, code: str, *, signal: CancellationSignal
    ) -> IpythonWorkerResult:
        del code, signal
        raise AssertionError("worker must remain inert")

    async def close(self) -> None:
        pass


class _CompletingEngine(_Engine):
    def step(self, action: str) -> dict[str, object]:
        del action
        observation = self.observe()
        observation["levels_completed"] = 1
        observation["state"] = "FINISHED"
        return observation


class _CompletingRuntime:
    def __init__(self, broker: ArcBroker) -> None:
        self.broker = broker
        self.requests: list[RunRequest] = []

    @property
    def manifest(self) -> RuntimeManifest:
        return RuntimeManifest("asterion.prime", ("prime.tool.ipython",))

    async def run(
        self, request: RunRequest, *, signal: object = None
    ) -> AsyncIterator[RunEvent]:
        del signal
        self.requests.append(request)
        self.broker.act(("ACTION1",))
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id=request.run_id,
            completed_level_count=1,
            primitive_action_count=1,
            partial_game_score="3.571429",
        )
        yield RunEvent(
            request.run_id,
            1,
            "run.started",
            {"capabilities": ["prime.tool.ipython"]},
        )
        yield RunEvent(
            request.run_id,
            2,
            "artifact.created",
            {
                "artifact": {
                    "artifact_id": "prime.p7-solving.receipt",
                    "kind": "p7-solving",
                    "media_type": (
                        "application/vnd.asterion.prime.p7-solving-receipt+json"
                    ),
                    "sha256": receipt.receipt_sha256.removeprefix("sha256:"),
                }
            },
        )
        yield RunEvent(request.run_id, 3, "run.completed", {"status": "completed"})


class TestPrimeP7NativeProvider(unittest.TestCase):
    def test_p7_runtime_terminal_predicate_stops_after_game_over(self) -> None:
        from asterion.applications.prime.runtime_binding import _p7_terminal
        from tests.test_prime_p7_native_broker import _Engine as TerminalEngine

        broker = ArcBroker(engine=TerminalEngine(game_over_after=1))
        self.assertFalse(_p7_terminal(broker))
        broker.act(("ACTION1",))
        self.assertTrue(_p7_terminal(broker))
        self.assertEqual(broker.seal().levels_completed, 0)

    def test_p7_projector_persists_usage_without_widening_public_stream(
        self,
    ) -> None:
        async def native_events() -> AsyncIterator[RunEvent]:
            yield RunEvent(
                "usage-run",
                1,
                "run.started",
                {"capabilities": ["prime.tool.ipython"]},
            )
            yield RunEvent(
                "usage-run",
                2,
                "usage.reported",
                {"input_tokens": 120, "output_tokens": 31},
            )
            yield RunEvent(
                "usage-run", 3, "run.completed", {"status": "completed"}
            )

        async def collect(projector: _P7SolveEventProjector) -> tuple[RunEvent, ...]:
            request = RunRequest(
                run_id="usage-run",
                input_text=P7_SOLVE_PROMPT,
                requested_capabilities=("prime.tool.ipython",),
            )
            return tuple([event async for event in projector(request, native_events())])

        with tempfile.TemporaryDirectory() as directory:
            trace_root = Path(directory).resolve()
            broker = ArcBroker(engine=_CompletingEngine())
            broker.act(("ACTION1",))
            adapter = P7PrivateTraceReceipt(broker, PrimeTraceRecorder(trace_root))
            projected = asyncio.run(collect(_P7SolveEventProjector(adapter)))
            artifact = projected[1].payload["artifact"]
            assert isinstance(artifact, MappingProxyType)
            adapter.get_receipt(
                run_id="usage-run",
                receipt_sha256="sha256:" + str(artifact["sha256"]),
            )

            self.assertEqual(
                tuple(event.type for event in projected),
                ("run.started", "artifact.created", "run.completed"),
            )
            entries = [
                json.loads(line)
                for line in (trace_root / "prime-trace.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            usage = [entry for entry in entries if entry["kind"] == "arc.usage.reported"]
            self.assertEqual(
                [entry["payload"] for entry in usage],
                [{"input_tokens": 120, "output_tokens": 31}],
            )
            self.assertNotIn("usage.reported", repr(projected))

    def test_p7_application_selects_only_asterion_prime(self) -> None:
        provider = create_provider()

        self.assertEqual(provider.provider_id, "prime-applications")
        # All seven native prime applications are now published after Phase 9
        # (P1-P7 native). prime.arc-agi-3-solving remains at index 0.
        self.assertEqual(
            tuple(application.application_id for application in provider.applications),
            (
                "prime.arc-agi-3-solving",
                "prime.bounded-autonomy",
                "prime.continual-improvement",
                "prime.ipython-coding",
                "prime.long-session-continuity",
                "prime.recursive-workflow",
                "prime.programmatic-long-context",
            ),
        )
        application = provider.applications[0]
        self.assertEqual(
            (application.application_id, application.version),
            ("prime.arc-agi-3-solving", "1.0.0"),
        )
        self.assertEqual(application.runtime_ids, ("asterion.prime",))
        self.assertEqual(
            application.capability_packages,
            (CapabilityPackageRef("prime-arc-agi-3-solver", "1.0.0"),),
        )

    def test_p7_only_provider_resolves_with_only_its_capability_package(self) -> None:
        provider = resolve_installed_provider(
            create_prime_arc_agi_3_solving_provider(),
            runtime_factories=default_runtime_factory_registry(),
            installed_packages=(create_prime_arc_agi_3_solver_package(),),
        )

        self.assertEqual(
            tuple(application.application_id for application in provider.applications),
            ("prime.arc-agi-3-solving",),
        )

    def test_p7_application_composes_package_over_runtime_tool_capability(self) -> None:
        composed = compose_installed_provider(
            create_provider(),
            runtime_factories=RuntimeFactoryRegistry(()),
            installed_packages=tuple(
                factory()
                for factory in (
                    create_prime_arc_agi_3_solver_package,
                    create_prime_ipython_coding_native_package,
                    create_prime_programmatic_long_context_native_package,
                    create_prime_long_session_continuity_native_package,
                    create_prime_recursive_workflow_native_package,
                    create_prime_bounded_autonomy_native_package,
                    create_prime_continual_improvement_native_package,
                )
            ),
        )

        assembly = composed.applications[0].assemblies[0]
        runtime_binding = assembly.runtime_binding
        self.assertIsNotNone(runtime_binding)
        assert runtime_binding is not None
        self.assertEqual(assembly.runtime_id, "asterion.prime")
        self.assertEqual(
            runtime_binding.capabilities,
            ("prime.tool.ipython",),
        )
        self.assertEqual(
            assembly.plan.host_capabilities,
            (
                "prime.arc-broker",
                "prime.ipython",
                "prime.launch",
                "prime.private-trace",
            ),
        )

    def test_installed_listing_and_index_are_metadata_only(self) -> None:
        entries = tuple(metadata.entry_points(group="asterion.applications"))

        self.assertIn(
            "prime-applications",
            tuple(
                item.provider_id
                for item in list_application_providers(entry_points=entries)
            ),
        )
        self.assertEqual(
            select_application_provider_id("prime.arc-agi-3-solving@1.0.0"),
            "prime-applications",
        )
        self.assertEqual(
            load_application_provider("prime-applications").provider_id,
            "prime-applications",
        )

    def test_assembly_is_closed_sorted_metadata_only(self) -> None:
        value = json.loads(ASSEMBLY.read_text(encoding="utf-8"))

        self.assertEqual(
            value,
            {
                "protocol": "asterion.application-assembly/v1",
                "application_id": "prime.arc-agi-3-solving",
                "version": "1.0.0",
                "runtime_id": "asterion.prime",
                "capability_packages": [
                    {"package_id": "prime-arc-agi-3-solver", "version": "1.0.0"}
                ],
                "capabilities": [
                    {
                        "capability_id": "prime.arc-agi-3-solving",
                        "version": "1.0.0",
                    }
                ],
                "host_capabilities": [
                    "prime.arc-broker",
                    "prime.ipython",
                    "prime.launch",
                    "prime.private-trace",
                ],
                "host_policies": [],
                "host_events": [],
                "host_artifacts": [],
            },
        )
        serialized = json.dumps(value).lower()
        for forbidden in (
            "command",
            "credential",
            "openai-codex",
            "environment",
            "executable",
            "path",
            "prompt",
            "state",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_prompt_is_game_agnostic_and_experiment_driven(self) -> None:
        lowered = " ".join(P7_SOLVE_PROMPT.lower().split())

        for required in (
            "ipython",
            "hypotheses",
            "shortest useful test",
            "before/after",
            "no-ops",
            "death paths",
            "target_level",
            "action1 is up",
            "reset_required",
            "reset the current level",
            "never use python or shell loops to submit actions",
            "[plan]",
            "p7_client.history(0, 32)",
            "p7_client.act_checked(plan)",
        ):
            self.assertIn(required, lowered)
        for forbidden in (
            "ls20",
            "9607627b",
            "seed",
            "golden trace",
            "action3, action3, action3",
        ):
            self.assertNotIn(forbidden, lowered)
        self.assertIn(
            "do not assume a known map, object identity, target coordinate, "
            "or action sequence",
            lowered,
        )

    def test_operator_selection_is_fixed_and_runtime_options_are_immutable(
        self,
    ) -> None:
        selection = resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent")})

        self.assertEqual(
            selection,
            P7RuntimeSelection(
                runtime_id="asterion.prime",
                provider="openai-codex",
                model="gpt-6-sol",
                max_actions=500,
                max_callbacks=128,
                deadline_ms=3_600_000,
            ),
        )
        options = p7_runtime_options(selection)
        self.assertIs(type(options), MappingProxyType)
        self.assertEqual(
            dict(options),
            {
                "deadline_ms": "3600000",
                "max_actions": "500",
                "max_callbacks": "128",
                "model": "gpt-6-sol",
                "provider": "openai-codex",
            },
        )
        self.assertNotIn("private-token", repr(selection))
        self.assertNotIn("private-token", repr(options))

    def test_offline_first_round_removes_runtime_bounds_only_with_explicit_mode(self) -> None:
        from asterion.applications.prime.p7.operator import _sweep_game
        game = _sweep_game(P7GameSelection("ls20-9607627b", 0), None)
        environment = {
            "ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"),
            "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND": "1",
            "ASTERION_PRIME_P7_RUN_MODE": "sweep",
            "OPERATION_MODE": "offline",
        }
        selected = resolve_p7_runtime(environment, game)
        self.assertIsNone(selected.deadline_ms)
        self.assertIsNone(selected.max_callbacks)
        self.assertEqual(selected.max_actions, game.baseline_actions[0])
        self.assertEqual(p7_runtime_options(selected, game)["deadline_ms"], "none")
        for change in (
            {"ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND": "0"},
            {"ASTERION_PRIME_P7_RUN_MODE": "solve"},
            {"OPERATION_MODE": "competition"},
        ):
            with self.subTest(change=change), self.assertRaises(P7OperatorError):
                resolve_p7_runtime({**environment, **change}, game)
        with self.assertRaises(P7OperatorError):
            resolve_p7_runtime(environment)
        from asterion.applications.prime.p7.game import ArcGameContract
        with self.assertRaises(P7OperatorError):
            resolve_p7_runtime(environment, ArcGameContract("ab12-12345678", win_levels=12))

    def test_unbounded_operator_resources_construct_a_no_deadline_session(self) -> None:
        from asterion.applications.prime.p7.operator import _sweep_game
        from asterion.applications.prime.runtime_binding import build_p7_runtime
        game = _sweep_game(P7GameSelection("ls20-9607627b", 0), None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extension = root / "prime_ipython.mjs"
            extension.write_text("export default function extension() {}\n")
            resources = build_p7_operator_resources(
                environment={
                    "ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"),
                    "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND": "1",
                    "ASTERION_PRIME_P7_RUN_MODE": "sweep",
                    "OPERATION_MODE": "offline",
                },
                pi_base_command=("/usr/bin/pi", "--mode", "rpc"),
                extension_path=extension, working_directory=root,
                worker=_Worker(), engine=_CompletingEngine(), private_trace_root=root,
                game=game,
            )
            try:
                runtime = build_p7_runtime(RuntimeFactoryContext(
                    provider_id="prime-applications", application_id="prime.arc-agi-3-solving",
                    application_version="1.0.0", runtime_id="asterion.prime",
                    assembly_path=ASSEMBLY, options=resources.runtime_options,
                    host_services=resources.host_services,
                ))
                self.assertIsNone(runtime._session._rpc_session.config.deadline_seconds)
                self.assertIsNone(runtime._session._limits.model_callbacks)
                self.assertIsNone(runtime._session._limits.tool_callbacks)
                self.assertNotIn("OPERATION_MODE", resources.host_services["prime.launch"].approved_environment)
                runtime._session.close()
            finally:
                asyncio.run(resources.close())

    def test_missing_model_host_fails_with_public_safe_error(self) -> None:
        for environment in ({}, {"ASTERION_PRIME_PI_AGENT_DIR": "   "}):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(
                    P7OperatorError, "P7 model host is unavailable"
                ) as raised:
                    resolve_p7_runtime(environment)
                self.assertNotIn("ASTERION_PRIME_PI_AGENT_DIR", str(raised.exception))

    def test_runtime_binding_assembles_only_exact_preflighted_services(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            broker = ArcBroker(engine=_Engine())
            launch, trace = self._launch(root, broker)
            ipython = PersistentIpythonHost(
                worker=_Worker(), p7_client=p7_client_facade(broker)
            )
            context = RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-solving",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=ASSEMBLY.resolve(),
                options=p7_runtime_options(
                    resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent")})
                ),
                host_services={
                    "prime.arc-broker": broker,
                    "prime.ipython": ipython,
                    "prime.launch": launch,
                    "prime.private-trace": trace,
                },
            )

            binding = asterion_prime_runtime_binding()
            runtime = binding.factory(context)

            self.assertEqual(binding.runtime_id, "asterion.prime")
            self.assertEqual(
                binding.capabilities,
                ("prime.tool.ipython",),
            )
            self.assertIs(type(runtime), AsterionPrimeRuntimeClient)
            self.assertFalse(launch.extension_lease.closed)
            cast(AsterionPrimeRuntimeClient, runtime)._session.close()

    def test_runtime_factory_accepts_only_consistently_recorded_active_prefix(self) -> None:
        from dataclasses import replace
        from asterion.applications.prime.p7.operator import _P7BrokerClient
        from asterion.applications.prime.p7.private_trace import P7_TRACE_IDENTITIES

        cases = (
            "valid", "missing-actions", "extra-action", "forged-action",
            "wrong-identities", "wrong-count", "wrong-level", "reset-required",
            "at-target", "at-cap", "cold-extra-action", "broken-chain",
        )
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                game = P7GameSelection("ls20-9607627b", 0, 7)
                broker = ArcBroker(engine=_CompletingEngine(), game=game)
                launch, trace = self._launch(root, broker)
                recorder = trace.runtime_recorder
                if case in {"missing-actions", "forged-action", "wrong-identities"}:
                    transition = broker.act(("ACTION1",)).transitions[0]
                    if case != "missing-actions":
                        recorder.append(
                            "arc.action",
                            {**P7_TRACE_IDENTITIES, **(
                                {"application_id": "other-app"}
                                if case == "wrong-identities" else {}
                            )},
                            {
                                "action": "ACTION2" if case == "forged-action" else transition.action,
                                "after_sha256": transition.after_sha256,
                                "before_sha256": transition.before_sha256,
                                "levels_completed": transition.levels_completed,
                                "sequence": transition.sequence,
                            },
                        )
                else:
                    _P7BrokerClient(broker, recorder).act([{"name": "ACTION1", "data": {}}])
                if case == "extra-action":
                    recorder.append("arc.action", P7_TRACE_IDENTITIES, recorder.snapshot()[-1].payload)
                elif case == "cold-extra-action":
                    broker._journal.clear()
                    broker._actions_dispatched = 0
                    broker._current = broker._initial
                elif case == "broken-chain":
                    broker._journal[0] = replace(broker._journal[0], before_sha256="sha256:" + "0" * 64)
                elif case == "wrong-count":
                    broker._actions_dispatched += 1
                elif case == "wrong-level":
                    broker._current = replace(broker._current, levels_completed=2)
                elif case == "reset-required":
                    broker._terminal_reason = "reset-required"
                elif case == "at-target":
                    broker._current = replace(broker._current, levels_completed=7)
                elif case == "at-cap":
                    broker._actions_dispatched = game.action_cap
                worker = _Worker()
                ipython = PersistentIpythonHost(worker=worker, p7_client=p7_client_facade(broker))
                context = RuntimeFactoryContext(
                    provider_id="prime-applications",
                    application_id="prime.arc-agi-3-solving",
                    application_version="1.0.0",
                    runtime_id="asterion.prime",
                    assembly_path=ASSEMBLY.resolve(),
                    options=p7_runtime_options(resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent")}, game), game),
                    host_services={
                        "prime.arc-broker": broker,
                        "prime.ipython": ipython,
                        "prime.launch": launch,
                        "prime.private-trace": trace,
                    },
                )
                try:
                    if case == "valid":
                        try:
                            runtime = asterion_prime_runtime_binding().factory(context)
                        except RuntimeFactoryError:
                            self.fail("runtime factory rejected a recorded active prefix")
                        self.assertIs(type(runtime), AsterionPrimeRuntimeClient)
                        cast(AsterionPrimeRuntimeClient, runtime)._session.close()
                        self.assertEqual(broker.status().primitive_actions, 1)
                        self.assertEqual(broker.status().levels_completed, 1)
                    else:
                        with self.assertRaisesRegex(RuntimeFactoryError, "configuration is invalid"):
                            asterion_prime_runtime_binding().factory(context)
                        self.assertTrue(launch.extension_lease.closed)
                    self.assertEqual(worker.starts, 0)
                finally:
                    launch.extension_lease.close()
                    trace.close()

    def test_operator_builds_composed_native_runtime_without_starting_edges(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extension = root / "prime_ipython.mjs"
            extension.write_text(
                "export default function extension() {}\n", encoding="utf-8"
            )
            trace_root = root / "trace"
            trace_root.mkdir()
            worker = _Worker()

            resources = build_p7_operator_resources(
                environment={"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent")},
                pi_base_command=("/usr/bin/pi", "--mode", "rpc"),
                extension_path=extension,
                working_directory=root,
                worker=worker,
                engine=_CompletingEngine(),
                private_trace_root=trace_root,
            )
            composed = compose_installed_provider(
                create_provider(),
                runtime_factories=RuntimeFactoryRegistry(()),
                installed_packages=tuple(
                    factory()
                    for factory in (
                        create_prime_arc_agi_3_solver_package,
                        create_prime_ipython_coding_native_package,
                        create_prime_programmatic_long_context_native_package,
                        create_prime_long_session_continuity_native_package,
                        create_prime_recursive_workflow_native_package,
                        create_prime_bounded_autonomy_native_package,
                        create_prime_continual_improvement_native_package,
                    )
                ),
            )
            assembly = composed.applications[0].assemblies[0]
            assert assembly.runtime_binding is not None
            runtime = assembly.runtime_binding.factory(
                RuntimeFactoryContext(
                    provider_id=composed.provider_id,
                    application_id="prime.arc-agi-3-solving",
                    application_version="1.0.0",
                    runtime_id=assembly.runtime_id,
                    assembly_path=assembly.path,
                    options=resources.runtime_options,
                    host_services=resources.host_services,
                )
            )

            launch = cast(
                PrimeLaunch,
                resources.host_services["prime.launch"],
            )
            self.assertIs(type(runtime), AsterionPrimeRuntimeClient)
            self.assertEqual(launch.approved_command[:2], ("/usr/bin/pi", "--mode"))
            self.assertIn("--provider", launch.approved_command)
            self.assertIn("openai-codex", launch.approved_command)
            self.assertIn("--model", launch.approved_command)
            self.assertIn("gpt-6-sol", launch.approved_command)
            self.assertTrue(launch.approved_command[-len(launch.extension_lease.command_args()):] == launch.extension_lease.command_args())
            self.assertEqual(
                launch.approved_environment["ASTERION_PRIME_PI_AGENT_DIR"],
                str(Path.home() / ".pi/agent"),
            )
            self.assertEqual(worker.starts, 0)
            fake_runtime = _CompletingRuntime(
                cast(ArcBroker, resources.host_services["prime.arc-broker"])
            )
            implementation = dict(composed.applications[0].implementations)[
                CAPABILITY_REF
            ]
            result = asyncio.run(
                implementation.execute(
                    CapabilityInvocation(
                        capability_ref=CAPABILITY_REF,
                        manifest=assembly.plan.capability_manifests[0],
                        run_id="native-composed",
                        input_text=P7_SOLVE_PROMPT,
                        upstream_artifacts=(),
                        runtime=fake_runtime,
                        host_services=resources.host_services,
                    )
                )
            )
            self.assertEqual(len(result.artifacts), 1)
            self.assertEqual(fake_runtime.requests[0].input_text, P7_SOLVE_PROMPT)
            cast(AsterionPrimeRuntimeClient, runtime)._session.close()
            asyncio.run(resources.close())

    def test_runtime_factory_failure_closes_unhanded_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            broker = ArcBroker(engine=_Engine())
            launch, trace = self._launch(root, broker)
            context = RuntimeFactoryContext(
                provider_id="other-provider",
                application_id="prime.arc-agi-3-solving",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=ASSEMBLY.resolve(),
                options={},
                host_services={
                    "prime.arc-broker": broker,
                    "prime.ipython": PersistentIpythonHost(
                        worker=_Worker(),
                        p7_client=p7_client_facade(ArcBroker(engine=_Engine())),
                    ),
                    "prime.launch": launch,
                    "prime.private-trace": trace,
                },
            )

            with self.assertRaisesRegex(
                RuntimeFactoryError, "Asterion-prime runtime configuration is invalid"
            ):
                asterion_prime_runtime_binding().factory(context)
            self.assertTrue(launch.extension_lease.closed)

    def test_runtime_factory_rejects_cap_different_from_selected_full_game(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            game = P7GameSelection("ls20-9607627b", 0, 7)
            broker = ArcBroker(engine=_Engine(), game=game)
            launch, trace = self._launch(root, broker)
            ipython = PersistentIpythonHost(worker=_Worker(), p7_client=p7_client_facade(broker))
            options = dict(p7_runtime_options(resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent")}, game), game))
            options["max_actions"] = "500"
            context = RuntimeFactoryContext(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-solving",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=ASSEMBLY.resolve(),
                options=options,
                host_services={
                    "prime.arc-broker": broker,
                    "prime.ipython": ipython,
                    "prime.launch": launch,
                    "prime.private-trace": trace,
                },
            )
            with self.assertRaisesRegex(RuntimeFactoryError, "configuration is invalid"):
                asterion_prime_runtime_binding().factory(context)
            self.assertTrue(launch.extension_lease.closed)

    def test_private_trace_receipt_rejects_early_mismatch_and_repeated_access(
        self,
    ) -> None:
        from asterion.applications.prime.p7.private_trace import (
            P7PrivateTraceReceipt,
            P7PrivateTraceReceiptError,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for case in ("early", "mismatch", "repeated"):
                with self.subTest(case=case):
                    trace_root = root / case
                    trace_root.mkdir()
                    broker = ArcBroker(engine=_CompletingEngine())
                    recorder = PrimeTraceRecorder(trace_root)
                    adapter = P7PrivateTraceReceipt(broker, recorder)
                    if case != "early":
                        broker.act(("ACTION1",))
                    expected = PrimeArcAgi3SolveReceipt.create(
                        run_id="adapter-run",
                        completed_level_count=1,
                        primitive_action_count=1,
                        partial_game_score="3.571429",
                    )
                    digest = (
                        expected.receipt_sha256
                        if case == "repeated"
                        else "sha256:" + "0" * 64
                    )
                    if case != "repeated":
                        with self.assertRaises(P7PrivateTraceReceiptError):
                            adapter.get_receipt(
                                run_id="adapter-run", receipt_sha256=digest
                            )
                        self.assertIsNone(recorder._trace_fd)
                        continue

                    self.assertEqual(
                        adapter.get_receipt(
                            run_id="adapter-run", receipt_sha256=digest
                        ),
                        expected,
                    )
                    with self.assertRaises(P7PrivateTraceReceiptError):
                        adapter.get_receipt(run_id="adapter-run", receipt_sha256=digest)

    @staticmethod
    def _launch(
        root: Path, broker: ArcBroker
    ) -> tuple[PrimeLaunch, P7PrivateTraceReceipt]:
        source = root / "prime_ipython.mjs"
        source.write_text("export default function extension() {}\n", encoding="utf-8")
        binding = PiExtensionBinding(
            extension_id="prime.ipython",
            path=source,
            capabilities=("prime.tool.ipython",),
            inherited_fds=(),
            environment={},
        )
        lease = binding.preflight()
        command = ("pi", "--mode", "rpc", *lease.command_args())
        trace_root = root / "trace"
        trace_root.mkdir()
        return (
            PrimeLaunch(
                approved_command=command,
                working_directory=root,
                extension_id=binding.extension_id,
                extension_path=source,
                extension_capabilities=binding.capabilities,
                binding_inherited_fds=binding.inherited_fds,
                binding_environment=dict(binding.environment),
                extension_lease=lease,
                deadline_seconds=ASTERION_PRIME_LIMITS.deadline_ms / 1000,
            ),
            P7PrivateTraceReceipt(broker, PrimeTraceRecorder(trace_root)),
        )

    def test_pyproject_registers_only_the_new_selected_p7_provider(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        entry_points = pyproject["project"]["entry-points"]

        self.assertEqual(
            entry_points["asterion.applications"]["prime-applications"],
            "asterion.applications.prime:create_provider",
        )
        for selector in (
            "prime.arc-agi-3-solving__1.0.0",
            "prime.ipython-coding__1.0.0",
        ):
            with self.subTest(selector=selector):
                self.assertEqual(
                    entry_points["asterion.application_index"][selector],
                    "asterion.applications.prime:create_provider",
                )


if __name__ == "__main__":
    unittest.main()
