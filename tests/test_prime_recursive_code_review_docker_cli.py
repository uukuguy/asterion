"""Provider-free checks for the P3 fixed Docker facade."""

from __future__ import annotations

import unittest

from asterion.applications.prime_agent.operator.recursive_code_review_docker_cli import (
    RecursiveCodeReviewDockerCli,
)
from asterion.services.restricted_worker import RestrictedWorkerError


class TestRecursiveCodeReviewDockerCli(unittest.TestCase):
    def test_fixed_p3_only_argv_has_empty_environment(self) -> None:
        cli = RecursiveCodeReviewDockerCli(
            docker_executable="/usr/bin/docker", socket_path="/var/run/docker.sock",
            seccomp_profile="/etc/prime-p3.json",
        )
        argv, env = cli.create_argv(
            container_id="prime-p3-" + "a" * 32, image_digest="sha256:" + "a" * 64
        )
        self.assertEqual(env, {})
        self.assertIn("/usr/local/bin/prime-recursive-code-review.mjs", argv)
        self.assertIn("seccomp=/etc/prime-p3.json", argv)
        with self.assertRaises(RestrictedWorkerError):
            cli.create_argv(container_id="prime-p2-" + "a" * 32, image_digest="sha256:" + "a" * 64)
