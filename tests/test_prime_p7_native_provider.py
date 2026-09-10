"""Native P7 application/provider and Asterion-prime binding tests."""

from __future__ import annotations

import json
import subprocess
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
)
from asterion.applications.provider import compose_installed_provider
from asterion.applications.prime import create_provider
from asterion.applications.prime.p7.ipython_host import (
    IpythonWorkerResult,
    P7ClientFacade,
    PersistentIpythonHost,
    p7_client_facade,
)
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
from asterion.capabilities.prime_ipython_coding_native.provider import (
    create_prime_ipython_coding_native_package,
)
from asterion.applications.prime.runtime_binding import (
    PreflightedPrimeLaunch,
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
from asterion.runtime.host import (
    CancellationSignal,
    RunEvent,
    RunRequest,
    RuntimeManifest,
)
from asterion.runtimes.asterion_prime import AsterionPrimeRuntimeClient
from asterion.runtimes.pi_extensions import PiExtensionBinding
from asterion.runtimes.pi_rpc import PiRpcConfig, PiRpcSession


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
        self.assertEqual(
            tuple(application.application_id for application in provider.applications),
            ("prime.arc-agi-3-solving", "prime.ipython-coding"),
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

    def test_p7_application_composes_package_over_runtime_tool_capability(self) -> None:
        composed = compose_installed_provider(
            create_provider(),
            runtime_factories=RuntimeFactoryRegistry(()),
            installed_packages=(
                create_prime_arc_agi_3_solver_package(),
                create_prime_ipython_coding_native_package(),
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
                "prime.pi-extension",
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
                    "prime.pi-extension",
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
            "deepseek",
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
            "short experiments",
            "before/after",
            "no-ops",
            "death paths",
            "one completed level",
            "action1 is up",
            "never use python or shell loops to submit actions",
            "[plan]",
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
        selection = resolve_p7_runtime({"DEEPSEEK_API_KEY": "private-token"})

        self.assertEqual(
            selection,
            P7RuntimeSelection(
                runtime_id="asterion.prime",
                provider="deepseek",
                model="deepseek-v4-flash",
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
                "model": "deepseek-v4-flash",
                "provider": "deepseek",
            },
        )
        self.assertNotIn("private-token", repr(selection))
        self.assertNotIn("private-token", repr(options))

    def test_missing_model_host_fails_with_public_safe_error(self) -> None:
        for environment in ({}, {"DEEPSEEK_API_KEY": "   "}):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(
                    P7OperatorError, "P7 model host is unavailable"
                ) as raised:
                    resolve_p7_runtime(environment)
                self.assertNotIn("DEEPSEEK_API_KEY", str(raised.exception))

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
                    resolve_p7_runtime({"DEEPSEEK_API_KEY": "private-token"})
                ),
                host_services={
                    "prime.arc-broker": broker,
                    "prime.ipython": ipython,
                    "prime.pi-extension": launch,
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
            process_starts: list[object] = []

            def forbidden_popen(
                *args: object, **kwargs: object
            ) -> subprocess.Popen[bytes]:
                process_starts.append((args, kwargs))
                raise AssertionError("Pi process must remain inert")

            resources = build_p7_operator_resources(
                environment={"DEEPSEEK_API_KEY": "private-token"},
                pi_base_command=("/usr/bin/pi", "--mode", "rpc"),
                extension_path=extension,
                working_directory=root,
                worker=worker,
                engine=_CompletingEngine(),
                private_trace_root=trace_root,
                popen=forbidden_popen,
            )
            composed = compose_installed_provider(
                create_provider(),
                runtime_factories=RuntimeFactoryRegistry(()),
                installed_packages=(
                    create_prime_arc_agi_3_solver_package(),
                    create_prime_ipython_coding_native_package(),
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
                PreflightedPrimeLaunch,
                resources.host_services["prime.pi-extension"],
            )
            self.assertIs(type(runtime), AsterionPrimeRuntimeClient)
            self.assertEqual(
                launch.approved_command,
                (
                    "/usr/bin/pi",
                    "--mode",
                    "rpc",
                    "--provider",
                    "deepseek",
                    "--model",
                    "deepseek-v4-flash",
                    *launch.extension_lease.command_args(),
                ),
            )
            self.assertEqual(
                launch.rpc_session.config.environment["DEEPSEEK_API_KEY"],
                "private-token",
            )
            self.assertEqual(worker.starts, 0)
            self.assertEqual(process_starts, [])
            self.assertNotIn("private-token", repr(resources))
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
                    "prime.pi-extension": launch,
                    "prime.private-trace": trace,
                },
            )

            with self.assertRaisesRegex(
                RuntimeFactoryError, "Asterion-prime runtime configuration is invalid"
            ):
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
    ) -> tuple[PreflightedPrimeLaunch, P7PrivateTraceReceipt]:
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
        rpc = PiRpcSession(
            PiRpcConfig(
                command=command,
                cwd=root,
                environment=dict(lease.environment),
                deadline_seconds=ASTERION_PRIME_LIMITS.deadline_ms / 1000,
                inherited_fds=lease.inherited_fds,
            )
        )
        trace_root = root / "trace"
        trace_root.mkdir()
        return (
            PreflightedPrimeLaunch(
                rpc_session=rpc,
                extension_binding=binding,
                extension_lease=lease,
                approved_command=command,
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
        self.assertEqual(
            entry_points["asterion.application_index"][
                "prime.arc-agi-3-solving__1.0.0"
            ],
            "asterion.applications.prime:create_provider",
        )


if __name__ == "__main__":
    unittest.main()
