"""P4 operator: env-driven commit→recover witness, prior_checkpoint_sha256 fix.

The operator is the sole bridge between the P4 native implementation and the
Makefile `asterion-prime-p4-run` supervisor. Two assertions anchor it:

* ``recover.prior_checkpoint_sha256`` MUST equal the prior's last sealed
  checkpoint digest (i.e. ``commit.checkpoint_sha256``). Earlier the field
  held ``prior_identity.continuation_id``; this test pins the correct shape.
* The SHA inequality that proves no-replay must still hold between the
  commit and recover rounds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import unittest


_OPERATOR_ROOT_ENV = "ASTERION_PRIME_OPERATOR_ROOT"
_PRIVATE_ROOT_ENV = "ASTERION_PRIME_P4_PRIVATE_ROOT"
_MODE_ENV = "ASTERION_PRIME_P4_MODE"


def _run_operator(
    *, operator_root: Path, private_root: Path, mode: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        _OPERATOR_ROOT_ENV: str(operator_root),
        _PRIVATE_ROOT_ENV: str(private_root),
        _MODE_ENV: mode,
        "LANG": "C.UTF-8",
    }
    return subprocess.run(
        [sys.executable, "-I", "-m", "asterion.applications.prime.p4.operator"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(operator_root),
    )


def _parse_stdout(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    line = completed.stdout.strip()
    assert line, (
        f"operator stdout empty; stderr={completed.stderr!r}, "
        f"rc={completed.returncode}"
    )
    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    return parsed


class P4OperatorEndToEnd(unittest.TestCase):
    """Run commit, then recover, against a fresh private_root; assert SHA wire."""

    def test_recover_prior_checkpoint_sha256_matches_commit_digest(self) -> None:
        operator_root = Path.cwd()
        with __import__("tempfile").TemporaryDirectory() as tmp:
            private_root = Path(tmp) / "prime-p4-test"

            commit_proc = _run_operator(
                operator_root=operator_root,
                private_root=private_root,
                mode="commit",
            )
            self.assertEqual(
                commit_proc.returncode,
                0,
                f"commit rc={commit_proc.returncode}; stderr={commit_proc.stderr!r}",
            )
            commit = _parse_stdout(commit_proc)
            self.assertEqual(commit["status"], "committed")
            self.assertIsNotNone(commit["checkpoint_sha256"])
            commit_digest = commit["checkpoint_sha256"]
            assert isinstance(commit_digest, str) and len(commit_digest) == 64

            recover_proc = _run_operator(
                operator_root=operator_root,
                private_root=private_root,
                mode="recover",
            )
            self.assertEqual(
                recover_proc.returncode,
                0,
                f"recover rc={recover_proc.returncode}; stderr={recover_proc.stderr!r}",
            )
            recover = _parse_stdout(recover_proc)
            self.assertEqual(recover["status"], "recovered")

            # The fix: prior_checkpoint_sha256 is the prior's last sealed
            # checkpoint digest (matches commit), NOT continuation_id.
            self.assertEqual(
                recover["prior_checkpoint_sha256"],
                commit_digest,
                "recover.prior_checkpoint_sha256 must equal commit.checkpoint_sha256",
            )
            self.assertNotEqual(
                recover["prior_checkpoint_sha256"],
                recover["continuation_id"],
                "regression guard: prior_checkpoint_sha256 must not be continuation_id",
            )

            # Continuity invariants remain intact.
            commit_generation = commit["generation"]
            assert isinstance(commit_generation, int)
            self.assertEqual(recover["new_generation"], commit_generation + 1)
            self.assertEqual(recover["continuation_id"], commit["continuation_id"])
            self.assertNotEqual(recover["result_sha256"], commit["result_sha256"])
            self.assertNotEqual(
                recover["worker_identity_sha256"],
                commit["worker_identity_sha256"],
            )


if __name__ == "__main__":
    unittest.main()