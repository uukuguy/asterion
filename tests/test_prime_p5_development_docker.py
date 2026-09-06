from __future__ import annotations

import unittest


class TestP5DevelopmentDocker(unittest.TestCase):
    def test_uses_the_single_admitted_p1b_worker_profile(self) -> None:
        from asterion.applications.prime_agent.operator.p5_development_docker import (
            P5DevelopmentDockerWorkerService,
        )

        self.assertEqual(
            P5DevelopmentDockerWorkerService.__name__,
            "P1BDockerPersistentWorkerService",
        )
