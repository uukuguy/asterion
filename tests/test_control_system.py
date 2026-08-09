from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from asterion.applications.provider import (
    APPLICATION_PROVIDER_PROTOCOL,
    InstalledApplication,
    InstalledApplicationProvider,
    InstalledAssembly,
)
from asterion.assembly.protocol import AssemblyPlan
from asterion.capabilities.composition import CapabilityComposition
from asterion.control.factory import (
    ControlPlaneFactoryBinding,
    ControlPlaneFactoryRegistry,
)
from asterion.control.system import AgentSystemError, resolve_agent_system


ROOT = Path(__file__).resolve().parents[1]
SYSTEM_FIXTURE = (
    ROOT / "tests" / "fixtures" / "agent_system" / "v1" / "valid-system.json"
)


def _manifest() -> dict[str, object]:
    value = json.loads(SYSTEM_FIXTURE.read_text())
    assert isinstance(value, dict)
    return value


def _plan(application_id: str, version: str, runtime_id: str) -> AssemblyPlan:
    return AssemblyPlan(
        application_id=application_id,
        version=version,
        runtime_id=runtime_id,
        capability_package_refs=(),
        capability_refs=(),
        capability_manifests=(),
        composition=CapabilityComposition(
            capability_ids=(),
            provided_capabilities=(),
            emitted_events=(),
            produced_artifacts=(),
        ),
        runtime_capabilities=(),
        host_capabilities=(),
        host_events=(),
        host_artifacts=(),
    )


def _application(root: Path, application_id: str, version: str) -> InstalledApplication:
    assembly_path = root / f"{application_id}.json"
    assembly_path.write_text("{}")
    plan = _plan(application_id, version, "fake.runtime")
    return InstalledApplication(
        application_id=application_id,
        version=version,
        assembly_paths=(assembly_path,),
        capability_packages=(),
        runtime_ids=("fake.runtime",),
        assemblies=(
            InstalledAssembly(
                runtime_id="fake.runtime",
                path=assembly_path,
                plan=plan,
            ),
        ),
    )


def _provider(root: Path) -> InstalledApplicationProvider:
    return InstalledApplicationProvider(
        protocol=APPLICATION_PROVIDER_PROTOCOL,
        provider_id="example.provider",
        resource_root=root,
        applications=(
            _application(root, "alpha", "1.0.0"),
            _application(root, "zeta", "2.0.0"),
        ),
    )


def _control_factories(calls: list[str], *, capabilities: tuple[str, ...] | None = None) -> ControlPlaneFactoryRegistry:
    def factory(context: object) -> object:
        del context
        calls.append("factory")
        return object()

    return ControlPlaneFactoryRegistry(
        (
            ControlPlaneFactoryBinding(
                control_plane_id="fake.control",
                version="1.0.0",
                commands=(
                    "action.resolve",
                    "checkpoint.request",
                    "input.submit",
                    "session.attach",
                    "session.cancel",
                    "session.create",
                    "session.pause",
                    "session.resume",
                ),
                events=(
                    "action.proposed",
                    "budget.reported",
                    "checkpoint.created",
                    "fault.raised",
                    "goal.updated",
                    "session.budget-limited",
                    "session.cancelled",
                    "session.completed",
                    "session.created",
                    "session.failed",
                    "session.paused",
                    "session.recovery-required",
                    "session.running",
                ),
                capabilities=capabilities
                if capabilities is not None
                else (
                    "action-proposals",
                    "checkpointing",
                    "event-replay",
                    "session-lifecycle",
                ),
                continuation_media_type="application/vnd.asterion.control-capsule",
                checkpoint_version="1.0.0",
                compatibility_ids=(
                    "asterion.agent-control/v1",
                    "fake-control/v1",
                ),
                factory=factory,
            ),
        )
    )


class TestControlSystem(unittest.TestCase):
    def test_resolves_exact_immutable_portfolio_without_factory_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            provider = _provider(root)
            calls: list[str] = []
            source = _manifest()
            original = json.loads(json.dumps(source))

            plan = resolve_agent_system(
                source,
                application_providers=(provider,),
                control_factories=_control_factories(calls),
                host_capabilities=("clock.monotonic", "storage.private"),
            )

            self.assertEqual(plan.system_id, "research.system")
            self.assertEqual(
                tuple(entry.application.application_id for entry in plan.portfolio),
                ("alpha", "zeta"),
            )
            self.assertEqual(plan.portfolio[0].assembly.runtime_id, "fake.runtime")
            self.assertEqual(plan.control_binding.version, "1.0.0")
            self.assertEqual(calls, [])
            self.assertEqual(source, original)
            with self.assertRaises(AttributeError):
                plan.system_id = "changed"  # type: ignore[misc]
            rendered = repr(plan)
            self.assertNotIn(str(root), rendered)

    def test_resolution_is_deterministic_under_provider_input_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = _provider(root)
            unused = replace(selected, provider_id="unused.provider", applications=())
            calls: list[str] = []
            factories = _control_factories(calls)

            first = resolve_agent_system(
                _manifest(),
                application_providers=(selected, unused),
                control_factories=factories,
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            second = resolve_agent_system(
                _manifest(),
                application_providers=(unused, selected),
                control_factories=factories,
                host_capabilities=("clock.monotonic", "storage.private"),
            )

            self.assertEqual(first, second)
            self.assertEqual(calls, [])

    def test_rejects_missing_exact_application_runtime_and_provider_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _provider(Path(directory))
            calls: list[str] = []
            factories = _control_factories(calls)
            manifest = _manifest()
            applications = manifest["applications"]
            assert isinstance(applications, list)
            first_ref = applications[0]
            assert isinstance(first_ref, dict)
            invalid_inputs = (
                (
                    {**manifest, "applications": [{**first_ref, "version": "9.0.0"}]},
                    (provider,),
                ),
                (
                    {
                        **manifest,
                        "applications": [
                            {**first_ref, "runtime_id": "missing.runtime"}
                        ],
                    },
                    (provider,),
                ),
                (manifest, (provider, provider)),
                (manifest, ()),
            )
            for value, providers in invalid_inputs:
                with self.subTest(value=value, providers=len(providers)), self.assertRaises(
                    AgentSystemError
                ):
                    resolve_agent_system(
                        value,
                        application_providers=providers,
                        control_factories=factories,
                        host_capabilities=("clock.monotonic", "storage.private"),
                    )
            self.assertEqual(calls, [])

    def test_rejects_missing_host_or_control_capability_before_factory_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            provider = _provider(Path(directory))
            calls: list[str] = []
            cases = (
                (
                    _control_factories(calls),
                    ("clock.monotonic",),
                ),
                (
                    _control_factories(calls, capabilities=("session-lifecycle",)),
                    ("clock.monotonic", "storage.private"),
                ),
            )
            for factories, host_capabilities in cases:
                with self.subTest(host_capabilities=host_capabilities), self.assertRaises(
                    AgentSystemError
                ):
                    resolve_agent_system(
                        _manifest(),
                        application_providers=(provider,),
                        control_factories=factories,
                        host_capabilities=host_capabilities,
                    )
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
