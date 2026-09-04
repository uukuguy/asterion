"""Provider-free contract tests for the production-only Prime P1 host."""

from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from typing import cast
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator.production_host import (
    PrimeP1ProductionHostCapability,
    PrimeP1ProductionHostError,
    create_prime_p1_production_factory,
)
from asterion.applications.prime_agent.provider import create_provider
from asterion.services.registry import HostServiceFactoryContext


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


class TestPrimeP1ProductionHost(unittest.IsolatedAsyncioTestCase):
    async def test_selected_application_declares_the_production_host_capability(self) -> None:
        provider = create_provider()
        selected = [
            application
            for application in provider.applications
            if application.application_id == "prime.ipython-coding"
        ]
        self.assertEqual(len(selected), 1)
        assembly = selected[0].assembly_paths[0].read_text(encoding="utf-8")
        self.assertIn('"application_id": "prime.ipython-coding"', assembly)
        self.assertIn('"prime.ipython-production"', assembly)

    async def test_factory_rejects_every_nonselected_context_before_private_reads(self) -> None:
        cases = (
            {"provider_id": "other"},
            {"application_id": "prime.capability-program"},
            {"application_version": "2.0.0"},
            {"capability_id": "model.bounded-session"},
            {"options": {"model": "private"}},
        )
        binding = create_prime_p1_production_factory(repo_root=Path("/unavailable"))
        for changes in cases:
            with self.subTest(changes=changes), patch(
                "asterion.applications.prime_agent.operator.production_host.dotenv_values"
            ) as dotenv:
                with self.assertRaises(PrimeP1ProductionHostError):
                    async with binding.factory(_context(**changes)):
                        pass
                dotenv.assert_not_called()

    async def test_missing_or_injected_configuration_cannot_create_authority(self) -> None:
        sentinel = "SENTINEL-PROCESS-SECRET"
        with TemporaryDirectory() as directory:
            binding = create_prime_p1_production_factory(
                repo_root=Path(directory),
                environment={"DEEPSEEK_API_KEY": sentinel},
            )
            with self.assertRaises(PrimeP1ProductionHostError) as raised:
                async with binding.factory(_context()):
                    pass
        self.assertNotIn(sentinel, str(raised.exception))
        self.assertNotIn(sentinel, repr(binding))

    async def test_static_preflight_mints_one_redacted_one_shot_authority_without_io(self) -> None:
        sentinel = "SENTINEL-PRIVATE-MODEL-KEY"
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            docker = root / "docker"
            docker.write_bytes(b"#!/bin/sh\nexit 1\n")
            docker.chmod(0o700)
            seccomp = root / "seccomp.json"
            seccomp.write_text(
                '{"architectures":["SCMP_ARCH_NATIVE"],"defaultAction":"SCMP_ACT_ERRNO",'
                '"syscalls":[{"action":"SCMP_ACT_ALLOW","names":["read","write"]}]}',
                encoding="utf-8",
            )
            socket_path = root / "docker.sock"
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(socket_path))
            try:
                (root / ".env").write_text(
                    "\n".join(
                        (
                            f"ASTERION_PRIME_P1_DOCKER_EXECUTABLE={docker}",
                            f"ASTERION_PRIME_P1_DOCKER_SOCKET={socket_path}",
                            f"ASTERION_PRIME_P1_SECCOMP_PROFILE={seccomp}",
                            "ASTERION_PRIME_P1_IMAGE_DIGEST=sha256:" + "a" * 64,
                            "ASTERION_PRIME_EXPERIMENT_MODEL=deepseek-v4-flash",
                            "DEEPSEEK_API_KEY=" + sentinel,
                        )
                    )
                    + "\n",
                    encoding="utf-8",
                )
                binding = create_prime_p1_production_factory(repo_root=root)
                with patch("asyncio.create_subprocess_exec") as subprocess_call, patch(
                    "urllib.request.urlopen"
                ) as network_call:
                    async with AsyncExitStack() as stack:
                        capability = cast(
                            PrimeP1ProductionHostCapability,
                            await stack.enter_async_context(binding.factory(_context())),
                        )
                        authority = capability.authorize("run-1")
                        with self.assertRaises(PrimeP1ProductionHostError):
                            capability.authorize("run-2")
                        import asterion.applications.prime_agent.operator.ipython_host_issuer as issuer

                        with self.assertRaisesRegex(Exception, "unavailable"):
                            await issuer._issue_production_ipython_host_live_run(  # noqa: SLF001
                                capability=authority
                            )
                        with self.assertRaisesRegex(Exception, "unavailable"):
                            await issuer._issue_production_ipython_host_live_run(  # noqa: SLF001
                                capability=authority
                            )
                subprocess_call.assert_not_called()
                network_call.assert_not_called()
            finally:
                listener.close()
        self.assertNotIn(sentinel, repr(capability))
        self.assertNotIn(sentinel, repr(authority))
        self.assertFalse(hasattr(authority, "provider"))
        self.assertFalse(hasattr(authority, "docker"))

    async def test_symlinked_or_non_socket_production_resources_fail_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "docker-real"
            executable.write_bytes(b"#!/bin/sh\n")
            executable.chmod(0o700)
            docker = root / "docker"
            docker.symlink_to(executable)
            seccomp = root / "seccomp.json"
            seccomp.write_text(
                '{"architectures":["SCMP_ARCH_NATIVE"],"defaultAction":"SCMP_ACT_ERRNO",'
                '"syscalls":[{"action":"SCMP_ACT_ALLOW","names":["read"]}]}',
                encoding="utf-8",
            )
            ordinary = root / "docker.sock"
            ordinary.write_bytes(b"not-a-socket")
            (root / ".env").write_text(
                f"ASTERION_PRIME_P1_DOCKER_EXECUTABLE={docker}\n"
                f"ASTERION_PRIME_P1_DOCKER_SOCKET={ordinary}\n"
                f"ASTERION_PRIME_P1_SECCOMP_PROFILE={seccomp}\n"
                + "ASTERION_PRIME_P1_IMAGE_DIGEST=sha256:" + "a" * 64 + "\n"
                + "ASTERION_PRIME_EXPERIMENT_MODEL=deepseek-v4-flash\n"
                + "DEEPSEEK_API_KEY=key\n",
                encoding="utf-8",
            )
            binding = create_prime_p1_production_factory(repo_root=root)
            with self.assertRaises(PrimeP1ProductionHostError):
                async with binding.factory(_context()):
                    pass

    async def test_manual_or_fake_authority_remains_unavailable(self) -> None:
        import asterion.applications.prime_agent.operator.ipython_host_issuer as issuer

        with self.assertRaisesRegex(Exception, "unavailable"):
            await issuer._issue_production_ipython_host_live_run(  # noqa: SLF001
                capability=object()
            )


if __name__ == "__main__":
    unittest.main()
