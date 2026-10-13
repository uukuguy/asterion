"""Native P7 application/provider and Asterion-prime binding tests."""

from __future__ import annotations

import json
import asyncio
import tempfile
import tomllib
import unittest
from unittest.mock import patch
from importlib import metadata
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import AsyncIterator, cast

from asterion.agents.prime.session import AsterionPrimeLimits
from asterion.agents.prime.trace import PrimeTraceRecorder
from asterion.agents.prime.tool_registry import PrimeApplicationToolRegistry
from asterion.services.diagnostics import FailureDiagnostic
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
from asterion.applications.prime.p7.tool_registry import P7_LEGACY_TOOL_REGISTRY
from asterion.capabilities.execution import CapabilityInvocation
from asterion.capabilities.prime_arc_agi_3_solver.host import (
    PrimeArcAgi3SolveReceipt,
)
from asterion.capabilities.prime_arc_agi_3_solver.provider import CAPABILITY_REF
from asterion.applications.prime.runtime_binding import (
    _P7SolveEventProjector,
    asterion_prime_runtime_binding,
)
from asterion.capability_packages import CapabilityPackageRef
from asterion.applications.prime.p7.broker import ArcBroker
from asterion.agents.prime.application import PrimeApplication
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


ROOT = Path(__file__).resolve().parents[1]
ASSEMBLY = (
    ROOT / "src/asterion/applications/prime/assemblies/prime-arc-agi-3-solving.json"
)


