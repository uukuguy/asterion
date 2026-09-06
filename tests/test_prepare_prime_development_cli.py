"""Output-stream contract for the Prime preparation command."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


def _subject() -> object:
    path = Path(__file__).resolve().parents[1] / "tools" / "prepare_prime_development.py"
    spec = importlib.util.spec_from_file_location("prepare_prime_development_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError("tool is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPreparePrimeDevelopmentCli(unittest.TestCase):
    def test_status_stream_moves_public_preparation_result_off_stdout(self) -> None:
        subject = _subject()
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(subject, "prepare_prime_development", return_value={"p2": object()}),
            patch.object(sys, "argv", ["prepare", "--scenario", "p2", "--status-stream", "stderr"]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(subject.main(), 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "prime-p2 PASS\n")

    def test_default_status_stream_remains_stdout(self) -> None:
        subject = _subject()
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(subject, "prepare_prime_development", return_value={"p2": object()}),
            patch.object(sys, "argv", ["prepare", "--scenario", "p2"]),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(subject.main(), 0)
        self.assertEqual(stdout.getvalue(), "prime-p2 PASS\n")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
