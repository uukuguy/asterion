"""Focused installed-host contract for the P2 development verification."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest
from asterion.services.registry import HostServiceFactoryContext


def _context(**changes: object) -> HostServiceFactoryContext:
    values: dict[str, object] = {
        "provider_id": "prime-agent",
        "application_id": "prime.programmatic-long-context",
        "application_version": "1.0.0",
        "capability_id": "prime.programmatic-long-context-development",
        "options": {},
    }
    values.update(changes)
    return HostServiceFactoryContext(**values)  # type: ignore[arg-type]


class TestPrimeP2CliHost(unittest.IsolatedAsyncioTestCase):
    async def test_exact_context_runs_p2_once_and_projects_p2_scope(self) -> None:
        from asterion.applications.prime_agent.operator import p2_cli_host as subject

        resources = subject._P2CliResources(  # noqa: SLF001
            image_digest="sha256:" + "a" * 64,
            transport=SimpleNamespace(close=lambda: None),
            operator_config={},
            node_bin="/operator/node",
            entrypoint="/operator/p2-development-main.js",
            prime_source_root="/operator/prime",
        )
        trace = SimpleNamespace(trace_sha256="sha256:" + "b" * 64)
        binding = subject.create_prime_p2_cli_factory(repo_root=Path("/repo"))
        with (
            patch.object(subject, "_preflight", return_value=resources),
            patch.object(
                subject,
                "run_prime_p2_development",
                new=AsyncMock(return_value=trace),
            ) as run,
        ):
            async with binding.factory(_context()) as service:
                result = await service.verify(
                    PrimeSmallVerificationRequest("prime-p2-cli-run")
                )

        self.assertEqual(
            (result.run_id, result.scope, result.promotion, result.trace_sha256),
            (
                "prime-p2-cli-run",
                "p2-development",
                "unpromoted",
                "sha256:" + "b" * 64,
            ),
        )
        run.assert_awaited_once_with(
            image_digest=resources.image_digest,
            transport=resources.transport,
            operator_config=resources.operator_config,
            node_bin=resources.node_bin,
            entrypoint=resources.entrypoint,
            prime_source_root=resources.prime_source_root,
            run_id="prime-p2-cli-run",
            signal=None,
        )

    async def test_wrong_application_is_rejected_before_preflight(self) -> None:
        from asterion.applications.prime_agent.operator import p2_cli_host as subject

        binding = subject.create_prime_p2_cli_factory(repo_root=Path("/repo"))
        with patch.object(subject, "_preflight") as preflight:
            with self.assertRaises(subject.PrimeP2CliHostError):
                async with binding.factory(_context(application_id="prime.ipython-coding")):
                    pass
        preflight.assert_not_called()

    async def test_public_failure_has_no_private_exception_chain(self) -> None:
        from asterion.applications.prime_agent.operator import p2_cli_host as subject

        resources = subject._P2CliResources(  # noqa: SLF001
            image_digest="sha256:" + "a" * 64,
            transport=SimpleNamespace(close=lambda: None),
            operator_config={"secret": "P2_PRIVATE_SENTINEL"},
            node_bin="/operator/node",
            entrypoint="/operator/p2-development-main.js",
            prime_source_root="/operator/prime",
        )
        service = subject.PrimeP2SmallVerificationService(resources)
        with patch.object(
            subject,
            "run_prime_p2_development",
            new=AsyncMock(side_effect=ValueError("P2_PRIVATE_SENTINEL")),
        ):
            with self.assertRaises(subject.PrimeP2CliHostError) as raised:
                await service.verify(PrimeSmallVerificationRequest("prime-p2-failure"))
        self.assertIsNone(raised.exception.__context__)
        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn("P2_PRIVATE_SENTINEL", repr(raised.exception))


if __name__ == "__main__":
    unittest.main()
