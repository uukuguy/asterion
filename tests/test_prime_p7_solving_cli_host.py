"""Operator-only integration checks for the installed P7 solving action."""

from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch

from asterion.capabilities.prime_arc_agi_3_solver.host import PrimeArcAgi3SolveReceipt
from asterion.runtimes.prime_agent_host import PrimePresetExecutionRequest
from asterion.services.presentation import TextHostPresentationSink
from asterion.services.registry import HostServiceFactoryContext


class _Progress:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


class TestPrimeP7SolvingCliHost(unittest.IsolatedAsyncioTestCase):
    async def test_exact_factory_locks_operator_model_and_injects_progress_presentation(self) -> None:
        from asterion.applications.prime_agent.operator import p7_solving_cli_host as subject

        progress, display = _Progress(), StringIO()
        context = HostServiceFactoryContext(
            provider_id="prime-agent", application_id="prime.arc-agi-3-solving",
            application_version="1.0.0", capability_id="prime.arc-agi-3-solving",
            options={}, progress=progress, presentation=TextHostPresentationSink(display),
        )
        receipt = PrimeArcAgi3SolveReceipt.create(
            run_id="p7-solve", completed_level_count=1,
            primitive_action_count=3, partial_game_score="1.000000",
        )
        captured: list[object] = []

        async def lifecycle(*args: object, **kwargs: object) -> object:
            captured.extend((args, kwargs))
            kwargs["receipt_store"].publish(receipt)
            return receipt

        with (
            patch.object(subject, "_preflight", return_value=object()),
            patch.object(subject, "_operator_config", return_value={"DEEPSEEK_API_KEY": "SENTINEL", "ASTERION_PRIME_EXPERIMENT_MODEL": "deepseek-v4-flash"}),
        ):
            binding = subject.create_prime_p7_solving_factory(repo_root=Path("/repo"), lifecycle_runner=lifecycle)
            self.assertEqual(binding.capability_id, "prime.arc-agi-3-solving")
            self.assertEqual(binding.option_names, ())
            async with binding.factory(context) as service:
                result = await service.execute(PrimePresetExecutionRequest("p7-solve", "solve-first-public-level"))
                self.assertEqual(result.receipt_sha256, receipt.receipt_sha256)
                self.assertEqual(service.get_receipt(run_id="p7-solve", receipt_sha256=receipt.receipt_sha256), receipt)
                with self.assertRaises(subject.PrimeP7SolvingCliHostError):
                    await service.execute(PrimePresetExecutionRequest("p7-next", "solve-first-public-level"))
        self.assertTrue(captured)
        self.assertIs(captured[1]["progress"], progress)
        self.assertIs(captured[1]["presentation"], context.presentation)

    async def test_single_use_rejects_concurrent_execution(self) -> None:
        from asterion.applications.prime_agent.operator import p7_solving_cli_host as subject

        started, release = asyncio.Event(), asyncio.Event()
        receipt = PrimeArcAgi3SolveReceipt.create(run_id="p7-once", completed_level_count=1, primitive_action_count=1, partial_game_score="1.000000")

        async def lifecycle(*_: object, **__: object) -> object:
            started.set()
            await release.wait()
            return receipt

        service = subject.PrimeP7SolvingService(object(), lifecycle_runner=lifecycle)
        active = asyncio.create_task(service.execute(PrimePresetExecutionRequest("p7-once", "solve-first-public-level")))
        await started.wait()
        with self.assertRaises(subject.PrimeP7SolvingCliHostError):
            await service.execute(PrimePresetExecutionRequest("p7-other", "solve-first-public-level"))
        release.set()
        await active


if __name__ == "__main__":
    unittest.main()
