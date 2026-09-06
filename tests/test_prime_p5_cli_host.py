from __future__ import annotations

import unittest
import asyncio
from pathlib import Path
from unittest.mock import patch


class TestP5CliHost(unittest.TestCase):
    def test_runner_constructs_the_real_worker_without_progress_keyword(self) -> None:
        from asterion.applications.prime_agent.operator import p5_cli_host as subject

        class Worker:
            def __init__(self, *, image_digest: str, transport: object, run_id: str, session_id: str, goal_id: str, workspace: str) -> None:
                del image_digest, transport, run_id, session_id, goal_id, workspace

        async def lifecycle(**_: object) -> object:
            return type("Trace", (), {"trace_sha256": "sha256:" + "a" * 64})()

        resources = subject._P5CliResources("sha256:" + "b" * 64, object(), {}, "/node", "/entry", "/prime")
        with (
            patch.object(subject, "P5DevelopmentDockerWorkerService", Worker),
            patch.object(subject, "create_prime_p5_development_sdk_provider", return_value=object()),
            patch.object(subject, "PrimeP5DevelopmentGateway", return_value=object()),
            patch.object(subject, "run_p5_development_lifecycle", lifecycle),
            patch.object(subject, "_prepare_workspace"),
        ):
            asyncio.run(subject._run_p5_development_lifecycle(resources, "p5-run"))

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
