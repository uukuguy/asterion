from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class TestPrimeP4CliHost(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_kills_and_reaps_the_node_process(self) -> None:
        from asterion.applications.prime_agent.operator import p4_cli_host as subject

        class Process:
            returncode: int | None = None

            def __init__(self) -> None:
                self.kills = 0
                self.waits = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                await asyncio.Future()

            def kill(self) -> None:
                self.kills += 1

            async def wait(self) -> int:
                self.waits += 1
                self.returncode = -9
                return self.returncode

        process = Process()
        with (
            patch.object(
                subject.asyncio,
                "create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            patch.object(subject, "_DEADLINE_SECONDS", 0.01),
            self.assertRaises(subject.PrimeP4CliHostError),
        ):
            await subject._run_p4_development(
                subject._P4CliResources("node", "entry", "/prime"), "p4-timeout"
            )
        self.assertEqual(process.kills, 1)
        self.assertEqual(process.waits, 1)

    async def test_service_projects_only_a_digest_from_the_private_session_result(self) -> None:
        from asterion.applications.prime_agent.operator import p4_cli_host as subject
        from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest

        observed = []

        async def runner(resources: object, run_id: str) -> object:
            observed.append((resources, run_id))
            return {
                "activeSessionId": "private-session-identity",
                "cursor": {"generation": "private-generation", "sequence": 7},
            }

        resources = subject._P4CliResources("node", "entry", "/prime")
        service = subject.PrimeP4SmallVerificationService(resources, runner=runner)
        result = await service.verify(PrimeSmallVerificationRequest("p4-projection"))

        self.assertEqual(observed, [(resources, "p4-projection")])
        self.assertEqual(result.run_id, "p4-projection")
        self.assertEqual(result.scope, "p4-development")
        self.assertEqual(result.promotion, "unpromoted")
        self.assertRegex(result.trace_sha256, r"\Asha256:[0-9a-f]{64}\Z")
        self.assertNotIn("private", repr(result))

    async def test_service_rejects_invalid_private_runner_result_without_exposing_it(self) -> None:
        from asterion.applications.prime_agent.operator import p4_cli_host as subject
        from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest

        async def runner(_: object, __: str) -> object:
            return {"activeSessionId": "secret", "cursor": {"sequence": 1}}

        service = subject.PrimeP4SmallVerificationService(
            subject._P4CliResources("node", "entry", "/prime"), runner=runner
        )
        with self.assertRaisesRegex(subject.PrimeP4CliHostError, "unavailable") as raised:
            await service.verify(PrimeSmallVerificationRequest("p4-invalid"))
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
