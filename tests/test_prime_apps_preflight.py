"""Boundary tests for the aggregate Prime host preflight command."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from asterion.applications.prime_agent.provider import create_provider
from asterion.services.registry import HostServiceFactoryBinding, HostServiceFactoryRegistry
from tools.preflight_prime_apps import preflight_prime_apps


_SCENARIOS = (
    ("p1", "prime.ipython-production"),
    ("p2", "prime.programmatic-long-context-development"),
    ("p3", "prime.recursive-workflow-development"),
    ("p4", "prime.long-session-continuity-development"),
    ("p5", "prime.bounded-autonomy-development"),
    ("p6", "prime.continual-improvement-development"),
    ("p7", "prime.arc-agi-3-development"),
)


class _HostEntryPoint:
    group = "asterion.host_services"

    def __init__(self, name: str, factory) -> None:
        self.name = name
        self._factory = factory

    def load(self):
        return self._factory


class TestPrimeAppsPreflight(unittest.TestCase):
    def test_prepares_all_rows_then_opens_and_closes_exact_contexts(self) -> None:
        prepared: list[tuple[str, ...]] = []
        opened = []
        closed = []
        runtime_factory_calls = []

        def prepare(root: Path, scenarios: tuple[str, ...]):
            self.assertIsInstance(root, Path)
            prepared.append(scenarios)
            return {scenario: object() for scenario in scenarios}

        def binding_for(capability_id: str):
            def create_binding():
                @asynccontextmanager
                async def factory(context):
                    opened.append(context)
                    try:
                        yield object()
                    finally:
                        closed.append(context.capability_id)

                return HostServiceFactoryBinding(capability_id, (), factory)

            return _HostEntryPoint(capability_id, create_binding)

        provider = replace(
            create_provider(),
            runtime_factory_bindings=(lambda: runtime_factory_calls.append("called"),),
        )
        stdout, stderr = StringIO(), StringIO()
        result = preflight_prime_apps(
            Path.cwd(),
            stdout=stdout,
            stderr=stderr,
            prepare=prepare,
            load_provider=lambda _: provider,
            registry=HostServiceFactoryRegistry(
                tuple(binding_for(capability) for _, capability in _SCENARIOS)
            ),
        )

        self.assertEqual(result, 0)
        self.assertEqual(prepared, [(scenario,) for scenario, _ in _SCENARIOS])
        self.assertEqual([item.capability_id for item in opened], [item[1] for item in _SCENARIOS])
        self.assertEqual(closed, [item[1] for item in _SCENARIOS])
        self.assertTrue(all(dict(item.options) == {} for item in opened))
        self.assertEqual(runtime_factory_calls, [])
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            stdout.getvalue(),
            "".join(f"prime-{scenario} PASS\n" for scenario, _ in _SCENARIOS),
        )

    def test_prepare_failure_skips_its_context_and_later_rows_continue(self) -> None:
        opened: list[str] = []

        def prepare(_: Path, scenarios: tuple[str, ...]):
            if scenarios == ("p2",):
                raise ValueError("SENTINEL_SECRET /private/preparation")
            return {scenarios[0]: object()}

        def entry(capability_id: str):
            def create_binding():
                @asynccontextmanager
                async def factory(context):
                    opened.append(context.capability_id)
                    yield object()

                return HostServiceFactoryBinding(capability_id, (), factory)

            return _HostEntryPoint(capability_id, create_binding)

        stdout, stderr = StringIO(), StringIO()
        result = preflight_prime_apps(
            Path.cwd(),
            stdout=stdout,
            stderr=stderr,
            prepare=prepare,
            load_provider=lambda _: create_provider(),
            registry=HostServiceFactoryRegistry(tuple(entry(capability) for _, capability in _SCENARIOS)),
        )

        self.assertEqual(result, 1)
        self.assertNotIn("prime.programmatic-long-context-development", opened)
        self.assertIn("prime.arc-agi-3-development", opened)
        self.assertEqual(
            stdout.getvalue(),
            "".join(
                f"prime-{scenario} {'FAIL' if scenario == 'p2' else 'PASS'}\n"
                for scenario, _ in _SCENARIOS
            ),
        )
        self.assertNotIn("SENTINEL_SECRET", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("/private/preparation", stdout.getvalue() + stderr.getvalue())

    def test_invalid_assembly_fails_only_its_row_without_opening_it(self) -> None:
        provider = create_provider()
        p3 = next(item for item in provider.applications if item.application_id == "prime.recursive-workflow")
        with TemporaryDirectory() as directory:
            assembly = Path(directory) / "invalid.json"
            assembly.write_text("{}", encoding="utf-8")
            invalid = replace(p3, assembly_paths=(assembly,))
            provider = replace(
                provider,
                applications=tuple(
                    invalid if item.application_id == invalid.application_id else item
                    for item in provider.applications
                ),
            )
            opened: list[str] = []

            def entry(capability_id: str):
                def create_binding():
                    @asynccontextmanager
                    async def factory(context):
                        opened.append(context.capability_id)
                        yield object()

                    return HostServiceFactoryBinding(capability_id, (), factory)

                return _HostEntryPoint(capability_id, create_binding)

            stdout, stderr = StringIO(), StringIO()
            result = preflight_prime_apps(
                Path.cwd(),
                stdout=stdout,
                stderr=stderr,
                prepare=lambda _, scenarios: {scenarios[0]: object()},
                load_provider=lambda _: provider,
                registry=HostServiceFactoryRegistry(tuple(entry(capability) for _, capability in _SCENARIOS)),
            )

        self.assertEqual(result, 1)
        self.assertNotIn("prime.recursive-workflow-development", opened)
        self.assertIn("prime.arc-agi-3-development", opened)
        self.assertIn("prime-p3 FAIL\n", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
