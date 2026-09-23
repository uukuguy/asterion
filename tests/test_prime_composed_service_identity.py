"""Composed Prime hosts reject a declared service that differs from the one used."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from asterion.applications.prime.p5.operator import (
    P5OperatorError,
    _ComposedLoopHost,
)
from asterion.applications.prime.p6.operator import (
    P6OperatorError,
    _ComposedCandidateHost,
)


class PrimeComposedServiceIdentityTests(unittest.TestCase):
    def test_p5_rejects_service_identity_drift(self) -> None:
        loop, extension, oracle, trace = object(), object(), object(), object()
        resources = SimpleNamespace(
            pi_extension=extension, p5_oracle=oracle, private_trace=trace
        )
        host = _ComposedLoopHost(loop, resources)
        services = {
            "prime.ipython": loop,
            "prime.pi-extension": extension,
            "prime.session-backend": host,
            "prime.p5-oracle": oracle,
            "prime.private-trace": trace,
        }
        host.validate_runtime_services(services)
        for name in services:
            with self.subTest(name=name):
                drifted = dict(services)
                drifted[name] = object()
                with self.assertRaises(P5OperatorError):
                    host.validate_runtime_services(drifted)

    def test_p6_rejects_service_identity_drift(self) -> None:
        loop, coordinator, oracle = object(), object(), object()
        resources = SimpleNamespace(p6_oracle=oracle)
        host = _ComposedCandidateHost(resources, loop, coordinator)
        services = {
            "prime.candidate-store": loop,
            "prime.pi-extension": coordinator,
            "prime.session-backend": host,
            "prime.p6-oracle": oracle,
            "prime.private-trace": None,
        }
        host.validate_runtime_services(services)
        for name in services:
            with self.subTest(name=name):
                drifted = dict(services)
                drifted[name] = object()
                with self.assertRaises(P6OperatorError):
                    host.validate_runtime_services(drifted)


if __name__ == "__main__":
    unittest.main()
