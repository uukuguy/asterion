"""Development-only persistent-IPython worker checks for P1-B."""

from __future__ import annotations

import io
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from asterion.applications.prime_agent.operator.image import p1b_launcher


_IDENTITY = {"run_id": "p1b-test-run", "session_id": "p1b-test-session"}


def _frame(sequence: int, kind: str, **values: object) -> str:
    return json.dumps(
        {
            "identity": _IDENTITY,
            "kind": kind,
            "protocol": p1b_launcher.PROTOCOL,
            "sequence": sequence,
            **values,
        },
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"


class _TamperingInput(io.StringIO):
    def __init__(self, frames: str) -> None:
        super().__init__(frames)
        self._reads = 0

    def readline(self, size: int = -1) -> str:
        self._reads += 1
        if self._reads == 2:
            from IPython.core.interactiveshell import InteractiveShell

            InteractiveShell.instance().user_ns["p1b_value"] = 0
        return super().readline(size)


class _InitialWorkspaceWitness(io.StringIO):
    def __init__(self, frames: str, workspace: Path) -> None:
        super().__init__(frames)
        self._workspace = workspace
        self._read = False

    def readline(self, size: int = -1) -> str:
        if not self._read:
            self._read = True
            if self._workspace.joinpath("p1b-state").exists() or self._workspace.joinpath(
                "p1b-state", "continuity.txt"
            ).exists():
                raise AssertionError("worker prepared cell-owned state before cell1")
        return super().readline(size)


_BASELINE_CELL = """\
from pathlib import Path as P1BPath
p1b_value = 41
def p1b_answer():
    return 42
import os
P1BPath("p1b-state").mkdir()
os.chdir(P1BPath.cwd() / "p1b-state")
P1BPath("continuity.txt").write_bytes(b"p1b continuity fixture\\n")
assert P1BPath("continuity.txt").read_bytes() == b"p1b continuity fixture\\n"
"""


@unittest.skipUnless(importlib.util.find_spec("IPython"), "requires the image's IPython dependency")
class TestPrimeP1BLauncher(unittest.TestCase):
    def _run(
        self, workspace: Path, frames: io.StringIO
    ) -> tuple[int, list[dict[str, object]]]:
        output = io.StringIO()
        status = p1b_launcher.run_development_worker(
            workspace=workspace,
            stdin=frames,
            stdout=output,
        )
        return status, [json.loads(line) for line in output.getvalue().splitlines()]

    def test_two_cells_preserve_one_kernel_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            status, messages = self._run(
                workspace,
                _InitialWorkspaceWitness(
                    _frame(1, "cell.execute", cell=_BASELINE_CELL)
                    + _frame(2, "cell.execute", cell="assert p1b_answer() == 42")
                    + _frame(3, "finish"),
                    workspace,
                ),
            )

        self.assertEqual(status, 0)
        self.assertEqual(messages[0]["kind"], "baseline.recorded")
        self.assertEqual(messages[0]["baseline_recorded"], True)
        self.assertEqual(messages[0]["kernel_generation"], 1)
        self.assertEqual(messages[1]["kind"], "continuity.verified")
        self.assertEqual(
            messages[1]["preserved"],
            {
                "cwd": True,
                "file_bytes": True,
                "function_behavior": True,
                "function_identity": True,
                "namespace_value": True,
                "path_alias": True,
            },
        )
        self.assertEqual(messages[2]["kind"], "completed")

    def test_tampering_after_first_cell_fails_before_second_cell_and_redacts_sentinel(self) -> None:
        sentinel = "P1B_PRIVATE_SENTINEL_DO_NOT_LEAK"
        with tempfile.TemporaryDirectory() as temporary:
            status, messages = self._run(
                Path(temporary),
                _TamperingInput(
                    _frame(1, "cell.execute", cell=_BASELINE_CELL)
                    + _frame(2, "cell.execute", cell=f"raise AssertionError({sentinel!r})")
                ),
            )

        serialized = json.dumps(messages, separators=(",", ":"), sort_keys=True)
        self.assertEqual(status, 1)
        self.assertEqual([message["kind"] for message in messages], ["baseline.recorded", "failed"])
        self.assertNotIn(sentinel, serialized)
