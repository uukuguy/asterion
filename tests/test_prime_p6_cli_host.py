from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


class TestP6CliHost(unittest.TestCase):
    def test_sets_the_finite_outer_deadline(self) -> None:
        from asterion.applications.prime_agent.operator.p6_cli_host import (
            P6_CLI_DEADLINE_SECONDS,
        )

        self.assertEqual(P6_CLI_DEADLINE_SECONDS, 300)

    def test_prepares_only_the_owned_p6_baseline(self) -> None:
        from asterion.applications.prime_agent.operator.p6_cli_host import (
            _prepare_workspace,
        )

        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with patch("os.chown") as chown:
                _prepare_workspace(workspace)
            self.assertEqual([path.name for path in workspace.iterdir()], ["baseline.py"])
            self.assertEqual(
                (workspace / "baseline.py").read_bytes(),
                b"def clamp(value, lower, upper):\n    return min(upper, value)\n",
            )
            self.assertEqual(chown.call_count, 2)
