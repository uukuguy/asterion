"""Tests for the fail-closed, code-owned Prime P1 seccomp policy catalog."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
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
    SeccompArgumentConstraint,
    SeccompPolicyLock,
    SeccompRuleAtom,
    canonical_maximum_seccomp_profile_bytes,
    canonical_seccomp_policy_lock_bytes,
    parse_canonical_seccomp_policy_lock,
    resolve_promoted_seccomp_policy,
    seccomp_policy_lock_sha256,
)

_READ = SeccompRuleAtom(
    "read", (SeccompArgumentConstraint(0, "SCMP_CMP_EQ", 0, None),)
)
_WRITE = SeccompRuleAtom(
    "write", (SeccompArgumentConstraint(0, "SCMP_CMP_MASKED_EQ", 1, 3),)
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
        "allowed_rule_atoms": (_READ, _WRITE),
        "maximum_profile_sha256": "0" * 64,
    }
    has_supplied_maximum = "maximum_profile_sha256" in changes
    values.update(changes)
    provisional = SeccompPolicyLock(**values)  # type: ignore[arg-type]
    if not has_supplied_maximum:
        try:
            values["maximum_profile_sha256"] = hashlib.sha256(
                _independent_maximum_profile_bytes(provisional)
            ).hexdigest()
        except (AttributeError, PrimeP1SeccompPolicyLockError):
            return provisional
    return SeccompPolicyLock(**values)  # type: ignore[arg-type]


def _independent_maximum_profile_bytes(lock: SeccompPolicyLock) -> bytes:
    return json.dumps(
        {
            "architectures": [lock.libseccomp_architecture],
            "defaultAction": "SCMP_ACT_ERRNO",
            "syscalls": [
                {
                    "action": "SCMP_ACT_ALLOW",
                    "args": [
                        {**{"index": item.index, "op": item.op, "value": item.value}, **({"valueTwo": item.value_two} if item.value_two is not None else {})}
                        for item in atom.arguments
                    ],
                    "names": [atom.syscall],
                }
                for atom in lock.allowed_rule_atoms
            ],
        },
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode()


class TestPrimeP1SeccompPolicyLock(unittest.TestCase):
    def test_maximum_profile_is_canonical_and_intrinsic(self) -> None:
        lock = _lock()
        profile = canonical_maximum_seccomp_profile_bytes(lock)
        self.assertEqual(
            profile,
            b'{"architectures":["SCMP_ARCH_X86_64"],"defaultAction":"SCMP_ACT_ERRNO",'
            b'"syscalls":[{"action":"SCMP_ACT_ALLOW","args":[{"index":0,"op":"SCMP_CMP_EQ","value":0}],"names":["read"]},'
            b'{"action":"SCMP_ACT_ALLOW","args":[{"index":0,"op":"SCMP_CMP_MASKED_EQ","value":1,"valueTwo":3}],"names":["write"]}]}'
        )
        self.assertEqual(lock.maximum_profile_sha256, hashlib.sha256(profile).hexdigest())
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            canonical_seccomp_policy_lock_bytes(
                replace(lock, maximum_profile_sha256="0" * 64)
            )

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
        self.assertEqual(
            decoded["platform"],
            {"architecture": "amd64", "os": "linux", "variant": None},
        )
        self.assertEqual(
            decoded["allowed_rule_atoms"],
            [
                {
                    "arguments": [
                        {
                            "index": 0,
                            "op": "SCMP_CMP_EQ",
                            "value": 0,
                            "value_two": None,
                        }
                    ],
                    "syscall": "read",
                },
                {
                    "arguments": [
                        {
                            "index": 0,
                            "op": "SCMP_CMP_MASKED_EQ",
                            "value": 1,
                            "value_two": 3,
                        }
                    ],
                    "syscall": "write",
                },
            ],
        )

    def test_rejects_noncanonical_locks_and_parser_bytes(self) -> None:
        invalid_locks = (
            _lock(libseccomp_architecture="SCMP_ARCH_NATIVE"),
            _lock(libseccomp_architecture="SCMP_ARCH_AARCH64"),
            _lock(default_action="SCMP_ACT_ALLOW"),
            _lock(allowed_rule_atoms=(_WRITE, _READ)),
            _lock(allowed_rule_atoms=(_READ, _READ)),
            _lock(allowed_rule_atoms=("read",)),
            _lock(
                allowed_rule_atoms=(
                    SeccompRuleAtom(
                        "read",
                        (SeccompArgumentConstraint(0, "SCMP_CMP_EQ", 0, 1),),
                    ),
                )
            ),
            _lock(
                allowed_rule_atoms=(
                    SeccompRuleAtom(
                        "read",
                        (SeccompArgumentConstraint(True, "SCMP_CMP_EQ", 0, None),),
                    ),
                )
            ),
            _lock(maximum_profile_sha256="A" * 64),
            _lock(platform=ImagePlatformDescriptor("Linux", "amd64", None)),
        )
        for lock in invalid_locks:
            with self.subTest(lock=repr(lock)):
                with self.assertRaises(PrimeP1SeccompPolicyLockError):
                    canonical_seccomp_policy_lock_bytes(lock)
        valid_lock = _lock()
        payload = canonical_seccomp_policy_lock_bytes(valid_lock)
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            parse_canonical_seccomp_policy_lock(payload + b" ")
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            parse_canonical_seccomp_policy_lock(
                payload[:-1] + b',"schema_version":"duplicate"}'
            )
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            parse_canonical_seccomp_policy_lock(
                payload.replace(
                    b'"maximum_profile_sha256":"' + valid_lock.maximum_profile_sha256.encode() + b'"',
                    b'"maximum_profile_sha256":NaN',
                )
            )
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            parse_canonical_seccomp_policy_lock(
                payload.replace(
                    b'"maximum_profile_sha256":"' + valid_lock.maximum_profile_sha256.encode() + b'"',
                    b'"maximum_profile_sha256":Infinity',
                )
            )

    def test_platform_architecture_mapping_is_exact_and_host_independent(self) -> None:
        arm64 = _lock(
            platform=ImagePlatformDescriptor("linux", "arm64", None),
            libseccomp_architecture="SCMP_ARCH_AARCH64",
        )
        self.assertEqual(parse_canonical_seccomp_policy_lock(canonical_seccomp_policy_lock_bytes(arm64)), arm64)
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            canonical_seccomp_policy_lock_bytes(
                _lock(platform=ImagePlatformDescriptor("linux", "arm64", None))
            )
        with self.assertRaises(PrimeP1SeccompPolicyLockError):
            canonical_seccomp_policy_lock_bytes(
                _lock(platform=ImagePlatformDescriptor("linux", "amd64", "v8"))
            )

    def test_constraint_values_are_bounded_unsigned_64_bit_integers(self) -> None:
        maximum = 2**64 - 1
        accepted = (
            SeccompRuleAtom(
                "read", (SeccompArgumentConstraint(0, "SCMP_CMP_EQ", 0, None),)
            ),
            SeccompRuleAtom(
                "write",
                (
                    SeccompArgumentConstraint(
                        0, "SCMP_CMP_MASKED_EQ", maximum, maximum
                    ),
                ),
            ),
        )
        for atom in accepted:
            with self.subTest(atom=repr(atom)):
                canonical_seccomp_policy_lock_bytes(_lock(allowed_rule_atoms=(atom,)))
        invalid = (
            SeccompArgumentConstraint(0, "SCMP_CMP_EQ", -1, None),
            SeccompArgumentConstraint(0, "SCMP_CMP_EQ", 2**64, None),
            SeccompArgumentConstraint(0, "SCMP_CMP_EQ", 10**100, None),
            SeccompArgumentConstraint(0, "SCMP_CMP_MASKED_EQ", 0, -1),
            SeccompArgumentConstraint(0, "SCMP_CMP_MASKED_EQ", 0, 2**64),
            SeccompArgumentConstraint(0, "SCMP_CMP_MASKED_EQ", 0, 10**100),
        )
        for constraint in invalid:
            with self.subTest(constraint=repr(constraint)):
                with self.assertRaises(PrimeP1SeccompPolicyLockError):
                    canonical_seccomp_policy_lock_bytes(
                        _lock(
                            allowed_rule_atoms=(
                                SeccompRuleAtom("read", (constraint,)),
                            )
                        )
                    )

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
        self.assertEqual(list(inspect.signature(resolve_promoted_seccomp_policy).parameters), ["platform"])
        with self.assertRaises(TypeError):
            cast(Any, resolve_promoted_seccomp_policy)(
                ImagePlatformDescriptor("linux", "amd64", None), catalog
            )

    def test_is_immutable_and_has_no_host_or_authority_imports(self) -> None:
        lock = _lock()
        self.assertEqual(repr(lock), "SeccompPolicyLock(redacted)")
        self.assertNotIn("a" * 64, repr(lock))
        with self.assertRaises((AttributeError, TypeError)):
            cast(Any, lock).allowed_rule_atoms += (_READ,)
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
        self.assertTrue(_has_only_allowed_direct_imports(source))
        self.assertFalse(_has_only_allowed_direct_imports("import platform\n"))


if __name__ == "__main__":
    unittest.main()


def _has_only_allowed_direct_imports(source: str) -> bool:
    allowed = {
        (0, "__future__"),
        (0, "dataclasses"),
        (0, "hashlib"),
        (0, "json"),
        (0, "re"),
        (0, "typing"),
        (1, "image_input_lock"),
    }
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    imports = {
        (0, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.level, node.module or "")
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    return imports <= allowed
