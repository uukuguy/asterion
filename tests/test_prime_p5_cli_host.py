from __future__ import annotations

import unittest
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class TestP5CliHost(unittest.TestCase):
    def test_runner_forwards_progress_to_lifecycle_not_worker(self) -> None:
        from asterion.applications.prime_agent.operator import p5_cli_host as subject

        class Worker:
            def __init__(self, *, image_digest: str, transport: object, run_id: str, session_id: str, goal_id: str, workspace: str) -> None:
                del image_digest, transport, run_id, session_id, goal_id, workspace

        received: dict[str, object] = {}

        async def lifecycle(**kwargs: object) -> object:
            received.update(kwargs)
            return type("Trace", (), {"trace_sha256": "sha256:" + "a" * 64})()

        resources = subject._P5CliResources("sha256:" + "b" * 64, object(), {}, "/node", "/entry", "/prime")
        with (
            patch.object(subject, "P5DevelopmentDockerWorkerService", Worker),
            patch.object(subject, "create_prime_p5_development_sdk_provider", return_value=object()),
            patch.object(subject, "PrimeP5DevelopmentGateway", return_value=object()),
            patch.object(subject, "run_p5_development_lifecycle", lifecycle),
            patch.object(subject, "_prepare_workspace"),
        ):
            reporter = object()
            asyncio.run(subject._run_p5_development_lifecycle(resources, "p5-run", reporter))
        self.assertIs(received["progress"], reporter)

    def test_preflight_closes_sealed_descriptor_when_config_rejects(self) -> None:
        from asterion.applications.prime_agent.operator import p5_cli_host as subject

        paths = type("Paths", (), {
            "node": Path("/node"), "gateway_root": Path("/gateway"),
            "source_root": Path("/source"), "seccomp": Path("/seccomp"),
        })()
        with (
            patch.object(subject, "_regular_executable", side_effect=lambda path: path),
            patch.object(subject, "_regular_file", side_effect=lambda path: path),
            patch.object(subject, "_regular_directory", side_effect=lambda path: path),
            patch.object(subject, "_inspect_image", return_value="sha256:" + "a" * 64),
            patch.object(subject, "_sealed_seccomp", return_value=31),
            patch.object(subject, "_operator_config", side_effect=ValueError),
            patch.object(subject.os, "lstat", return_value=SimpleNamespace(st_mode=0)),
            patch.object(subject.stat, "S_ISSOCK", return_value=True),
            patch.object(subject.os, "close") as close,
        ):
            with self.assertRaises(subject.PrimeP5CliHostError):
                subject._preflight(Path("/repo"), paths=paths)
        close.assert_called_once_with(31)

    def test_sets_the_finite_outer_deadline(self) -> None:
        from asterion.applications.prime_agent.operator.p5_cli_host import (
            P5_CLI_DEADLINE_SECONDS,
        )

        self.assertEqual(P5_CLI_DEADLINE_SECONDS, 300)

    def test_resolves_the_rehashed_prepared_p5_paths(self) -> None:
        from asterion.applications.prime_agent.operator import p5_cli_host as subject

        expected = object()
        with (
            patch.object(subject.sys, "platform", "linux"),
            patch.object(subject.os, "geteuid", return_value=0),
            patch.object(subject, "resolve_prepared_prime_development", return_value=expected) as resolve,
        ):
            self.assertIs(subject._prepared_paths(Path("/repo")), expected)
        resolve.assert_called_once_with(Path("/repo"), "p5")
