"""Provider-free P2 Docker facade checks."""

from __future__ import annotations
import unittest
from asterion.applications.prime_agent.operator.programmatic_long_context_docker_cli import (
    ProgrammaticLongContextDockerCli,
)
from asterion.services.restricted_worker import RestrictedWorkerError


class TestProgrammaticLongContextDockerCli(unittest.TestCase):
    def test_fixed_argv_uses_empty_host_environment_and_p2_only_identity(self) -> None:
        cli = ProgrammaticLongContextDockerCli(
            docker_executable="/usr/bin/docker",
            socket_path="/var/run/docker.sock",
            seccomp_profile="/etc/p2.json",
        )
        argv, env = cli.create_argv(
            container_id="prime-p2-" + "a" * 32, image_digest="sha256:" + "a" * 64
        )
        self.assertEqual(env, {})
        self.assertIn("--entrypoint", argv)
        self.assertIn("/usr/local/bin/prime-programmatic-long-context.mjs", argv)
        self.assertIn("seccomp=/etc/p2.json", argv)
        with self.assertRaises(RestrictedWorkerError):
            cli.create_argv(
                container_id="prime-" + "a" * 32, image_digest="sha256:" + "a" * 64
            )
