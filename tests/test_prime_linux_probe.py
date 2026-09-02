"""Provider-free tests for the Prime Linux backend readiness probe."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from asterion.applications.prime_agent.operator.linux_probe import (
    LinuxBackendFacts,
    PrimeLinuxBackendProbe,
)


def _facts(**changes: object) -> LinuxBackendFacts:
    values: dict[str, object] = {
        "engine": "native-docker", "daemon_available": True, "image_available": True,
        "operator_ready": True, "safety_matches": True,
    }
    values.update(changes)
    return LinuxBackendFacts(**values)  # type: ignore[arg-type]


class TestPrimeLinuxBackendProbe(unittest.TestCase):
    def test_non_linux_platforms_are_external_limited_without_action(self) -> None:
        for platform_name in ("Darwin", "Windows", "FreeBSD"):
            calls = 0

            def inspect() -> LinuxBackendFacts:
                nonlocal calls
                calls += 1
                return _facts()

            with self.subTest(platform_name=platform_name):
                result = PrimeLinuxBackendProbe(platform_name, inspect).probe()
                self.assertEqual((result.status, result.reason), ("External-limited", "unsupported-platform"))
                self.assertEqual(calls, 0)

    def test_linux_classifies_non_native_and_missing_preconditions(self) -> None:
        cases = (
            ("desktop", _facts(engine="docker-desktop"), "unsupported-engine"),
            ("orbstack", _facts(engine="orbstack"), "unsupported-engine"),
            ("unknown", _facts(engine="podman"), "unsupported-engine"),
            ("daemon", _facts(daemon_available=False), "missing-precondition"),
            ("image", _facts(image_available=False), "missing-precondition"),
            ("operator", _facts(operator_ready=False), "missing-precondition"),
        )
        for name, facts, reason in cases:
            with self.subTest(name=name):
                result = PrimeLinuxBackendProbe("Linux", lambda: facts).probe()
                self.assertEqual((result.status, result.reason), ("External-limited", reason))

    def test_safety_mismatch_fails_and_exact_native_linux_is_ready(self) -> None:
        failed = PrimeLinuxBackendProbe("Linux", lambda: _facts(safety_matches=False)).probe()
        self.assertEqual((failed.status, failed.reason), ("failure", "safety-mismatch"))

        ready = PrimeLinuxBackendProbe("Linux", _facts).probe()
        self.assertEqual((ready.status, ready.reason), ("ready", "native-linux-ready"))
        self.assertEqual(tuple(ready.__dataclass_fields__), ("status", "reason"))
        with self.assertRaises(FrozenInstanceError):
            ready.status = "PASS"  # type: ignore[misc]
        rendered = repr(ready)
        for secret in ("provider", "model", "prompt", "credential", "socket", "token"):
            self.assertNotIn(secret, rendered)