def _context(**kwargs):
    from asterion.applications.prime.p7.tool_dispatch import P7ToolDispatch
    services = kwargs.get('host_services', {})
    owner, host = services.get('prime.launch'), services.get('prime.ipython')
    if type(owner) is PrimeApplication and owner.services is None and host is not None:
        owner._services = P7ToolDispatch(host, getattr(host, '_p7_client', None), run_id='fixture')
    return RuntimeFactoryContext(**kwargs)


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

    async def restore(self, *args, **kwargs):
        raise AssertionError("worker must remain inert")


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
    def test_private_trace_retains_bounded_failure_diagnostic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker = ArcBroker(engine=_CompletingEngine())
            adapter = P7PrivateTraceReceipt(
                broker, PrimeTraceRecorder(Path(directory).resolve())
            )
            diagnostic = FailureDiagnostic(
                "diagnostic-id", "pi.prompt", "RuntimeError", "subject", None,
                "pi-provider-execution",
            )

            adapter.record_failure(diagnostic)

            self.assertIs(adapter.failure_diagnostic, diagnostic)

    def test_p7_continuation_prompt_carries_current_state(self) -> None:
        from asterion.applications.prime.runtime_binding import _p7_continuation_prompt
        from asterion.applications.prime.p7.broker import ArcObservation, ArcStatus

        class Broker:
            game = SimpleNamespace(target_level=3)

            def status(self):
                return ArcStatus(4, 2, 40, "active")

            def observe(self):
                return ArcObservation(("ACTION1",), (((0, 0),),), 2, "NOT_FINISHED", 3)

            def tried_actions(self, level):
                del level
                return [{"level": 2, "action": "ACTION1", "count": 10, "position": None}]

            def last_outcome_summary(self, level):
                return {"attempts": {"ACTION1": 10}, "no_effect": {"ACTION1": 3}}

        prompt = _p7_continuation_prompt(Broker(), 1)
        self.assertIn("Round 1", prompt)
        self.assertIn("actions_remaining", prompt)
        self.assertIn("frame_summary", prompt)
        self.assertIn("force-replan-after-repeated-action", prompt)
        self.assertIn("tried_summary", prompt)
        self.assertIn("one falsifiable gameplay action", prompt)

    def test_p7_runtime_terminal_predicate_keeps_reset_required_open(self) -> None:
        from asterion.applications.prime.runtime_binding import _p7_terminal
        from tests.test_prime_p7_native_broker import _Engine as TerminalEngine

        broker = ArcBroker(engine=TerminalEngine(game_over_after=1))
        self.assertFalse(_p7_terminal(broker))
        broker.act(("ACTION1",))
        self.assertFalse(_p7_terminal(broker))
        self.assertEqual(broker.status().terminal_reason, "reset-required")
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
        for required in (
            "ipython", "p7_workspace", "p7_execute_plan", "p7_research",
            "competing_hypotheses", "checkpoint", "source_export_ids",
        ):
            self.assertIn(required, P7_SOLVE_PROMPT)
        for forbidden in ("ls20", "9607627b", "golden trace", "p7_client."):
            self.assertNotIn(forbidden, P7_SOLVE_PROMPT)

    def test_operator_selection_is_fixed_and_runtime_options_are_immutable(
        self,
    ) -> None:
        selection = resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"), "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol"})

        self.assertEqual(
            selection,
            P7RuntimeSelection(
                runtime_id="asterion.prime",
                provider="openai-codex",
                model="gpt-6.1-sol",
                max_actions=500,
                max_callbacks=1024,
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
                "max_callbacks": "1024",
                "max_tool_callbacks": "4096",
                "model": "gpt-6.1-sol",
                "provider": "openai-codex",
            },
        )
        self.assertNotIn("private-token", repr(selection))
        self.assertNotIn("private-token", repr(options))

    def test_offline_first_round_removes_runtime_bounds_only_with_explicit_mode(self) -> None:
        from asterion.applications.prime.p7.operator import _sweep_game
        game = _sweep_game(P7GameSelection("ls20-9607627b", 0), None)
        environment = {
            "ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"), "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol",
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
        game = _sweep_game(P7GameSelection("ls20-9607627b", 0), None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            extension = root / "prime_ipython.mjs"
            extension.write_text("export default function extension() {}\n")
            trace_root = root / "trace"
            trace_root.mkdir()
            resources = build_p7_operator_resources(
                environment={
                    "ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"), "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol",
                    "ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND": "1",
                    "ASTERION_PRIME_P7_RUN_MODE": "sweep",
                    "OPERATION_MODE": "offline",
                    "ASTERION_PRIME_EFFORT": "high",
                },
                executable=Path("/usr/bin/pi"),
                extension_path=extension, working_directory=root,
                worker=_Worker(), engine=_CompletingEngine(), private_trace_root=trace_root,
                game=game,
            )
            try:
                owner = resources.application
                self.assertEqual(owner._operator.effort, 'high')
                self.assertIsNone(owner.authorized_limits.deadline_ms)
                self.assertIsNone(owner.authorized_limits.model_callbacks)
                self.assertIsNone(owner._persistent)
                self.assertNotIn('OPERATION_MODE', owner._operator.environment)
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
            context = _context(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-solving",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=ASSEMBLY.resolve(),
                options=p7_runtime_options(
                    resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"), "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol"})
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
            self.assertIsNone(launch._persistent)
            asyncio.run(launch.close())

    def test_runtime_binding_rejects_a_launch_without_a_declared_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            broker = ArcBroker(engine=_Engine())
            launch, trace = self._launch(root, broker, declare_model=False)
            ipython = PersistentIpythonHost(
                worker=_Worker(), p7_client=p7_client_facade(broker)
            )
            context = _context(
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

            with self.assertRaises(RuntimeFactoryError):
                asterion_prime_runtime_binding().factory(context)
            self.assertIsNone(launch._persistent)

    def test_runtime_binding_rejects_same_identity_with_incomplete_tool_registry(self) -> None:
        from dataclasses import replace
        from asterion.applications.prime.p7.runtime_binding import build_p7_runtime

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            broker = ArcBroker(engine=_Engine())
            launch, trace = self._launch(root, broker)
            bad_launch = PrimeApplication(
                replace(launch._spec, tools=replace(launch._spec.tools,
                    registry=PrimeApplicationToolRegistry(launch.tool_registry.module_id,
                        launch.tool_registry.capability_id, ('ipython',)))),
                launch._operator, authorization=launch.authorized_limits)
            ipython = PersistentIpythonHost(
                worker=_Worker(), p7_client=p7_client_facade(broker)
            )
            context = _context(
                provider_id="prime-applications",
                application_id="prime.arc-agi-3-solving",
                application_version="1.0.0",
                runtime_id="asterion.prime",
                assembly_path=ASSEMBLY.resolve(),
                options=p7_runtime_options(
                    resolve_p7_runtime({
                        "ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"),
                        "ASTERION_PRIME_PROVIDER": "openai-codex",
                        "ASTERION_PRIME_MODEL": "gpt-6.1-sol",
                    })
                ),
                host_services={
                    "prime.arc-broker": broker,
                    "prime.ipython": ipython,
                    "prime.launch": bad_launch,
                    "prime.private-trace": trace,
                },
            )
            with self.assertRaises(RuntimeFactoryError):
                build_p7_runtime(context)
            self.assertIsNone(launch._persistent)

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
                context = _context(
                    provider_id="prime-applications",
                    application_id="prime.arc-agi-3-solving",
                    application_version="1.0.0",
                    runtime_id="asterion.prime",
                    assembly_path=ASSEMBLY.resolve(),
                    options=p7_runtime_options(resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"), "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol"}, game), game),
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
                        asyncio.run(launch.close())
                        self.assertEqual(broker.status().primitive_actions, 1)
                        self.assertEqual(broker.status().levels_completed, 1)
                    else:
                        with self.assertRaisesRegex(RuntimeFactoryError, "configuration is invalid"):
                            asterion_prime_runtime_binding().factory(context)
                        self.assertIsNone(launch._persistent)
                    self.assertEqual(worker.starts, 0)
                finally:
                    asyncio.run(launch.close())
                    trace.close()

    def test_operator_selects_explicit_artifact_and_injects_exact_registry(self) -> None:
        from asterion.applications.prime.p7 import live
        from asterion.applications.prime.p7.tool_registry import P7_TOOL_REGISTRY

        for variant, cognition, expected_name, registry in (
            ("verified", False, "p7-research-extension.mjs", P7_TOOL_REGISTRY),
            ("legacy", False, "p7-legacy-extension.mjs", P7_LEGACY_TOOL_REGISTRY),
            ("verified", True, "p7-legacy-extension.mjs", P7_LEGACY_TOOL_REGISTRY),
        ):
            with self.subTest(variant=variant, cognition=cognition), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                resource_root = root / "resources"
                resource_root.mkdir()
                for name in ("p7-research-extension.mjs", "p7-legacy-extension.mjs"):
                    (resource_root / name).write_text("export default function register() {}")
                trace_root = root / "trace"
                trace_root.mkdir()
                worker = _Worker()
                with patch.object(live.importlib_resources, "files", return_value=root):
                    resources = build_p7_operator_resources(
                        environment={
                            "ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"),
                            "ASTERION_PRIME_PROVIDER": "openai-codex",
                            "ASTERION_PRIME_MODEL": "gpt-6.1-sol",
                            "ASTERION_PRIME_P7_HISTORY_VARIANT": variant,
                            "ASTERION_PRIME_P7_TOOL_MODE": "injected-stale-selector",
                            "ASTERION_PRIME_IPYTHON_TOOL_REGISTRY": "injected-stale-registry",
                        },
                        executable=Path("/usr/bin/pi"),
                        extension_path=resource_root / "p7-research-extension.mjs",
                        working_directory=root,
                        worker=worker,
                        engine=_Engine(),
                        private_trace_root=trace_root,
                        cognition_mode=cognition,
                    )
                try:
                    launch = resources.host_services["prime.launch"]
                    self.assertEqual(launch._spec.tools.path.name, expected_name)
                    self.assertEqual(launch.tool_registry, registry)
                    self.assertIsNone(launch._persistent)
                    self.assertNotIn('ASTERION_PRIME_P7_TOOL_MODE', launch._operator.environment)
                    self.assertNotIn('ASTERION_PRIME_IPYTHON_TOOL_REGISTRY', launch._operator.environment)
                    self.assertEqual(worker.starts, 0)
                    from asterion.agents.prime import _launch
                    owned = _launch.persistent_launch(launch._operator, launch._spec,
                        launch.services, *launch._runtime_material, metrics_root=launch._metrics_root)
                    launch._persistent = owned
                    self.assertEqual(resources.context_view_metrics()['status'], 'not-recorded')
                    self.assertEqual(resources.provider_prefix_metrics()['status'], 'not-recorded')
                    self.assertIsNone(owned.rpc.process)
                finally:
                    asyncio.run(resources.close())
                self.assertEqual(owned.metrics.read()['status'], 'unavailable')
                self.assertEqual(owned.prefix_metrics.read()['status'], 'unavailable')

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
                environment={"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"), "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol"},
                executable=Path("/usr/bin/pi"),
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
                _context(
                    provider_id=composed.provider_id,
                    application_id="prime.arc-agi-3-solving",
                    application_version="1.0.0",
                    runtime_id=assembly.runtime_id,
                    assembly_path=assembly.path,
                    options=resources.runtime_options,
                    host_services=resources.host_services,
                )
            )

            launch = resources.application
            self.assertIs(type(runtime), AsterionPrimeRuntimeClient)
            self.assertIs(type(launch), PrimeApplication)
            self.assertEqual(launch.identity, ('prime.arc-agi-3-solving', '1.0.0', 'openai-codex', 'gpt-6.1-sol'))
            self.assertIsNone(launch._persistent)
            self.assertFalse(hasattr(launch, 'approved_command'))
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
            asyncio.run(launch.close())
            asyncio.run(resources.close())

    def test_runtime_factory_failure_closes_unhanded_lease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            broker = ArcBroker(engine=_Engine())
            launch, trace = self._launch(root, broker)
            context = _context(
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
            self.assertIsNone(launch._persistent)

    def test_runtime_factory_rejects_cap_different_from_selected_full_game(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            game = P7GameSelection("ls20-9607627b", 0, 7)
            broker = ArcBroker(engine=_Engine(), game=game)
            launch, trace = self._launch(root, broker)
            ipython = PersistentIpythonHost(worker=_Worker(), p7_client=p7_client_facade(broker))
            options = dict(p7_runtime_options(resolve_p7_runtime({"ASTERION_PRIME_PI_AGENT_DIR": str(Path.home() / ".pi/agent"), "ASTERION_PRIME_PROVIDER": "openai-codex", "ASTERION_PRIME_MODEL": "gpt-6.1-sol"}, game), game))
            options["max_actions"] = "500"
            context = _context(
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
            self.assertIsNone(launch._persistent)

    def test_unknown_action_blocks_prompt_recovery(self):
        from asterion.applications.prime.p7.action_journal import ActionJournal
        from asterion.applications.prime.p7.runtime_binding import _p7_recovery_effects_settled
        from tests.test_prime_p7_action_journal import SCOPE, ACTION, BEFORE
        with tempfile.TemporaryDirectory() as directory:
            journal = ActionJournal(Path(directory).resolve(), SCOPE)
            engine = _Engine()
            engine.action_journal = journal
            broker = ArcBroker(engine=engine)
            ipython = PersistentIpythonHost(worker=_Worker(), p7_client=p7_client_facade(broker))
            self.assertTrue(_p7_recovery_effects_settled(ipython, broker))
            journal.prepare(sequence=1, action=ACTION, before=BEFORE)
            journal.dispatch_entered(ACTION)
            journal.unresolved('dispatched-no-reply')
            self.assertFalse(_p7_recovery_effects_settled(ipython, broker))
            asyncio.run(ipython.close())

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
    def _launch(root, broker, *, declare_model=True):
        import time
        from asterion.agents.prime.application import (PrimeApplicationSpec, PrimeOperatorContext,
            PrimeToolModuleArtifact, prepare_prime_application)
        from asterion.agents.prime.deadline import TaskDeadline
        source = root / 'prime_ipython.mjs'
        source.write_text('export default function extension() {}\n')
        owner = prepare_prime_application(
            PrimeApplicationSpec('prime.arc-agi-3-solving', '1.0.0', 'persistent-code-tools',
                                 tools=PrimeToolModuleArtifact(source, P7_LEGACY_TOOL_REGISTRY)),
            PrimeOperatorContext(Path('/usr/bin/pi'), None, root, 'openai-codex',
                'gpt-6.1-sol' if declare_model else 'invalid-model', 'medium', {},
                TaskDeadline(deadline_monotonic=time.monotonic()+3600, deadline_epoch=time.time()+3600)),
            authorization=AsterionPrimeLimits(1024, 4096, 3600000))
        trace_root = root / 'trace'
        trace_root.mkdir()
        return owner, P7PrivateTraceReceipt(broker, PrimeTraceRecorder(trace_root))

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
