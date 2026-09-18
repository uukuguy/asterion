"""Tests for prime.continuity-store host service (Phase 6, Task 4)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime.services import (
    ContinuityStoreHostService,
    ContinuityStoreServiceError,
    create_continuity_store_host_service,
)
from asterion.services.progress import NOOP_HOST_PROGRESS_REPORTER
from asterion.services.presentation import NOOP_HOST_PRESENTATION_SINK
from asterion.services.registry import HostServiceFactoryContext


def _context(root: Path) -> HostServiceFactoryContext:
    return HostServiceFactoryContext(
        provider_id="prime-applications",
        application_id="prime.long-session-continuity",
        application_version="1.0.0",
        capability_id="prime.continuity-store",
        options={"root": str(root)},
        progress=NOOP_HOST_PROGRESS_REPORTER,
        presentation=NOOP_HOST_PRESENTATION_SINK,
    )


class TestContinuityStoreHostService(unittest.TestCase):
    def test_factory_binding_metadata(self) -> None:
        binding = create_continuity_store_host_service()
        self.assertEqual(binding.capability_id, "prime.continuity-store")
        self.assertEqual(binding.option_names, ("root",))

    def test_rejects_wrong_provider(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            ctx = HostServiceFactoryContext(
                provider_id="other-provider",
                application_id="prime.long-session-continuity",
                application_version="1.0.0",
                capability_id="prime.continuity-store",
                options={"root": str(root)},
                progress=NOOP_HOST_PROGRESS_REPORTER,
                presentation=NOOP_HOST_PRESENTATION_SINK,
            )
            with self.assertRaises(ContinuityStoreServiceError):
                asyncio.run(_drain_factory(ctx))

    def test_rejects_wrong_application(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            ctx = HostServiceFactoryContext(
                provider_id="prime-applications",
                application_id="prime.programmatic-long-context",
                application_version="1.0.0",
                capability_id="prime.continuity-store",
                options={"root": str(root)},
                progress=NOOP_HOST_PROGRESS_REPORTER,
                presentation=NOOP_HOST_PRESENTATION_SINK,
            )
            with self.assertRaises(ContinuityStoreServiceError):
                asyncio.run(_drain_factory(ctx))

    def test_rejects_unexpected_options(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            ctx = HostServiceFactoryContext(
                provider_id="prime-applications",
                application_id="prime.long-session-continuity",
                application_version="1.0.0",
                capability_id="prime.continuity-store",
                options={"root": str(root), "extra": "no"},
                progress=NOOP_HOST_PROGRESS_REPORTER,
                presentation=NOOP_HOST_PRESENTATION_SINK,
            )
            with self.assertRaises(ContinuityStoreServiceError):
                asyncio.run(_drain_factory(ctx))

    def test_rejects_relative_root(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            ctx = HostServiceFactoryContext(
                provider_id="prime-applications",
                application_id="prime.long-session-continuity",
                application_version="1.0.0",
                capability_id="prime.continuity-store",
                options={"root": "relative/private"},
                progress=NOOP_HOST_PROGRESS_REPORTER,
                presentation=NOOP_HOST_PRESENTATION_SINK,
            )
            with self.assertRaises(ContinuityStoreServiceError):
                asyncio.run(_drain_factory(ctx))

    def test_service_exposes_public_identity_without_leaking_path(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            ctx = _context(root)

            async def driver():
                factory = create_continuity_store_host_service().factory
                async with factory(ctx) as service:
                    self.assertIsInstance(service, ContinuityStoreHostService)
                    public = service.public_identity
                    self.assertEqual(public.provider_id, "prime-applications")
                    self.assertEqual(
                        public.application_id, "prime.long-session-continuity"
                    )
                    self.assertEqual(public.runtime_id, "asterion.prime")
                    self.assertEqual(public.generation, 1)
                    self.assertIsNone(public.prior_generation)
                    self.assertFalse(public.is_continued)
                    self.assertEqual(public.continuation_root_sha256, public.continuation_root_sha256)
                    # No private path field is exposed.
                    self.assertNotIn("private_root", vars(public))
                    self.assertNotIn("path", vars(public))
                    self.assertEqual(service.current_generation, 1)
                    self.assertEqual(service.highest_sealed_generation, 0)
                    self.assertIsNone(service.recover_checkpoint())

            asyncio.run(driver())

    def test_service_recovers_checkpoint_after_store_rebind(self) -> None:
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "private"
            root.mkdir(mode=0o700)
            ctx = _context(root)

            async def driver():
                factory = create_continuity_store_host_service().factory
                # Open twice — the second open must NOT fail on the same root.
                async with factory(ctx) as first:
                    self.assertEqual(first.current_generation, 1)
                async with factory(ctx) as second:
                    public = second.public_identity
                    self.assertEqual(public.generation, 1)
                    self.assertIsNone(public.prior_generation)
                    # No checkpoint sealed in this test, so recovery is empty.
                    self.assertIsNone(second.recover_checkpoint())

            asyncio.run(driver())


async def _drain_factory(context: HostServiceFactoryContext) -> None:
    factory = create_continuity_store_host_service().factory
    async with factory(context):
        pass


if __name__ == "__main__":
    unittest.main()