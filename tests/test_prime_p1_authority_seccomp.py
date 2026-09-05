"""Focused tests for static Prime P1 seccomp resource admission."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    load_operator_config,
)
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)
from asterion.applications.prime_agent.operator.seccomp_policy_lock import (
    PromotedSeccompPolicyCatalog,
    SeccompArgumentConstraint,
    SeccompPolicyLock,
    SeccompRuleAtom,
)


_PROFILE = (
    b'{"architectures":["SCMP_ARCH_X86_64"],"defaultAction":"SCMP_ACT_ERRNO",'
    b'"syscalls":[{"action":"SCMP_ACT_ALLOW","args":[],"names":["read"]}]}'
)


def _policy() -> SeccompPolicyLock:
    return SeccompPolicyLock(
        schema_version="asterion.prime-p1-seccomp-policy-lock/v1",
        platform=ImagePlatformDescriptor("linux", "amd64", None),
        libseccomp_architecture="SCMP_ARCH_X86_64",
        image_config_digest="sha256:" + "a" * 64,
        build_input_sha256="b" * 64,
        launcher_sha256="c" * 64,
        workload_sha256="d" * 64,
        starter_sha256="e" * 64,
        oracle_sha256="f" * 64,
        default_action="SCMP_ACT_ERRNO",
        allowed_rule_atoms=(
            SeccompRuleAtom("read", ()),
            SeccompRuleAtom(
                "write", (SeccompArgumentConstraint(0, "SCMP_CMP_EQ", 0, None),)
            ),
        ),
        maximum_profile_sha256="0" * 64,
    )


class TestPrimeP1AuthoritySeccomp(unittest.TestCase):
    def _config(
        self,
        root: Path,
        profile: Path,
        *,
        image_config_digest: str = "sha256:" + "a" * 64,
        profile_bytes: bytes = _PROFILE,
    ) -> object:
        values = {
            "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
            "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
            "ASTERION_PRIME_P1_SECCOMP_PROFILE": str(profile),
            "ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256": hashlib.sha256(profile_bytes).hexdigest(),
            "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": image_config_digest,
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "linux",
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd64",
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "none",
            "ASTERION_PRIME_P1_MODEL_ID": "deepseek-chat",
            "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/lib/asterion/evidence",
            "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "p1-2026",
            "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
            "DEEPSEEK_API_KEY": "SECCOMP_SECRET_SENTINEL",
        }
        config_path = root / "operator.env"
        config_path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        config_path.chmod(0o600)
        return load_operator_config(os.open(config_path, os.O_RDONLY | os.O_CLOEXEC))

    def test_empty_catalog_fails_before_profile_filesystem_access(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            import asterion.applications.prime_agent.operator.authority_seccomp as module

            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(module.os, "open", side_effect=AssertionError("filesystem")) as opened,
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                admit_static_seccomp_resource(config)
        opened.assert_not_called()
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn("SECCOMP_SECRET_SENTINEL", str(raised.exception))

    def test_rejects_config_image_digest_before_profile_filesystem_access(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.authority_seccomp as module
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile, image_config_digest="sha256:" + "d" * 64)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
                patch.object(module.os, "open", side_effect=AssertionError("filesystem")) as opened,
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                admit_static_seccomp_resource(config)
        opened.assert_not_called()
        self.assertIsNone(raised.exception.__context__)

    def test_admits_exact_canonical_profile_and_revalidates(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            AdmittedPrimeP1SeccompResource,
            admit_static_seccomp_resource,
            revalidate_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
            ):
                resource = admit_static_seccomp_resource(config)
                self.assertIsInstance(resource, AdmittedPrimeP1SeccompResource)
                self.assertEqual(resource.sha256, hashlib.sha256(_PROFILE).hexdigest())
                self.assertEqual(repr(resource), "AdmittedPrimeP1SeccompResource(redacted)")
                revalidate_static_seccomp_resource(resource)
                owned_fds = resource._fds
                resource.close()
                resource.close()
                for fd in owned_fds:
                    with self.subTest(fd=fd):
                        with self.assertRaises(OSError):
                            os.fstat(fd)

    def test_rejects_noncanonical_or_non_promoted_profile_atoms(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        invalid = (
            _PROFILE + b" ",
            json.dumps(
                {
                    "architectures": ["SCMP_ARCH_X86_64"],
                    "defaultAction": "SCMP_ACT_ERRNO",
                    "syscalls": [
                        {"action": "SCMP_ACT_ALLOW", "args": [], "names": ["open"]}
                    ],
                }, separators=(",", ":"), sort_keys=True
            ).encode(),
            b'{"architectures":["SCMP_ARCH_X86_64"],"defaultAction":"SCMP_ACT_ERRNO",'
            b'"syscalls":[{"action":"SCMP_ACT_ALLOW","args":[],"names":["read"],"names":["read"]}]}',
        )
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
            ):
                for payload in invalid:
                    with self.subTest(payload=payload[:16]):
                        profile.write_bytes(payload)
                        profile.chmod(0o600)
                        config = self._config(root, profile, profile_bytes=payload)
                        with self.assertRaises(PrimeP1AuthorityResourceError) as raised:
                            admit_static_seccomp_resource(config)
                        self.assertIsNone(raised.exception.__context__)

    def test_revalidation_rejects_changed_bytes_and_closed_resource(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
            revalidate_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
            ):
                resource = admit_static_seccomp_resource(config)
                profile.write_bytes(_PROFILE + b" ")
                with self.assertRaises(PrimeP1AuthorityResourceError):
                    revalidate_static_seccomp_resource(resource)
                resource.close()
                with self.assertRaises(PrimeP1AuthorityResourceError):
                    revalidate_static_seccomp_resource(resource)

    def test_fifo_is_rejected_without_blocking(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.fifo"
            os.mkfifo(profile, 0o600)
            config = self._config(root, profile, profile_bytes=b"fifo")
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                admit_static_seccomp_resource(config)
        self.assertIsNone(raised.exception.__context__)

    def test_rejects_ancestor_changed_during_profile_validation(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.authority_seccomp as module
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            validate = module._validate_profile

            def mutate_ancestor(data: bytes, policy: object) -> None:
                validate(data, policy)  # type: ignore[arg-type]
                root.chmod(0o777)

            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
                patch.object(module, "_validate_profile", side_effect=mutate_ancestor),
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                admit_static_seccomp_resource(config)
        self.assertIsNone(raised.exception.__context__)

    def test_reader_retries_eintr_with_bound_and_resets_after_a_chunk(self) -> None:
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "profile"
            path.write_bytes(b"x")
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            identity = module._identity(fd)
            actual_read = os.read
            attempts = 0

            def interrupted_then_data(target_fd: int, count: int) -> bytes:
                nonlocal attempts
                attempts += 1
                if attempts <= 8:
                    raise InterruptedError
                return actual_read(target_fd, count)

            with patch.object(module.os, "read", side_effect=interrupted_then_data):
                data, digest = module._read_profile(fd, identity)
            self.assertEqual(data, b"x")
            self.assertEqual(digest, hashlib.sha256(b"x").hexdigest())
            os.close(fd)

            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            identity = module._identity(fd)
            calls = 0

            def reset_after_chunk(_: int, __: int) -> bytes:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise InterruptedError
                if calls == 2:
                    return b"x"
                if calls <= 10:
                    raise InterruptedError
                return b""

            with patch.object(module.os, "read", side_effect=reset_after_chunk):
                data, _ = module._read_profile(fd, identity)
            self.assertEqual(data, b"x")
            os.close(fd)

            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            identity = module._identity(fd)
            with patch.object(module.os, "read", side_effect=InterruptedError):
                with self.assertRaises(ValueError):
                    module._read_profile(fd, identity)
            os.close(fd)

    def test_lexically_oversized_paths_are_rejected_before_open(self) -> None:
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        for path in ("/" + ("a/" * 65) + "profile", "/" + "a" * 4097):
            with self.subTest(path_length=len(path)):
                with patch.object(module.os, "open") as opened:
                    with self.assertRaises(ValueError):
                        module._open_profile(path)
                opened.assert_not_called()

    def test_missing_root_cloexec_closes_opened_root_once(self) -> None:
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "profile"
            path.write_bytes(b"x")
            path.chmod(0o600)
            closed: list[int] = []
            actual_close = os.close

            def track_close(fd: int) -> None:
                closed.append(fd)
                actual_close(fd)

            fds = module._open_profile(str(path))
            with patch.object(module.fcntl, "fcntl", return_value=0):
                with patch.object(module.os, "close", side_effect=track_close):
                    with self.assertRaises(ValueError):
                        module._chain_identities(fds)
                    module._close_all(fds)
            self.assertEqual(closed, list(reversed(fds)))
            for fd in fds:
                with self.subTest(fd=fd):
                    with self.assertRaises(OSError):
                        os.fstat(fd)

    def test_missing_middle_or_leaf_cloexec_rejects_and_closes_reverse(self) -> None:
        import asterion.applications.prime_agent.operator.authority_seccomp as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            path = Path(temporary) / "profile"
            path.write_bytes(b"x")
            path.chmod(0o600)
            actual_fcntl = module.fcntl.fcntl
            for failure_index in (2,):
                fds = module._open_profile(str(path))
                closed: list[int] = []
                actual_close = os.close
                calls = 0

                def missing_cloexec(fd: int, operation: int) -> int:
                    nonlocal calls
                    calls += 1
                    if calls == failure_index:
                        return 0
                    return actual_fcntl(fd, operation)

                with (
                    self.subTest(failure_index=failure_index),
                    patch.object(module.fcntl, "fcntl", side_effect=missing_cloexec),
                    patch.object(
                        module.os,
                        "close",
                        side_effect=lambda fd: (closed.append(fd), actual_close(fd))[1],
                    ),
                ):
                    with self.assertRaises(ValueError):
                        module._chain_identities(fds)
                    module._close_all(fds)
                self.assertEqual(closed, list(reversed(fds)))

            fds = module._open_profile(str(path))
            closed = []
            actual_close = os.close
            calls = 0

            def missing_leaf(fd: int, operation: int) -> int:
                nonlocal calls
                calls += 1
                if calls == len(fds):
                    return 0
                return actual_fcntl(fd, operation)

            with (
                patch.object(module.fcntl, "fcntl", side_effect=missing_leaf),
                patch.object(
                    module.os,
                    "close",
                    side_effect=lambda fd: (closed.append(fd), actual_close(fd))[1],
                ),
            ):
                with self.assertRaises(ValueError):
                    module._chain_identities(fds)
                module._close_all(fds)
            self.assertEqual(closed, list(reversed(fds)))

    def test_post_open_validation_failure_closes_full_chain_without_transfer(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.authority_seccomp as module
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            closed: list[int] = []
            actual_close = os.close

            def track_close(fd: int) -> None:
                closed.append(fd)
                actual_close(fd)

            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(
                    catalog_module,
                    "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG",
                    PromotedSeccompPolicyCatalog((_policy(),)),
                ),
                patch.object(module, "_validate_profile", side_effect=RuntimeError("private")),
                patch.object(module.os, "close", side_effect=track_close),
                self.assertRaises(PrimeP1AuthorityResourceError) as raised,
            ):
                admit_static_seccomp_resource(config)
        self.assertIsNone(raised.exception.__context__)
        self.assertGreater(len(closed), 1)
        self.assertEqual(len(closed), len(set(closed)))
        for fd in closed:
            with self.subTest(fd=fd):
                with self.assertRaises(OSError):
                    os.fstat(fd)

    def test_revalidate_wins_over_concurrent_close_and_then_closes(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            admit_static_seccomp_resource,
            revalidate_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.authority_seccomp as module
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(catalog_module, "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG", PromotedSeccompPolicyCatalog((_policy(),))),
            ):
                resource = admit_static_seccomp_resource(config)
                entered, release = threading.Event(), threading.Event()
                closer_attempted, closer_completed = threading.Event(), threading.Event()
                validate = module._validate_profile

                class InstrumentedLock:
                    def __init__(self) -> None:
                        self._lock = threading.Lock()
                        self._acquires = 0

                    def __enter__(self) -> "InstrumentedLock":
                        self.acquire()
                        return self

                    def __exit__(self, *_: object) -> None:
                        self.release()

                    def acquire(self) -> None:
                        self._acquires += 1
                        if self._acquires == 2:
                            closer_attempted.set()
                        self._lock.acquire()

                    def release(self) -> None:
                        self._lock.release()

                object.__setattr__(resource, "_lock", InstrumentedLock())

                def parked(data: bytes, policy: object) -> None:
                    entered.set()
                    release.wait(2)
                    validate(data, policy)  # type: ignore[arg-type]

                with patch.object(module, "_validate_profile", side_effect=parked):
                    worker = threading.Thread(target=revalidate_static_seccomp_resource, args=(resource,))
                    worker.start()
                    self.assertTrue(entered.wait(1))
                    closer = threading.Thread(target=lambda: (resource.close(), closer_completed.set()))
                    closer.start()
                    try:
                        self.assertTrue(closer_attempted.wait(1))
                        self.assertFalse(closer_completed.is_set())
                        release.set()
                        worker.join(1)
                        closer.join(1)
                    finally:
                        release.set()
                self.assertFalse(worker.is_alive())
                self.assertFalse(closer.is_alive())
                self.assertTrue(closer_completed.is_set())
                for fd in resource._fds:
                    with self.assertRaises(OSError):
                        os.fstat(fd)

    def test_close_wins_and_revalidation_never_rewalks(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
            revalidate_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.authority_seccomp as module
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(catalog_module, "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG", PromotedSeccompPolicyCatalog((_policy(),))),
            ):
                resource = admit_static_seccomp_resource(config)
                completed = threading.Event()
                closer = threading.Thread(target=lambda: (resource.close(), completed.set()))
                closer.start()
                self.assertTrue(completed.wait(1))
                closer.join(1)
                with patch.object(module, "_open_profile", side_effect=AssertionError("rewalk")) as opened:
                    with self.assertRaises(PrimeP1AuthorityResourceError):
                        revalidate_static_seccomp_resource(resource)
                opened.assert_not_called()

    def test_revalidation_ancestor_mutation_closes_transient_chain_only(self) -> None:
        from asterion.applications.prime_agent.operator.authority_seccomp import (
            PrimeP1AuthorityResourceError,
            admit_static_seccomp_resource,
            revalidate_static_seccomp_resource,
        )
        import asterion.applications.prime_agent.operator.authority_seccomp as module
        import asterion.applications.prime_agent.operator.seccomp_policy_lock as catalog_module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary:
            root = Path(temporary)
            profile = root / "profile.json"
            profile.write_bytes(_PROFILE)
            profile.chmod(0o600)
            config = self._config(root, profile)
            with (
                patch.object(module.sys, "platform", "linux"),
                patch.object(catalog_module, "PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG", PromotedSeccompPolicyCatalog((_policy(),))),
            ):
                resource = admit_static_seccomp_resource(config)
                original = resource._fds
                rewalk: list[tuple[int, ...]] = []
                open_profile = module._open_profile
                validate = module._validate_profile
                actual_close = os.close
                closed: list[int] = []

                def capture(path: object) -> tuple[int, ...]:
                    fds = open_profile(path)
                    rewalk.append(fds)
                    return fds

                def mutate(data: bytes, policy: object) -> None:
                    validate(data, policy)  # type: ignore[arg-type]
                    root.chmod(0o777)

                with (
                    patch.object(module, "_open_profile", side_effect=capture),
                    patch.object(module, "_validate_profile", side_effect=mutate),
                    patch.object(module.os, "close", side_effect=lambda fd: (closed.append(fd), actual_close(fd))[1]),
                    self.assertRaises(PrimeP1AuthorityResourceError),
                ):
                    revalidate_static_seccomp_resource(resource)
                self.assertEqual(len(rewalk), 1)
                self.assertEqual(closed, list(reversed(rewalk[0])))
                for fd in original:
                    os.fstat(fd)
                resource.close()
                for fd in original:
                    with self.assertRaises(OSError):
                        os.fstat(fd)


if __name__ == "__main__":
    unittest.main()
