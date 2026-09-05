"""Focused contract checks for the local-root P1 CLI host."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from asterion.services.registry import HostServiceFactoryContext
from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest


def _context(**changes: object) -> HostServiceFactoryContext:
    values: dict[str, object] = {
        "provider_id": "prime-agent",
        "application_id": "prime.ipython-coding",
        "application_version": "1.0.0",
        "capability_id": "prime.ipython-production",
        "options": {},
    }
    values.update(changes)
    return HostServiceFactoryContext(**values)  # type: ignore[arg-type]


class _Signal:
    cancelled = False


class TestPrimeP1CliHost(unittest.IsolatedAsyncioTestCase):
    async def test_image_tag_must_resolve_to_the_confirmed_digest(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject

        result = SimpleNamespace(
            returncode=0,
            stdout=("sha256:" + "a" * 64 + "\n").encode(),
        )
        with patch.object(subject.subprocess, "run", return_value=result):
            with self.assertRaises(subject.PrimeP1CliHostError):
                subject._inspect_image(Path("/usr/bin/docker"), Path("/var/run/docker.sock"))

    async def test_preflight_failure_closes_created_transport(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject

        transport = SimpleNamespace(close=Mock())
        with (
            patch.object(subject.sys, "platform", "linux"),
            patch.object(subject.os, "geteuid", return_value=0),
            patch.object(subject, "_regular_executable", side_effect=(Path("/docker"), Path("/node"))),
            patch.object(subject.os, "lstat", return_value=SimpleNamespace(st_mode=0)),
            patch.object(subject.stat, "S_ISSOCK", return_value=True),
            patch.object(subject, "_regular_file", return_value=Path("/bridge.js")),
            patch.object(subject, "_regular_directory", return_value=Path("/prime")),
            patch.object(subject, "_sealed_seccomp", return_value=73),
            patch.object(subject, "_inspect_image", return_value="sha256:" + "a" * 64),
            patch.object(subject, "_host_platform", return_value=object()),
            patch.object(subject, "P1BDevelopmentSnapshotTransport", return_value=transport),
            patch.object(subject, "_operator_config", side_effect=RuntimeError("SENTINEL")),
            patch.object(subject.os, "close"),
        ):
            with self.assertRaises(subject.PrimeP1CliHostError):
                subject._preflight(Path("/repo"))
        transport.close.assert_called_once_with()

    async def test_seccomp_memfd_is_sealed_like_docker_admission(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject

        with TemporaryDirectory() as directory:
            profile = Path(directory) / "seccomp.json"
            profile.write_bytes(b"{}")
            seals = 1 | 2 | 4 | 8
            with (
                patch.object(subject.os, "memfd_create", return_value=73, create=True) as created,
                patch.object(subject.os, "MFD_CLOEXEC", 16, create=True),
                patch.object(subject.os, "MFD_ALLOW_SEALING", 32, create=True),
                patch.object(subject.fcntl, "F_ADD_SEALS", 64, create=True),
                patch.object(subject.fcntl, "F_GET_SEALS", 128, create=True),
                patch.object(subject.fcntl, "F_SEAL_WRITE", 1, create=True),
                patch.object(subject.fcntl, "F_SEAL_GROW", 2, create=True),
                patch.object(subject.fcntl, "F_SEAL_SHRINK", 4, create=True),
                patch.object(subject.fcntl, "F_SEAL_SEAL", 8, create=True),
                patch.object(subject.fcntl, "F_GETFD", 256, create=True),
                patch.object(subject.fcntl, "FD_CLOEXEC", 16, create=True),
                patch.object(subject.os, "write", return_value=2),
                patch.object(subject.os, "fstat", return_value=SimpleNamespace(st_size=2)),
                patch.object(subject.os, "lseek", return_value=0),
                patch.object(subject.fcntl, "fcntl", side_effect=(16, None, seals)) as mocked,
            ):
                descriptor = subject._sealed_seccomp(profile)
        self.assertEqual(descriptor, 73)
        created.assert_called_once_with("asterion-p1-development-seccomp", 48)
        self.assertEqual(mocked.call_args_list, [
            ((73, 256),),
            ((73, 64, seals),),
            ((73, 128),),
        ])

    async def test_service_context_close_releases_source_memfd_once(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject

        transport = SimpleNamespace(close=Mock())
        resources = subject._P1CliResources(  # type: ignore[attr-defined]
            image_digest="sha256:" + "a" * 64, transport=transport, operator_config={},
            node_bin="/operator/node", entrypoint="/operator/bridge.js", prime_source_root="/operator/prime",
            seccomp_fd=73,
        )
        service = subject.PrimeSmallVerificationService(resources)
        with patch.object(subject.os, "close") as close:
            service._close()  # type: ignore[attr-defined]
            service._close()  # type: ignore[attr-defined]
        close.assert_called_once_with(73)
        transport.close.assert_called_once_with()

    async def test_exact_context_opens_without_starting_the_verification_flow(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject

        ready = subject._P1CliResources(  # type: ignore[attr-defined]
            image_digest="sha256:" + "a" * 64,
            transport=object(),
            operator_config={"DEEPSEEK_API_KEY": "SENTINEL"},
            node_bin="/operator/node",
            entrypoint="/operator/bridge.js",
            prime_source_root="/operator/prime",
        )
        binding = subject.create_prime_p1_cli_factory(repo_root=Path("/unavailable"))
        with (
            patch.object(subject, "_preflight", return_value=ready) as preflight,
            patch.object(subject, "run_prime_p1b_development", new_callable=AsyncMock) as run,
        ):
            async with binding.factory(_context()) as service:
                self.assertIsInstance(service, subject.PrimeSmallVerificationService)
            preflight.assert_called_once()
            run.assert_not_awaited()

    async def test_verify_consumes_service_and_preserves_caller_run_id(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject
        from asterion.applications.prime_agent.operator.p1b_development_host import PrimeP1BDevelopmentTrace

        ready = subject._P1CliResources(  # type: ignore[attr-defined]
            image_digest="sha256:" + "a" * 64, transport=object(), operator_config={},
            node_bin="/operator/node", entrypoint="/operator/bridge.js", prime_source_root="/operator/prime",
        )
        binding = subject.create_prime_p1_cli_factory(repo_root=Path("/unavailable"))
        trace = PrimeP1BDevelopmentTrace(trace_sha256="sha256:" + "b" * 64)
        with (
            patch.object(subject, "_preflight", return_value=ready),
            patch.object(subject, "run_prime_p1b_development", new=AsyncMock(return_value=trace)) as run,
        ):
            async with binding.factory(_context()) as service:
                result = await service.verify(PrimeSmallVerificationRequest("caller-run-1"))
                self.assertEqual((result.run_id, result.scope, result.promotion, result.trace_sha256), ("caller-run-1", "p1-b-development", "unpromoted", trace.trace_sha256))
                with self.assertRaises(subject.PrimeP1CliHostError):
                    await service.verify(PrimeSmallVerificationRequest("caller-run-2"))
        run.assert_awaited_once_with(
            image_digest=ready.image_digest, transport=ready.transport, operator_config=ready.operator_config,
            node_bin=ready.node_bin, entrypoint=ready.entrypoint, prime_source_root=ready.prime_source_root,
            run_id="caller-run-1",
        )

    async def test_context_exit_and_bad_request_fail_closed_without_secret(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject

        ready = subject._P1CliResources(  # type: ignore[attr-defined]
            image_digest="sha256:" + "a" * 64, transport=object(), operator_config={"key": "SENTINEL"},
            node_bin="/operator/node", entrypoint="/operator/bridge.js", prime_source_root="/operator/prime",
        )
        binding = subject.create_prime_p1_cli_factory(repo_root=Path("/unavailable"))
        with patch.object(subject, "_preflight", return_value=ready):
            async with binding.factory(_context()) as service:
                with self.assertRaises(subject.PrimeP1CliHostError) as caught:
                    await service.verify(object())
            with self.assertRaises(subject.PrimeP1CliHostError):
                await service.verify(PrimeSmallVerificationRequest("caller-run-1"))
        self.assertNotIn("SENTINEL", str(caught.exception))

    async def test_cancellation_waits_for_p1b_cleanup_before_propagating(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject

        ready = subject._P1CliResources(  # type: ignore[attr-defined]
            image_digest="sha256:" + "a" * 64, transport=object(), operator_config={},
            node_bin="/operator/node", entrypoint="/operator/bridge.js", prime_source_root="/operator/prime",
        )
        completed = asyncio.Event()

        async def pending(**_: object) -> object:
            try:
                await asyncio.Event().wait()
            finally:
                completed.set()
            raise AssertionError("unreachable")

        binding = subject.create_prime_p1_cli_factory(repo_root=Path("/unavailable"))
        with (
            patch.object(subject, "_preflight", return_value=ready),
            patch.object(subject, "run_prime_p1b_development", side_effect=pending),
        ):
            async with binding.factory(_context()) as service:
                task = asyncio.create_task(service.verify(PrimeSmallVerificationRequest("caller-run-1"), signal=_Signal()))
                await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        self.assertTrue(completed.is_set())

    async def test_failed_p1b_task_is_reaped_before_safe_failure(self) -> None:
        from asterion.applications.prime_agent.operator import p1_cli_host as subject

        ready = subject._P1CliResources(  # type: ignore[attr-defined]
            image_digest="sha256:" + "a" * 64, transport=object(), operator_config={},
            node_bin="/operator/node", entrypoint="/operator/bridge.js", prime_source_root="/operator/prime",
        )
        completed = asyncio.Event()

        async def fails_after_cleanup(**_: object) -> object:
            try:
                raise RuntimeError("SENTINEL")
            finally:
                completed.set()

        binding = subject.create_prime_p1_cli_factory(repo_root=Path("/unavailable"))
        with (
            patch.object(subject, "_preflight", return_value=ready),
            patch.object(subject, "run_prime_p1b_development", side_effect=fails_after_cleanup),
        ):
            async with binding.factory(_context()) as service:
                with self.assertRaises(subject.PrimeP1CliHostError) as caught:
                    await service.verify(PrimeSmallVerificationRequest("caller-run-1"))
        self.assertTrue(completed.is_set())
        self.assertNotIn("SENTINEL", str(caught.exception))
