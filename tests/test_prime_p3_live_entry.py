"""Installed-wheel P3 preset entry wiring, without a provider call."""

from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from asterion.applications.prime.p3 import live_entry
from asterion.agents.prime.application import PrimeOperatorContext
from asterion.agents.prime.deadline import TaskDeadline


class TestP3LiveEntry(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_launch_and_fresh_private_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = PrimeOperatorContext(
                executable=Path("/node"), entry=Path("/pi"), cwd=root,
                provider="deepseek", model="deepseek-flash", effort="off",
                environment={"DEEPSEEK_API_KEY": "SECRET"},
                task_deadline=TaskDeadline(deadline_monotonic=time.monotonic() + 120,
                                           deadline_epoch=time.time() + 120),
            )
            result = SimpleNamespace(status="completed", model_call_count=2)
            environment = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(root),
                "ASTERION_PRIME_P3_PRIVATE_ROOT": str(root / "evidence"),
            }
            with (
                patch.object(
                    live_entry, "resolve_live_model_context", return_value=context
                ),
                patch.object(
                    live_entry,
                    "run_live_verification",
                    new_callable=AsyncMock,
                    return_value=result,
                ) as run,
            ):
                received = await live_entry.run_live_preset(environment)
            self.assertIs(received, result)
            kwargs = run.await_args.kwargs
            self.assertEqual(
                kwargs["private_root"].parent, (root / "evidence").resolve()
            )
            prime = kwargs["prime"]
            identity = prime._text_identity_summary()
            self.assertEqual(len(identity.command_sha256), 64)
            self.assertEqual(len(identity.binding_sha256), 64)
            self.assertNotIn("session_factory", kwargs)
            view = prime.text_model(key="child", limits=kwargs["limits"])
            for forbidden in ("process", "open", "close"):
                self.assertFalse(hasattr(view, forbidden))
            self.assertEqual(prime.state, "prepared")
            cleanup = await prime.close()
            self.assertTrue(cleanup.complete)
            self.assertNotIn("SECRET", str(result))

    async def test_missing_operator_inputs_fail_closed(self):
        with self.assertRaises(live_entry.P3LiveEntryError):
            await live_entry.run_live_preset({})
