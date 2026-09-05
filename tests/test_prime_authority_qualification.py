from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path("/tmp/asterion-authority-candidate-9hpk1mgz")
INVENTORY = Path("/tmp/asterion-authority-candidate-9hpk1mgz.release.json")


class TestAuthorityQualification(unittest.TestCase):
    def test_launch_handoff_failure_does_not_reclose_input_descriptors(self) -> None:
        from asterion.applications.prime_agent.operator import authority_qualification

        class Bundle:
            def __init__(self) -> None:
                self.closed = False

            def _runtime_identity(self) -> object:
                return object()

            def close(self) -> None:
                self.closed = True

        bundle = Bundle()
        inputs = (40, 41, 42, 43)
        with (
            mock.patch.object(
                authority_qualification,
                "_validate_instance",
                return_value={"runtime_identity": {}},
            ),
            mock.patch.object(
                authority_qualification, "_same_identity", return_value=True
            ),
            mock.patch.object(
                authority_qualification.os, "pread", return_value=b"k" * 32
            ),
            mock.patch.object(authority_qualification.os, "dup", side_effect=(50, 51)),
            mock.patch.object(
                authority_qualification,
                "launch_authority_child",
                side_effect=ValueError,
            ),
            mock.patch.object(authority_qualification.os, "close") as close,
        ):
            with self.assertRaises(authority_qualification.AuthorityQualificationError):
                authority_qualification.run_authority_qualification(
                    bundle,
                    config_fd=inputs[0],
                    session_key_fd=inputs[1],
                    runtime_directory_fd=inputs[2],
                    launch_instance_fd=inputs[3],
                )

        self.assertFalse(bundle.closed)
        self.assertEqual({call.args[0] for call in close.call_args_list}, {50, 51})

    def test_real_completed_exchange(self) -> None:
        if os.geteuid() != 0 or not ROOT.is_dir():
            self.skipTest("requires Linux root candidate")
        from asterion.applications.prime_agent.operator.authority_bundle import (
            admit_authority_bundle,
            declared_authority_runtime_identity,
            parse_authority_bundle_release,
        )
        from asterion.applications.prime_agent.operator.authority_qualification import (
            run_authority_qualification,
        )

        with tempfile.TemporaryDirectory(dir="/root") as temporary:
            base = Path(temporary)
            root = base / "bundle"
            shutil.copytree(ROOT, root, copy_function=shutil.copy2)
            release = json.loads(INVENTORY.read_text())
            bootstrap = root / release["launch_profile"]["bootstrap_path"]
            entry = (
                Path(__file__).parents[1]
                / "src/asterion/applications/prime_agent/operator/authority_qualification_entry.py"
            ).read_bytes()
            bootstrap.write_bytes(entry)
            os.chmod(bootstrap, 0o444)
            record = next(
                item
                for item in release["files"]
                if item["path"] == release["launch_profile"]["bootstrap_path"]
            )
            record.update(
                size=len(entry), sha256=hashlib.sha256(entry).hexdigest(), mode=0o444
            )
            inventory = base / "release.json"
            inventory.write_bytes(
                json.dumps(release, sort_keys=True, separators=(",", ":")).encode()
            )
            os.chmod(inventory, 0o444)
            parsed = parse_authority_bundle_release(inventory.read_bytes())
            runtime = base / "runtime"
            runtime.mkdir(mode=0o700)
            os.chown(
                runtime,
                parsed.launch_profile.authority_uid,
                parsed.launch_profile.authority_gid,
            )
            instance = {
                "format": "asterion.prime-p1-authority-launch-instance/v2",
                "purpose": "qualification",
                "run_id": "run-1",
                "session_id": "d" * 64,
                "supervisor_pid": os.getpid(),
                "supervisor_uid": os.geteuid(),
                "runtime_identity": {
                    "interpreter_executable_sha256": declared_authority_runtime_identity(
                        parsed
                    ).interpreter_executable_sha256,
                    "authority_bundle_sha256": declared_authority_runtime_identity(
                        parsed
                    ).authority_bundle_sha256,
                    "launch_profile_sha256": declared_authority_runtime_identity(
                        parsed
                    ).launch_profile_sha256,
                },
                "request_contract_sha256": "a" * 64,
                "resource_set_sha256": "b" * 64,
                "application_request_sha256": "c" * 64,
                "workload_id": "bounded-ipc-qualification-v1",
            }
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            inventory_fd = os.open(inventory, os.O_RDONLY)
            bundle = admit_authority_bundle(
                root_fd,
                inventory_fd,
                parsed.target,
                declared_authority_runtime_identity(parsed),
            )
            config, key, instance_fd = (
                _sealed(value)
                for value in (
                    b"{}",
                    b"k" * 32,
                    json.dumps(
                        instance, sort_keys=True, separators=(",", ":")
                    ).encode(),
                )
            )
            runtime_fd = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY)
            self.assertEqual(
                run_authority_qualification(
                    bundle,
                    config_fd=config,
                    session_key_fd=key,
                    runtime_directory_fd=runtime_fd,
                    launch_instance_fd=instance_fd,
                ),
                "qualification completed",
            )

    def test_real_cancelled_exchange(self) -> None:
        if os.geteuid() != 0 or not ROOT.is_dir():
            self.skipTest("requires Linux root candidate")
        self.assertEqual(self._run(cancel=True), "qualification cancelled")

    def test_rejects_instance_with_bundle_identity_mismatch(self) -> None:
        if os.geteuid() != 0 or not ROOT.is_dir():
            self.skipTest("requires Linux root candidate")
        from asterion.applications.prime_agent.operator.authority_qualification import (
            AuthorityQualificationError,
        )

        with self.assertRaises(AuthorityQualificationError):
            self._run(identity_override="0" * 64)

    def _run(
        self, *, cancel: bool = False, identity_override: str | None = None
    ) -> str:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            admit_authority_bundle,
            declared_authority_runtime_identity,
            parse_authority_bundle_release,
        )
        from asterion.applications.prime_agent.operator.authority_qualification import (
            run_authority_qualification,
        )

        with tempfile.TemporaryDirectory(dir="/root") as temporary:
            base = Path(temporary)
            root = base / "bundle"
            shutil.copytree(ROOT, root, copy_function=shutil.copy2)
            release = json.loads(INVENTORY.read_text())
            bootstrap = root / release["launch_profile"]["bootstrap_path"]
            entry = (
                Path(__file__).parents[1]
                / "src/asterion/applications/prime_agent/operator/authority_qualification_entry.py"
            ).read_bytes()
            bootstrap.write_bytes(entry)
            os.chmod(bootstrap, 0o444)
            record = next(
                item
                for item in release["files"]
                if item["path"] == release["launch_profile"]["bootstrap_path"]
            )
            record.update(
                size=len(entry), sha256=hashlib.sha256(entry).hexdigest(), mode=0o444
            )
            inventory = base / "release.json"
            inventory.write_bytes(
                json.dumps(release, sort_keys=True, separators=(",", ":")).encode()
            )
            os.chmod(inventory, 0o444)
            parsed = parse_authority_bundle_release(inventory.read_bytes())
            runtime = base / "runtime"
            runtime.mkdir(mode=0o700)
            os.chown(
                runtime,
                parsed.launch_profile.authority_uid,
                parsed.launch_profile.authority_gid,
            )
            identity = declared_authority_runtime_identity(parsed)
            instance = {
                "format": "asterion.prime-p1-authority-launch-instance/v2",
                "purpose": "qualification",
                "run_id": "run-1",
                "session_id": "d" * 64,
                "supervisor_pid": os.getpid(),
                "supervisor_uid": os.geteuid(),
                "runtime_identity": {
                    "interpreter_executable_sha256": identity_override
                    or identity.interpreter_executable_sha256,
                    "authority_bundle_sha256": identity.authority_bundle_sha256,
                    "launch_profile_sha256": identity.launch_profile_sha256,
                },
                "request_contract_sha256": "a" * 64,
                "resource_set_sha256": "b" * 64,
                "application_request_sha256": "c" * 64,
                "workload_id": "bounded-ipc-qualification-v1",
            }
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            inventory_fd = os.open(inventory, os.O_RDONLY)
            bundle = admit_authority_bundle(
                root_fd, inventory_fd, parsed.target, identity
            )
            config, key, instance_fd = (
                _sealed(value)
                for value in (
                    b"{}",
                    b"k" * 32,
                    json.dumps(
                        instance, sort_keys=True, separators=(",", ":")
                    ).encode(),
                )
            )
            runtime_fd = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY)
            return run_authority_qualification(
                bundle,
                config_fd=config,
                session_key_fd=key,
                runtime_directory_fd=runtime_fd,
                launch_instance_fd=instance_fd,
                cancel=cancel,
            )


def _sealed(value: bytes) -> int:
    fd = os.memfd_create("q", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    os.write(fd, value)
    fcntl.fcntl(
        fd,
        fcntl.F_ADD_SEALS,
        fcntl.F_SEAL_WRITE
        | fcntl.F_SEAL_GROW
        | fcntl.F_SEAL_SHRINK
        | fcntl.F_SEAL_SEAL,
    )
    return fd
