"""Syntax and identity tests for the private authority bundle contract."""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import tempfile
import copy
from pathlib import Path
import unittest
from unittest import mock
from dataclasses import replace

from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def _release_value() -> dict[str, object]:
    return {
        "format": "asterion.prime-p1-authority-bundle-release/v1",
        "release_version": "2.0.0",
        "target": {"os": "linux", "architecture": "arm64", "variant": None},
        "interpreter_path": "bin/python3",
        "files": [
            {
                "path": "bin/bootstrap",
                "role": "bootstrap",
                "mode": 0o555,
                "size": 1,
                "sha256": "a" * 64,
            },
            {
                "path": "bin/python3",
                "role": "interpreter",
                "mode": 0o555,
                "size": 1,
                "sha256": "b" * 64,
            },
        ],
        "launch_profile": {
            "profile_version": "1.0.0",
            "bootstrap_path": "bin/bootstrap",
            "argv": ["/proc/self/fd/7/bin/python3", "-I", "-S", "-B", "/proc/self/fd/9"],
            "python_flags": ["-I", "-S", "-B"],
            "python_path": ["bin"],
            "environment": {},
            "cwd_role": "runtime-directory",
            "umask": 63,
            "authority_uid": 1,
            "authority_gid": 2,
            "supplementary_gids": [],
            "capabilities": [],
            "no_new_privs": True,
            "rlimits": {
                "cpu_seconds": 120,
                "file_bytes": 16777216,
                "open_files": 256,
                "processes": 64,
                "address_space_bytes": 2147483648,
            },
            "inherited_fds": [
                {"fd": 3, "role": "config"}, {"fd": 4, "role": "session-key"},
                {"fd": 5, "role": "runtime-directory"}, {"fd": 6, "role": "launch-instance"},
                {"fd": 7, "role": "bundle-root"}, {"fd": 8, "role": "release-inventory"},
                {"fd": 9, "role": "bootstrap"},
            ],
            "socket": {"basename": "authority.sock", "runtime_dir_role": "runtime-directory", "type": "SOCK_SEQPACKET", "max_clients": 1, "peer_policy": "exact-supervisor-pid-uid"},
            "ipc_protocol": "asterion.prime-p1-authority-ipc/v2",
            "receipt_format": "asterion.prime-p1-authority-receipt/v2",
            "max_packet_bytes": 8192,
            "deadline_milliseconds": 60000,
            "external_runtime": [],
        },
    }


