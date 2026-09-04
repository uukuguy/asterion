"""Provider-free tests for Prime's private bounded-model host factory."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
import unittest

from asterion.applications.prime_agent.operator.model_session_host import (
    PrimeModelSessionHostError,
    create_bounded_model_session_factory,
)
from asterion.services.bounded_model_session import (
    BoundedModelSessionLease,
    BoundedModelSessionRequest,
    BoundedModelSessionService,
)
from asterion.services.registry import HostServiceFactoryContext


def _context() -> HostServiceFactoryContext:
    return HostServiceFactoryContext(
        provider_id="prime-agent",
        application_id="prime.ipython-coding",
        application_version="1.0.0",
        capability_id="model.bounded-session",
        options={},
    )


def _request(**changes: int | str) -> BoundedModelSessionRequest:
    request = BoundedModelSessionRequest(
        run_id="run-1", max_requests=1, max_input_tokens=1024,
        max_output_tokens=1024, max_input_bytes=4096, max_output_bytes=4096,
        max_cost_microunits=10_000, deadline_seconds=60,
    )
    return replace(request, **changes)


class TestPrimeModelSessionHost(unittest.IsolatedAsyncioTestCase):
    async def test_factory_reads_private_dotenv_only_and_returns_revocable_service(self) -> None:
        sentinel = "SENTINEL-PRIME-PRIVATE-KEY"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "PRIME_MODEL_API_KEY=" + sentinel + "\nPRIME_MODEL_ID=operator-model\n",
                encoding="utf-8",
            )
            binding = create_bounded_model_session_factory(repo_root=root)
            self.assertEqual(binding.capability_id, "model.bounded-session")
            self.assertEqual(binding.option_names, ())
            async with AsyncExitStack() as stack:
                service = cast(
                    BoundedModelSessionService,
                    await stack.enter_async_context(binding.factory(_context())),
                )
                lease = service.open(_request())
                self.assertEqual(lease.run_id, "run-1")
                receipt = service.revoke(lease)
                self.assertEqual(
                    (receipt.terminal, receipt.request_count, receipt.cost_microunits),
                    ("revoked", 0, 0),
                )
                with self.assertRaises(PrimeModelSessionHostError):
                    service.revoke(lease)
            self.assertNotIn(sentinel, repr(service))
            self.assertNotIn(sentinel, repr(binding))

    async def test_service_rejects_every_request_limit_that_differs_from_p1_preset(self) -> None:
        mismatches = {
            "max_requests": 2,
            "max_input_tokens": 1023,
            "max_output_tokens": 1025,
            "max_input_bytes": 4095,
            "max_output_bytes": 4097,
            "max_cost_microunits": 9_999,
            "deadline_seconds": 61,
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "PRIME_MODEL_API_KEY=key\nPRIME_MODEL_ID=operator-model\n",
                encoding="utf-8",
            )
            binding = create_bounded_model_session_factory(repo_root=root)
            async with AsyncExitStack() as stack:
                service = cast(
                    BoundedModelSessionService,
                    await stack.enter_async_context(binding.factory(_context())),
                )
                for field, value in mismatches.items():
                    with self.subTest(field=field, value=value):
                        with self.assertRaises(PrimeModelSessionHostError):
                            service.open(_request(**{field: value}))
                self.assertEqual(service.open(_request()).session_id, "prime-session-1")

    async def test_revoke_rejects_forged_run_identity_and_receipts_original_lease(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "PRIME_MODEL_API_KEY=key\nPRIME_MODEL_ID=operator-model\n",
                encoding="utf-8",
            )
            binding = create_bounded_model_session_factory(repo_root=root)
            async with AsyncExitStack() as stack:
                service = cast(
                    BoundedModelSessionService,
                    await stack.enter_async_context(binding.factory(_context())),
                )
                lease = service.open(_request())
                forged = BoundedModelSessionLease(lease.session_id, "run-2")
                with self.assertRaises(PrimeModelSessionHostError):
                    service.revoke(forged)
                receipt = service.revoke(lease)
                self.assertEqual((receipt.session_id, receipt.run_id), (lease.session_id, "run-1"))

    async def test_factory_fails_closed_when_private_configuration_is_absent_or_invalid(self) -> None:
        for contents in (None, "PRIME_MODEL_API_KEY=\n", "PRIME_MODEL_API_KEY=key\nPRIME_MODEL_ID=\n"):
            with self.subTest(contents=contents), TemporaryDirectory() as directory:
                root = Path(directory)
                if contents is not None:
                    (root / ".env").write_text(contents, encoding="utf-8")
                binding = create_bounded_model_session_factory(repo_root=root)
                with self.assertRaises(PrimeModelSessionHostError) as raised:
                    async with binding.factory(_context()):
                        pass
                self.assertNotIn("key", str(raised.exception))

    async def test_factory_never_uses_process_environment_or_exposes_provider_configuration(self) -> None:
        sentinel = "SENTINEL-PROCESS-SECRET"
        with TemporaryDirectory() as directory:
            binding = create_bounded_model_session_factory(
                repo_root=Path(directory), environment={"PRIME_MODEL_API_KEY": sentinel},
            )
            with self.assertRaises(PrimeModelSessionHostError):
                async with binding.factory(_context()):
                    pass
            self.assertNotIn(sentinel, repr(binding))
