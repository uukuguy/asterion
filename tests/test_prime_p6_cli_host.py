from __future__ import annotations

from pathlib import Path
import asyncio
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


class TestP6CliHost(unittest.TestCase):
    def test_runner_constructs_the_real_worker_without_progress_keyword(self) -> None:
        from asterion.applications.prime_agent.operator import p6_cli_host as subject

        class Worker:
            def __init__(self, *, image_digest: str, transport: object, run_id: str, session_id: str, goal_id: str, workspace: str) -> None:
                del image_digest, transport, run_id, session_id, goal_id, workspace

        async def lifecycle(**_: object) -> object:
            return type("Receipt", (), {"trace_sha256": "sha256:" + "a" * 64})()

        resources = subject._P6CliResources("sha256:" + "b" * 64, object(), {}, "/node", "/entry", "/prime")
        with (
            patch.object(subject, "P6DevelopmentDockerWorkerService", Worker),
            patch.object(subject, "create_prime_p6_development_sdk_provider", return_value=object()),
            patch.object(subject, "PrimeP6DevelopmentGateway", return_value=object()),
            patch.object(subject, "run_p6_development_lifecycle", lifecycle),
            patch.object(subject, "_prepare_workspace"),
        ):
            asyncio.run(subject._run_p6_development_lifecycle(resources, "p6-run"))

    def test_sets_the_finite_outer_deadline(self) -> None:
        from asterion.applications.prime_agent.operator.p6_cli_host import (
            P6_CLI_DEADLINE_SECONDS,
        )

        self.assertEqual(P6_CLI_DEADLINE_SECONDS, 300)

    def test_resolves_the_rehashed_prepared_p6_paths(self) -> None:
        from asterion.applications.prime_agent.operator import p6_cli_host as subject

        expected = object()
        with (
            patch.object(subject.sys, "platform", "linux"),
            patch.object(subject.os, "geteuid", return_value=0),
            patch.object(subject, "resolve_prepared_prime_development", return_value=expected) as resolve,
        ):
            self.assertIs(subject._prepared_paths(Path("/repo")), expected)
        resolve.assert_called_once_with(Path("/repo"), "p6")

    def test_prepares_only_the_owned_p6_baseline(self) -> None:
        from asterion.applications.prime_agent.operator.p6_cli_host import (
            _prepare_workspace,
        )

        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with patch("os.chown") as chown:
                _prepare_workspace(workspace)
            self.assertEqual([path.name for path in workspace.iterdir()], ["baseline.py"])
            self.assertEqual(
                (workspace / "baseline.py").read_bytes(),
                b"def clamp(value, lower, upper):\n    return min(upper, value)\n",
            )
            self.assertEqual(chown.call_count, 2)
