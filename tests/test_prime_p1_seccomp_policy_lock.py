"""Tests for the fail-closed, code-owned Prime P1 seccomp policy catalog."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import hashlib
import inspect
import json
import os
from pathlib import Path
import unittest
from typing import Any, cast
from unittest.mock import patch

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)
from asterion.applications.prime_agent.operator.seccomp_policy_lock import (
    PrimeP1SeccompPolicyLockError,
    PromotedSeccompPolicyCatalog,
    SeccompPolicyLock,
    canonical_seccomp_policy_lock_bytes,
    parse_canonical_seccomp_policy_lock,
    resolve_promoted_seccomp_policy,
    seccomp_policy_lock_sha256,
)


def _lock(**changes: object) -> SeccompPolicyLock:
    values: dict[str, object] = {
        "schema_version": "asterion.prime-p1-seccomp-policy-lock/v1",
        "platform": ImagePlatformDescriptor("linux", "amd64", None),
        "libseccomp_architecture": "SCMP_ARCH_X86_64",
        "image_config_digest": "sha256:" + "a" * 64,
        "build_input_sha256": "b" * 64,
        "launcher_sha256": "c" * 64,
        "workload_sha256": "d" * 64,
        "starter_sha256": "e" * 64,
        "oracle_sha256": "f" * 64,
        "default_action": "SCMP_ACT_ERRNO",
        "allowed_rule_atoms": ("read", "write"),
        "profile_sha256": "0" * 64,
    }
    values.update(changes)
    return SeccompPolicyLock(**values)  # type: ignore[arg-type]


class TestPrimeP1SeccompPolicyLock(unittest.TestCase):
    def test_canonical_round_trip_and_digest_are_deterministic(self) -> None:
        lock = _lock()
        first = canonical_seccomp_policy_lock_bytes(lock)
        second = canonical_seccomp_policy_lock_bytes(lock)
        self.assertIsInstance(first, bytes)
        self.assertEqual(first, second)
        self.assertEqual(parse_canonical_seccomp_policy_lock(first), lock)
        self.assertEqual(
            seccomp_policy_lock_sha256(lock), hashlib.sha256(first).hexdigest()
        )
        decoded = json.loads(first)
        self.assertEqual(decoded["platform"], {"architecture": "amd64", "os": "linux", "variant": None})
        self.assertEqual(decoded["allowed_rule_atoms"], ["read", "write"])

    def test_rejects_noncanonical_locks_and_parser_bytes(self) -> None:
        invalid_locks = (
            _lock(libseccomp_architecture="SCMP_ARCH_NATIVE"),
            _lock(default_action="SCMP_ACT_ALLOW"),
            _lock(allowed_rule_atoms=("write", "read")),
            _lock(allowed_rule_atoms=("read", "read")),
            _lock(profile_sha256="A" * 64),
            _lock(platform=ImagePlatformDescriptor("Linux", "amd64", None)),
        )
        for lock in invalid_locks:
            with self.subTest(lock=repr(lock)):
                with self.assertRaises(PrimeP1SeccompPolicyLockError):
                    canonical_seccomp_policy_lock_bytes(lock)
        payload = canonical_seccomp_policy_lock_bytes(_lock())
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            parse_canonical_seccomp_policy_lock(payload + b" ")

    def test_empty_catalog_and_platform_mismatch_fail_closed(self) -> None:
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            resolve_promoted_seccomp_policy(ImagePlatformDescriptor("linux", "amd64", None))
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as module

        catalog = PromotedSeccompPolicyCatalog((_lock(),))
        with patch.object(module, "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG", catalog):
            with self.assertRaises(PrimeP1SeccompPolicyLockError):
                resolve_promoted_seccomp_policy(
                    ImagePlatformDescriptor("linux", "arm64", None)
                )

    def test_is_immutable_and_has_no_host_or_authority_imports(self) -> None:
        lock = _lock()
        self.assertEqual(repr(lock), "SeccompPolicyLock(redacted)")
        self.assertNotIn("a" * 64, repr(lock))
        with self.assertRaises((AttributeError, TypeError)):
            cast(Any, lock).allowed_rule_atoms += ("close",)
        with self.assertRaises((AttributeError, TypeError, FrozenInstanceError)):
            lock.platform.os = "linux"  # type: ignore[misc]

        def forbidden(*_: object, **__: object) -> object:
            raise AssertionError("host access is forbidden")

        with (
            patch.object(os, "getcwd", side_effect=forbidden),
            patch.object(os, "getenv", side_effect=forbidden),
            patch.dict(os.environ, {"PYTHONHASHSEED": "hostile"}),
        ):
            self.assertEqual(seccomp_policy_lock_sha256(lock), seccomp_policy_lock_sha256(lock))

        import asterion.applications.prime_agent.operator.seccomp_policy_lock as module

        source = Path(inspect.getfile(module)).read_text(encoding="utf-8")
        imports = {
            alias.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module or ""
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
        }
        self.assertFalse(
            any(
                forbidden_name in module_name
                for forbidden_name in (
                    "authority_config",
                    "authority_resources",
                    "docker",
                    "model_session_host",
                    "network",
                    "os",
                    "socket",
                    "subprocess",
                    "sys",
                )
                for module_name in imports
            )
        )


if __name__ == "__main__":
    unittest.main()
