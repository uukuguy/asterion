"""Boundary checks for the aggregate Prime host preflight command."""

from __future__ import annotations

from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
import unittest

from asterion.applications.prime_agent.provider import create_provider
from asterion.services.registry import HostServiceFactoryBinding, HostServiceFactoryRegistry
from tools.preflight_prime_apps import _ROWS, preflight_prime_apps


class _Entry:
    group = "asterion.host_services"

    def __init__(self, name: str) -> None:
        self.name = name

    def load(self):
        capability_id = self.name

        def binding():
            @asynccontextmanager
            async def factory(context):
                yield object()

            return HostServiceFactoryBinding(capability_id, (), factory)

        return binding


class TestPrimeAppsPreflight(unittest.TestCase):
    def test_preflight_covers_only_the_seven_development_applications(self) -> None:
        prepared: list[tuple[str, ...]] = []

        def prepare(_: Path, scenarios: tuple[str, ...]):
            prepared.append(scenarios)
            return {scenario: object() for scenario in scenarios}

        stdout, stderr = StringIO(), StringIO()
        result = preflight_prime_apps(
            Path.cwd(), stdout=stdout, stderr=stderr, prepare=prepare,
            load_provider=lambda _: create_provider(),
            registry=HostServiceFactoryRegistry(tuple(_Entry(capability) for _, _, _, capability in _ROWS)),
        )

        self.assertEqual(result, 0)
        self.assertEqual(_ROWS[-1][:2], ("prime-p7", "p7"))
        self.assertNotIn(("p7-solving",), prepared)
        self.assertIn("prime-p7 PASS\n", stdout.getvalue())
        self.assertNotIn("prime-p7-solve", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