class TestPrimeAuthorityBundle(unittest.TestCase):
    def test_parse_canonical_release_freezes_records_and_declares_identity(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            declared_authority_runtime_identity,
            parse_authority_bundle_release,
        )

        value = _release_value()
        release = parse_authority_bundle_release(_canonical(value))
        self.assertEqual(release.target, ImagePlatformDescriptor("linux", "arm64", None))
        self.assertEqual(release.files[1].path, "bin/python3")
        with self.assertRaises((AttributeError, TypeError)):
            release.files += ()  # type: ignore[misc]

        identity = declared_authority_runtime_identity(release)
        self.assertEqual(identity.interpreter_executable_sha256, "b" * 64)
        bundle = {
            key: value[key]
            for key in ("release_version", "target", "interpreter_path", "files")
        }
        expected_bundle = hashlib.sha256(
            b"asterion.prime-p1-authority-bundle/v1\0" + _canonical(bundle)
        ).hexdigest()
        profile = dict(value["launch_profile"])
        profile.update(
            {
                "target": value["target"],
                "interpreter_executable_sha256": "b" * 64,
                "authority_bundle_sha256": expected_bundle,
            }
        )
        self.assertEqual(identity.authority_bundle_sha256, expected_bundle)
        self.assertEqual(
            identity.launch_profile_sha256,
            hashlib.sha256(
                b"asterion.prime-p1-authority-launch-profile/v1\0" + _canonical(profile)
            ).hexdigest(),
        )

    def test_parser_rejects_noncanonical_or_invalid_target_header(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            AuthorityBundleError,
            parse_authority_bundle_release,
        )

        value = _release_value()
        for raw in (
            _canonical(value) + b"\n",
            _canonical({**value, "target": {"os": "darwin", "architecture": "arm64", "variant": None}}),
        ):
            with self.subTest(raw=raw[:20]):
                with self.assertRaises(AuthorityBundleError):
                    parse_authority_bundle_release(raw)

    def test_parser_rejects_boolean_socket_limit(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            AuthorityBundleError,
            parse_authority_bundle_release,
        )

        value = _release_value()
        value["launch_profile"]["socket"]["max_clients"] = True  # type: ignore[index]
        with self.assertRaises(AuthorityBundleError):
            parse_authority_bundle_release(_canonical(value))

    def test_parser_rejects_non_native_inherited_fd_values(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            AuthorityBundleError,
            parse_authority_bundle_release,
        )

        for value in (3.0, True, "3"):
            with self.subTest(value=value):
                release = _release_value()
                release["launch_profile"]["inherited_fds"][0]["fd"] = value  # type: ignore[index]
                with self.assertRaises(AuthorityBundleError):
                    parse_authority_bundle_release(_canonical(release))

    def test_declared_identity_rejects_forged_typed_profile(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            AuthorityBundleError,
            declared_authority_runtime_identity,
            parse_authority_bundle_release,
        )

        release = parse_authority_bundle_release(_canonical(_release_value()))
        for forged in (
            replace(release, interpreter_path="bin/other"),
            replace(release, launch_profile=replace(release.launch_profile, umask=True)),
            replace(release, files=(release.files[1],)),
            replace(release, files=(replace(release.files[0], role="data"), release.files[1])),
        ):
            with self.subTest(forged=forged):
                with self.assertRaises(AuthorityBundleError):
                    declared_authority_runtime_identity(forged)

    def test_failed_admission_closes_each_input_descriptor(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            AuthorityBundleError,
            AuthorityRuntimeIdentityV2,
            admit_authority_bundle,
        )

        with tempfile.TemporaryFile() as root, tempfile.TemporaryFile() as inventory:
            root_fd, inventory_fd = os.dup(root.fileno()), os.dup(inventory.fileno())
            with self.assertRaises(AuthorityBundleError):
                admit_authority_bundle(
                    root_fd,
                    inventory_fd,
                    ImagePlatformDescriptor("linux", "arm64", None),
                    AuthorityRuntimeIdentityV2("a" * 64, "b" * 64, "c" * 64),
                )
            for fd in (root_fd, inventory_fd):
                with self.subTest(fd=fd), self.assertRaises(OSError):
                    os.fstat(fd)

    def test_duplicate_admission_descriptor_is_closed_once_and_redacted(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            AuthorityBundleError,
            AuthorityRuntimeIdentityV2,
            admit_authority_bundle,
        )

        with tempfile.TemporaryFile() as handle:
            fd = os.dup(handle.fileno())
            with self.assertRaisesRegex(AuthorityBundleError, "^prime authority bundle is unavailable$"):
                admit_authority_bundle(
                    fd, fd, ImagePlatformDescriptor("linux", "arm64", None),
                    AuthorityRuntimeIdentityV2("a" * 64, "b" * 64, "c" * 64),
                )
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_malformed_descriptor_never_closes_boolean_as_fd(self) -> None:
        from asterion.applications.prime_agent.operator import authority_bundle

        valid_fd = 999_999
        expected = authority_bundle.AuthorityRuntimeIdentityV2("a" * 64, "b" * 64, "c" * 64)
        with mock.patch.object(authority_bundle.os, "close") as close:
            with self.assertRaises(authority_bundle.AuthorityBundleError):
                authority_bundle.admit_authority_bundle(
                    True, valid_fd, ImagePlatformDescriptor("linux", "arm64", None), expected
                )
        close.assert_called_once_with(valid_fd)

    def test_opaque_bundle_denies_copy_and_pickle(self) -> None:
        from asterion.applications.prime_agent.operator.authority_bundle import AdmittedAuthorityBundle

        forged = object.__new__(AdmittedAuthorityBundle)
        with self.assertRaises(TypeError):
            copy.copy(forged)
        with self.assertRaises(TypeError):
            pickle.dumps(forged)

    def test_root_owned_linux_admission_revalidates_then_closes_descriptors(self) -> None:
        if os.name != "posix" or os.geteuid() != 0:
            self.skipTest("requires a root-owned Linux fixture")
        from asterion.applications.prime_agent.operator.authority_bundle import (
            AuthorityBundleError,
            admit_authority_bundle,
            declared_authority_runtime_identity,
            parse_authority_bundle_release,
        )

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            outer = Path(directory)
            root = outer / "bundle"
            (root / "bin").mkdir(parents=True, mode=0o755)
            interpreter = b"\x7fELF\x02\x01\x01" + (b"\0" * 11) + (183).to_bytes(2, "little")
            (root / "bin" / "python3").write_bytes(interpreter)
            (root / "bin" / "bootstrap").write_bytes(b"x")
            for path in (root / "bin" / "python3", root / "bin" / "bootstrap"):
                path.chmod(0o555)
            value = _release_value()
            value["files"][0]["sha256"] = hashlib.sha256(b"x").hexdigest()  # type: ignore[index]
            value["files"][1]["size"] = len(interpreter)  # type: ignore[index]
            value["files"][1]["sha256"] = hashlib.sha256(interpreter).hexdigest()  # type: ignore[index]
            raw = _canonical(value)
            inventory = outer / "inventory.json"
            inventory.write_bytes(raw)
            inventory.chmod(0o644)
            release = parse_authority_bundle_release(raw)
            expected = declared_authority_runtime_identity(release)
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            inventory_fd = os.open(inventory, os.O_RDONLY)
            os.set_inheritable(root_fd, True)
            os.set_inheritable(inventory_fd, True)
            bundle = admit_authority_bundle(root_fd, inventory_fd, release.target, expected)
            self.assertFalse(os.get_inheritable(bundle._root_fd))
            self.assertFalse(os.get_inheritable(bundle._inventory_fd))
            self.assertEqual(bundle._runtime_identity(), expected)
            bundle._revalidate_for_spawn()
            bundle.close()
            bundle.close()
            for fd in (root_fd, inventory_fd):
                with self.assertRaises(OSError):
                    os.fstat(fd)
            with self.assertRaises(AuthorityBundleError):
                bundle._revalidate_for_spawn()
