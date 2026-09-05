"""Actual Linux-root smoke tests for private authority fd-exec launch."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
import unittest
import pickle
import signal
from unittest import mock


_CANDIDATE_ROOT = Path("/tmp/asterion-authority-candidate-9hpk1mgz")
_CANDIDATE_INVENTORY = Path("/tmp/asterion-authority-candidate-9hpk1mgz.release.json")


class TestPrimeAuthorityLinuxLaunch(unittest.TestCase):
    def test_echild_ownership_loss_never_signals(self) -> None:
        from asterion.applications.prime_agent.operator import authority_linux_launch

        child = authority_linux_launch.AuthorityLinuxChild(
            12345, 65534, time.monotonic(),
            _token=authority_linux_launch._CHILD_TOKEN,
        )
        with (
            mock.patch.object(authority_linux_launch, "_owned_child", return_value=False),
            mock.patch.object(authority_linux_launch.os, "killpg") as killpg,
            mock.patch.object(authority_linux_launch.os, "kill") as kill,
        ):
            child.cancel()
            authority_linux_launch._terminate_reap(12345)
        killpg.assert_not_called()
        kill.assert_not_called()

    def test_launch_restores_manager_sigchld_to_default_reaping(self) -> None:
        previous = signal.signal(signal.SIGCHLD, signal.SIG_IGN)
        try:
            with _AuthorityCandidateFixture(self) as fixture:
                fixture.replace_bootstrap(b"import time\ntime.sleep(30)\n")
                child, _ = fixture.launch()
                self.assertIs(signal.getsignal(signal.SIGCHLD), signal.SIG_DFL)
                child.cancel()
                self.assertEqual(child.wait(), "cancelled")
        finally:
            signal.signal(signal.SIGCHLD, previous)

    def test_invalid_input_fd_ownership_closes_each_numeric_fd_once(self) -> None:
        from asterion.applications.prime_agent.operator import authority_linux_launch
        from asterion.applications.prime_agent.operator.authority_linux_launch import (
            AuthorityLinuxLaunchError,
        )

        closed: list[int] = []
        original_close = authority_linux_launch.os.close

        def record_close(fd: int) -> None:
            closed.append(fd)
            original_close(fd)

        for duplicate, boolean in ((True, False), (False, True)):
            with self.subTest(duplicate=duplicate, boolean=boolean):
                first, second, third = (
                    os.open("/dev/null", os.O_RDONLY) for _ in range(3)
                )
                config = True if boolean else (first if duplicate else first)
                key = first if duplicate else first
                closed.clear()
                with mock.patch.object(authority_linux_launch.os, "close", side_effect=record_close):
                    with self.assertRaises(AuthorityLinuxLaunchError):
                        authority_linux_launch.launch_authority_child(
                            object(),
                            config_fd=config,
                            session_key_fd=key,
                            runtime_directory_fd=second,
                            launch_instance_fd=third,
                        )
                self.assertEqual(closed, [first, second, third])
                self.assertNotIn(1, closed)

    def test_child_owner_constructor_is_private_and_exact_type(self) -> None:
        from asterion.applications.prime_agent.operator.authority_linux_launch import (
            AuthorityLinuxChild,
            AuthorityLinuxLaunchError,
        )

        class ForgedChild(AuthorityLinuxChild):
            pass

        for constructor in (AuthorityLinuxChild, ForgedChild):
            with self.subTest(constructor=constructor):
                with self.assertRaises(AuthorityLinuxLaunchError):
                    constructor(1, 1, time.monotonic())

    def test_live_child_owner_denies_copy_and_pickle(self) -> None:
        with _AuthorityCandidateFixture(self) as fixture:
            fixture.replace_bootstrap(b"import time\ntime.sleep(30)\n")
            child, _ = fixture.launch()
            try:
                for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                    with self.subTest(operation=operation):
                        with self.assertRaises(TypeError):
                            operation(child)
            finally:
                child.close()

    def test_real_candidate_fd_exec_exits_and_reaps(self) -> None:
        with _AuthorityCandidateFixture(self) as fixture:
            child, fds = fixture.launch()
            self.assertEqual(child.wait(), "exited")
            _assert_closed(self, fds)
            _assert_reaped(self, child)

    def test_real_exec_failure_rejects_and_reaps_child(self) -> None:
        from asterion.applications.prime_agent.operator.authority_linux_launch import AuthorityLinuxLaunchError

        with _AuthorityCandidateFixture(self) as fixture:
            fixture.break_interpreter_loader()
            with self.assertRaises(AuthorityLinuxLaunchError):
                fixture.launch()
            _assert_closed(self, fixture.last_launch_fds)

    def test_immediate_cancel_reaps_real_authority_child(self) -> None:
        with _AuthorityCandidateFixture(self) as fixture:
            fixture.replace_bootstrap(b"import time\ntime.sleep(30)\n")
            child, fds = fixture.launch()
            child.cancel()
            self.assertEqual(child.wait(deadline=time.monotonic() + 2), "cancelled")
            _assert_closed(self, fds)
            _assert_reaped(self, child)

    def test_cancel_precedes_an_already_elapsed_wait_deadline(self) -> None:
        with _AuthorityCandidateFixture(self) as fixture:
            fixture.replace_bootstrap(b"import time\ntime.sleep(30)\n")
            child, _ = fixture.launch()
            child.cancel()
            self.assertEqual(child.wait(deadline=time.monotonic() - 1), "cancelled")

    def test_close_preserves_cancelled_terminal_status(self) -> None:
        with _AuthorityCandidateFixture(self) as fixture:
            fixture.replace_bootstrap(b"import time\ntime.sleep(30)\n")
            child, _ = fixture.launch()
            child.close()
            self.assertEqual(child.wait(), "cancelled")

    def test_unknown_inheritable_fd_is_not_present_after_fd_exec(self) -> None:
        with _AuthorityCandidateFixture(self) as fixture:
            fixture.replace_bootstrap(
                b"import os\n"
                b"observed=','.join(os.listdir('/proc/self/fd'))\n"
                b"fd=os.open('observed-fds',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)\n"
                b"os.write(fd,observed.encode())\n"
                b"os.close(fd)\n"
            )
            source = os.open("/dev/null", os.O_RDONLY)
            unknown_fd = fcntl.fcntl(source, fcntl.F_DUPFD, 50)
            os.close(source)
            os.set_inheritable(unknown_fd, True)
            self.addCleanup(_close_quietly, unknown_fd)
            child, _ = fixture.launch()
            self.assertEqual(child.wait(), "exited")
            observed = (fixture.runtime / "observed-fds").read_text().split(",")
            self.assertEqual(set(observed), {str(fd) for fd in range(0, 11)})
            os.fstat(unknown_fd)

    def test_partial_staging_failure_closes_transferred_descriptors(self) -> None:
        from asterion.applications.prime_agent.operator import authority_linux_launch
        from asterion.applications.prime_agent.operator.authority_linux_launch import AuthorityLinuxLaunchError

        with _AuthorityCandidateFixture(self) as fixture:
            before = _fd_count()
            original = authority_linux_launch.fcntl.fcntl
            stages = 0

            def fail_second_stage(fd: int, command: int, argument: int = 0) -> int:
                nonlocal stages
                if command == fcntl.F_DUPFD_CLOEXEC:
                    stages += 1
                    if stages == 2:
                        raise OSError("staging failure")
                return original(fd, command, argument)

            with mock.patch.object(authority_linux_launch.fcntl, "fcntl", side_effect=fail_second_stage):
                with self.assertRaises(AuthorityLinuxLaunchError):
                    fixture.launch()
            _assert_closed(self, fixture.last_launch_fds)
            self.assertEqual(_fd_count(), before)

    def test_fork_and_handshake_failures_reap_and_close(self) -> None:
        from asterion.applications.prime_agent.operator import authority_linux_launch
        from asterion.applications.prime_agent.operator.authority_linux_launch import AuthorityLinuxLaunchError

        for name, target, side_effect in (
            ("fork", "fork", OSError("fork failure")),
            ("select", "select", OSError("handshake failure")),
        ):
            with self.subTest(name=name), _AuthorityCandidateFixture(self) as fixture:
                before = _fd_count()
                module = authority_linux_launch.os if target == "fork" else authority_linux_launch.select
                with mock.patch.object(module, target, side_effect=side_effect):
                    with self.assertRaises(AuthorityLinuxLaunchError):
                        fixture.launch()
                _assert_closed(self, fixture.last_launch_fds)
                self.assertEqual(_fd_count(), before)


class _AuthorityCandidateFixture:
    """Private copy of the supplied immutable candidate with a fresh inventory."""

    def __init__(self, case: unittest.TestCase) -> None:
        self._case = case
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.root: Path
        self.inventory: Path
        self.runtime: Path
        self._release: dict[str, object]

    def __enter__(self) -> "_AuthorityCandidateFixture":
        if os.name != "posix" or os.geteuid() != 0 or not _CANDIDATE_ROOT.is_dir() or not _CANDIDATE_INVENTORY.is_file():
            self._case.skipTest("requires the OrbStack Linux root authority candidate")
        self._temporary = tempfile.TemporaryDirectory(dir="/root")
        temporary = Path(self._temporary.name)
        self.root = temporary / "bundle"
        shutil.copytree(_CANDIDATE_ROOT, self.root, copy_function=shutil.copy2)
        self.inventory = temporary / "bundle.release.json"
        self._release = json.loads(_CANDIDATE_INVENTORY.read_text())
        self.runtime = temporary / "runtime"
        self.runtime.mkdir(mode=0o700)
        profile = self._release["launch_profile"]
        assert type(profile) is dict
        os.chown(self.runtime, profile["authority_uid"], profile["authority_gid"])
        self._write_inventory()
        return self

    def __exit__(self, *_: object) -> None:
        assert self._temporary is not None
        self._temporary.cleanup()

    def replace_bootstrap(self, data: bytes) -> None:
        profile = self._release["launch_profile"]
        assert type(profile) is dict and type(profile["bootstrap_path"]) is str
        path = self.root / profile["bootstrap_path"]
        path.write_bytes(data)
        os.chmod(path, 0o444)
        self._replace_file_record(path.relative_to(self.root))
        self._write_inventory()

    def break_interpreter_loader(self) -> None:
        path = self.root / "bin/python3"
        data = bytearray(path.read_bytes())
        interpreter = _elf_interpreter_offset(data)
        data[interpreter] = ord("x") if data[interpreter] != ord("x") else ord("y")
        path.write_bytes(data)
        os.chmod(path, 0o555)
        self._replace_file_record(Path("bin/python3"))
        self._write_inventory()

    def launch(self) -> tuple[object, tuple[int, ...]]:
        from asterion.applications.prime_agent.operator.authority_bundle import (
            admit_authority_bundle,
            declared_authority_runtime_identity,
            parse_authority_bundle_release,
        )
        from asterion.applications.prime_agent.operator.authority_linux_launch import launch_authority_child

        raw = self.inventory.read_bytes()
        release = parse_authority_bundle_release(raw)
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        inventory_fd = os.open(self.inventory, os.O_RDONLY)
        bundle = admit_authority_bundle(root_fd, inventory_fd, release.target, declared_authority_runtime_identity(release))
        runtime_fd = os.open(self.runtime, os.O_RDONLY | os.O_DIRECTORY)
        inputs = tuple(_sealed_memfd(value) for value in (b"{}", b"k" * 32, b"instance"))
        self.last_launch_fds = (*inputs, runtime_fd)
        try:
            child = launch_authority_child(bundle, config_fd=inputs[0], session_key_fd=inputs[1], runtime_directory_fd=runtime_fd, launch_instance_fd=inputs[2])
        except BaseException:
            bundle.close()
            for fd in (*inputs, runtime_fd):
                _close_quietly(fd)
            raise
        return child, (*inputs, runtime_fd)

    def _replace_file_record(self, relative: Path) -> None:
        files = self._release["files"]
        assert type(files) is list
        path = self.root / relative
        record = next(item for item in files if item["path"] == relative.as_posix())
        record["size"] = path.stat().st_size
        record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        record["mode"] = path.stat().st_mode & 0o777

    def _write_inventory(self) -> None:
        self.inventory.write_bytes(json.dumps(self._release, sort_keys=True, separators=(",", ":")).encode())
        os.chmod(self.inventory, 0o444)


def _elf_interpreter_offset(data: bytearray) -> int:
    if data[:5] != b"\x7fELF\x02" or data[5] != 1:
        raise AssertionError("candidate interpreter is not a 64-bit little-endian ELF")
    program_offset = struct.unpack_from("<Q", data, 32)[0]
    entry_size, count = struct.unpack_from("<HH", data, 54)
    for index in range(count):
        offset = program_offset + index * entry_size
        if struct.unpack_from("<I", data, offset)[0] == 3:
            return struct.unpack_from("<Q", data, offset + 8)[0]
    raise AssertionError("candidate interpreter has no ELF loader entry")


def _sealed_memfd(data: bytes) -> int:
    fd = os.memfd_create("authority-test", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    os.write(fd, data)
    fcntl.fcntl(fd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
    return fd


def _assert_closed(case: unittest.TestCase, fds: tuple[int, ...]) -> None:
    for fd in fds:
        with case.assertRaises(OSError):
            os.fstat(fd)


def _assert_reaped(case: unittest.TestCase, child: object) -> None:
    pid = child._process_identity()[0]  # type: ignore[attr-defined]
    with case.assertRaises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


def _fd_count() -> int:
    return len(os.listdir("/proc/self/fd"))
