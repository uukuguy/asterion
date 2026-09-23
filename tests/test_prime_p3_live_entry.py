"""Installed-wheel P3 preset entry wiring, without a provider call."""

from pathlib import Path
from types import MappingProxyType, SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from asterion.applications.prime.p3 import live_entry


class TestP3LiveEntry(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_launch_and_fresh_private_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launch = SimpleNamespace(
                command=("/node", "/pi", "--no-tools"),
                environment=MappingProxyType({"DEEPSEEK_API_KEY": "SECRET"}),
                cwd=root,
            )
            result = SimpleNamespace(status="completed", model_call_count=2)
            environment = {
                "ASTERION_PRIME_OPERATOR_ROOT": str(root),
                "ASTERION_PRIME_P3_PRIVATE_ROOT": str(root / "evidence"),
            }
            with (
                patch.object(
                    live_entry, "resolve_live_model_launch", return_value=launch
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
            self.assertEqual(len(kwargs["command_sha256"]), 64)
            self.assertEqual(len(kwargs["binding_sha256"]), 64)
            session = kwargs["session_factory"]("child", root / "child")
            self.assertEqual(session._rpc.config.cwd, root / "child")
            self.assertNotIn("SECRET", str(result))

    async def test_missing_operator_inputs_fail_closed(self):
        with self.assertRaises(live_entry.P3LiveEntryError):
            await live_entry.run_live_preset({})
