from __future__ import annotations
import unittest
class TestPrimeP3DevelopmentDocker(unittest.TestCase):
    def test_only_root_receives_rlm_socket(self) -> None:
        from asterion.applications.prime_agent.operator.p3_development_docker import p3_worker_identities
        workers = p3_worker_identities("/workspace", "/run/rlm.sock")
        self.assertEqual([worker.rlm_socket is not None for worker in workers], [True, False, False])
