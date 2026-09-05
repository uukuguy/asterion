"""Real child-process checks for the private Linux identity policy."""

import os
import signal
import sys
import unittest
from unittest import mock


@unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0, "requires Linux root")
class TestPrimeAuthorityLinuxPolicy(unittest.TestCase):
    def _child(self, *, wrong_parent: bool = False, fail_syscall: bool = False) -> int:
        from asterion.applications.prime_agent.operator import authority_linux_policy as policy

        prepared = policy.prepare_linux_identity_policy()
        parent = os.getpid()
        pid = os.fork()
        if pid == 0:
            try:
                signal.alarm(5)
                if fail_syscall:
                    with mock.patch.object(policy, "_prctl", side_effect=OSError("private sentinel")):
                        policy.apply_linux_identity_policy(
                            prepared, authority_uid=65534, authority_gid=65534,
                            expected_parent_pid=parent,
                        )
                else:
                    policy.apply_linux_identity_policy(
                        prepared, authority_uid=65534, authority_gid=65534,
                        expected_parent_pid=parent + int(wrong_parent),
                    )
                self.assertEqual(os.getresuid(), (65534,) * 3)
                self.assertEqual(os.getresgid(), (65534,) * 3)
                self.assertEqual(os.getgroups(), [])
                policy.verify_linux_identity_policy(
                    prepared,
                    authority_uid=65534, authority_gid=65534, expected_parent_pid=parent,
                )
                os._exit(0)
            except policy.AuthorityLinuxPolicyError as error:
                os._exit(20 if str(error) == "prime authority launch is unavailable" else 21)
            except BaseException:
                os._exit(22)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFEXITED(status))
        with self.assertRaises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
        return os.WEXITSTATUS(status)

    def test_actual_child_drops_and_verifies_identity(self) -> None:
        self.assertEqual(self._child(), 0)

    def test_wrong_expected_parent_fails_closed(self) -> None:
        self.assertEqual(self._child(wrong_parent=True), 20)

    def test_syscall_failure_is_redacted_and_child_reaped(self) -> None:
        self.assertEqual(self._child(fail_syscall=True), 20)

    def test_inherited_caught_and_ignored_signals_reset_before_unblocking(self) -> None:
        old_usr = signal.signal(signal.SIGUSR1, lambda *_: None)
        old_pipe = signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, (signal.SIGUSR1,))
        try:
            self.assertEqual(self._child(), 0)
        finally:
            signal.signal(signal.SIGUSR1, old_usr)
            signal.signal(signal.SIGPIPE, old_pipe)
            signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)

    def test_capability_range_beyond_abi_rejected_before_fork(self) -> None:
        from asterion.applications.prime_agent.operator import authority_linux_policy as policy

        with mock.patch("builtins.open", mock.mock_open(read_data="64\n")):
            with self.assertRaises(policy.AuthorityLinuxPolicyError):
                policy.prepare_linux_identity_policy()

    def test_snapshot_constructor_is_sealed(self) -> None:
        from asterion.applications.prime_agent.operator import authority_linux_policy as policy

        prepared = policy.prepare_linux_identity_policy()
        self.assertFalse(hasattr(prepared, "_token"))
        with self.assertRaises(policy.AuthorityLinuxPolicyError):
            policy.LinuxIdentityPolicy(
                prepared.cap_last_cap, prepared.reset_signals, prepared.prepare_pid,
                prepared._libc, object(),
            )


if __name__ == "__main__":
    unittest.main()
