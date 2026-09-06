"""Focused installed-host contract for the P2 development verification."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from asterion.runtimes.prime_agent_host import PrimeSmallVerificationRequest
from asterion.services.progress import HostProgressEvent
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
    def test_preflight_resolves_prepared_paths_before_docker_or_credentials(self) -> None:
        from asterion.applications.prime_agent.operator import p2_cli_host as subject

        paths = SimpleNamespace(
            node=Path("/prepared/node"),
            seccomp=Path("/prepared/seccomp.json"),
            gateway_root=Path("/prepared/gateway"),
            source_root=Path("/prepared/prime"),
        )
        with (
            patch.object(subject.sys, "platform", "linux"),
            patch.object(subject.os, "geteuid", return_value=0),
            patch.object(subject, "resolve_prepared_prime_development", return_value=paths, create=True) as resolve,
            patch.object(subject, "_regular_executable", side_effect=AssertionError("docker opened")),
            patch.object(subject, "_operator_config", side_effect=AssertionError("credentials read")),
        ):
            with self.assertRaises(subject.PrimeP2CliHostError):
                subject._preflight(Path("/repo"))
        resolve.assert_called_once_with(Path("/repo"), "p2")

    def test_preflight_uses_only_prepared_paths_and_keeps_exact_image_argv(self) -> None:
        from asterion.applications.prime_agent.operator import p2_cli_host as subject

        paths = SimpleNamespace(
            node=Path("/prepared/node"),
            seccomp=Path("/prepared/seccomp.json"),
            gateway_root=Path("/prepared/gateway"),
            source_root=Path("/prepared/prime"),
        )
        transport = SimpleNamespace(close=Mock())
        with (
            patch.object(subject.sys, "platform", "linux"),
            patch.object(subject.os, "geteuid", return_value=0),
            patch.object(subject, "resolve_prepared_prime_development", return_value=paths, create=True),
            patch.object(subject, "_regular_executable", side_effect=(Path("/docker"), paths.node)),
            patch.object(subject.os, "lstat", return_value=SimpleNamespace(st_mode=0)),
            patch.object(subject.stat, "S_ISSOCK", return_value=True),
            patch.object(subject, "_regular_file", side_effect=(paths.gateway_root / "dist/src/p2-development-main.js", paths.source_root / "packages/coding-agent/dist/core/sdk.js", paths.source_root / "node_modules/typebox/build/index.mjs")) as files,
            patch.object(subject, "_regular_directory", return_value=paths.source_root),
            patch.object(subject, "_sealed_seccomp", return_value=73) as seal,
            patch.object(subject, "_inspect_image", return_value="sha256:" + "a" * 64),
            patch.object(subject, "_host_platform", return_value=object()),
            patch.object(subject, "PrimeP2DevelopmentDockerTransport", return_value=transport),
            patch.object(subject, "_operator_config", return_value={}),
        ):
            resources = subject._preflight(Path("/repo"))
        self.assertEqual(resources.node_bin, "/prepared/node")
        self.assertEqual(resources.prime_source_root, "/prepared/prime")
        seal.assert_called_once_with(paths.seccomp)
        self.assertNotIn("/tmp", repr(files.call_args_list))

    def test_image_inspection_uses_the_exact_docker_argv(self) -> None:
        from asterion.applications.prime_agent.operator import p2_cli_host as subject

        result = SimpleNamespace(returncode=0, stdout=(subject._CONFIRMED_IMAGE_DIGEST + "\n").encode())
        with patch.object(subject.subprocess, "run", return_value=result) as run:
            subject._inspect_image(Path("/usr/bin/docker"), Path("/var/run/docker.sock"))
        self.assertEqual(
            run.call_args.args[0],
            ("/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "image", "inspect", "--format", "{{.Id}}", "asterion-p2-development:20260906"),
        )

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
            patch.object(subject, "_prepared_paths", return_value=object()),
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
            progress=_context().progress,
        )

    async def test_factory_reports_preflight_failure_without_opening_service(self) -> None:
        from asterion.applications.prime_agent.operator import p2_cli_host as subject

        reporter = Mock()
        binding = subject.create_prime_p2_cli_factory(repo_root=Path("/repo"))
        with patch.object(subject, "_prepared_paths", side_effect=ValueError("private")):
            with self.assertRaises(subject.PrimeP2CliHostError):
                async with binding.factory(_context(progress=reporter)):
                    pass
        self.assertEqual(
            reporter.emit.call_args_list,
            [
                ((HostProgressEvent("preflight", "started"),),),
                ((HostProgressEvent("preflight", "failed"),),),
            ],
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
