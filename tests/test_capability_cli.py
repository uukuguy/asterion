from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from asterion.cli import _parser, main


PROJECT = Path(__file__).resolve().parents[1]
MINIMAL_PAYLOAD = PROJECT / "tests/fixtures/extensions/minimal/payload"


class CapabilityCliTests(unittest.TestCase):
    def test_help_lists_author_commands_and_staged_boundary_without_private_options(
        self,
    ) -> None:
        stream = io.StringIO()
        with self.assertRaises(SystemExit) as raised, redirect_stdout(stream):
            _parser().parse_args(["capability", "--help"])

        self.assertEqual(raised.exception.code, 0)
        help_text = stream.getvalue()
        for command in ("init", "validate", "inspect", "test", "pack", "convert"):
            self.assertIn(command, help_text)
            command_stream = io.StringIO()
            with (
                self.assertRaises(SystemExit) as command_exit,
                redirect_stdout(command_stream),
            ):
                _parser().parse_args(["capability", command, "--help"])
            self.assertEqual(command_exit.exception.code, 0)
            help_text += command_stream.getvalue()
        self.assertIn("archive-form approval", help_text)
        for forbidden in (
            "--source-root",
            "--provider",
            "--command",
            "--env",
            "--cost",
            "--budget",
            "--price",
        ):
            self.assertNotIn(forbidden, help_text)

    def test_validate_accepts_a_valid_portable_payload(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = main(
            ["capability", "validate", str(MINIMAL_PAYLOAD)],
            stdout=stdout,
            stderr=stderr,
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        result = json.loads(stdout.getvalue())
        self.assertEqual(
            set(result),
            {"package_id", "payload_sha256", "version"},
        )
        self.assertEqual(result["package_id"], "example.package")
        self.assertEqual(result["version"], "1.0.0")
        self.assertRegex(result["payload_sha256"], r"^[0-9a-f]{64}$")

    def test_invalid_payload_failure_redacts_private_paths_and_content(self) -> None:
        sentinel = "SECRET-PRIVATE-CAPABILITY-ROOT"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / sentinel
            shutil.copytree(MINIMAL_PAYLOAD, root)
            (root / "capability-package.json").write_text(
                '{"private":"SECRET-PRIVATE-CONTENT"}\n',
                encoding="utf-8",
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            code = main(
                ["capability", "validate", str(root)],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "asterion: command failed\n")
        self.assertNotIn(sentinel, stderr.getvalue())
        self.assertNotIn("SECRET-PRIVATE-CONTENT", stderr.getvalue())

    def test_inspect_emits_safe_identity_without_importing_provider(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(
            os.environ,
            {"ASTERION_TEST_FORBID_LOCAL_PROVIDER_IMPORT": "1"},
            clear=False,
        ):
            code = main(
                ["capability", "inspect", str(MINIMAL_PAYLOAD)],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        result = json.loads(stdout.getvalue())
        self.assertEqual(
            set(result),
            {
                "benchmark_suites",
                "capabilities",
                "package_id",
                "payload_sha256",
                "resources",
                "version",
            },
        )
        self.assertEqual(result["capabilities"], ["example.research@1.0.0"])
        self.assertEqual(
            result["benchmark_suites"],
            ["example.benchmark@1.0.0"],
        )
        self.assertEqual(
            result["resources"],
            [
                {
                    "resource_id": "example.public-config",
                    "sha256": (
                        "acc3e410bd74fb3717a1d4e8f8d47c2c"
                        "36c1181d05af98aa702f1be8732672c5"
                    ),
                }
            ],
        )
        rendered = stdout.getvalue()
        self.assertNotIn(str(MINIMAL_PAYLOAD), rendered)
        self.assertNotIn("provider", rendered)

    def test_init_copies_checked_in_template_and_test_runs_public_conformance(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve() / "SECRET-PRIVATE-AUTHOR-TARGET"
            init_stdout = io.StringIO()
            init_stderr = io.StringIO()

            init_code = main(
                ["capability", "init", str(target)],
                stdout=init_stdout,
                stderr=init_stderr,
            )

            self.assertEqual(init_code, 0)
            self.assertEqual(init_stderr.getvalue(), "")
            self.assertTrue((target / "payload/capability-package.json").is_file())
            self.assertTrue((target / "example/provider.py").is_file())
            init_result = json.loads(init_stdout.getvalue())
            self.assertEqual(init_result["package_id"], "example.package")
            self.assertNotIn(str(target), init_stdout.getvalue())

            test_stdout = io.StringIO()
            test_stderr = io.StringIO()
            with patch(
                "asterion.cli_capability.run_capability_conformance",
                wraps=__import__(
                    "asterion.capability_sdk",
                    fromlist=["run_capability_conformance"],
                ).run_capability_conformance,
            ) as conformance:
                test_code = main(
                    ["capability", "test", str(target)],
                    stdout=test_stdout,
                    stderr=test_stderr,
                )

            self.assertEqual(test_code, 0)
            self.assertEqual(test_stderr.getvalue(), "")
            conformance.assert_called_once()
            test_result = json.loads(test_stdout.getvalue())
            self.assertEqual(test_result["package_id"], "example.package")
            self.assertEqual(test_result["source_kind"], "local-directory")
            self.assertNotIn(str(target), test_stdout.getvalue())

    def test_pack_and_convert_validate_target_then_report_staged_boundary(
        self,
    ) -> None:
        for command in ("pack", "convert"):
            with self.subTest(command=command):
                stdout = io.StringIO()
                stderr = io.StringIO()

                code = main(
                    ["capability", command, "example.package@1.0.0"],
                    stdout=stdout,
                    stderr=stderr,
                )

                self.assertEqual(code, 2)
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(
                    stderr.getvalue(),
                    f"asterion: capability {command} is unsupported "
                    "pending archive-form approval\n",
                )

    def test_test_rejects_a_symlinked_local_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "source"
            linked = root / "SECRET-PRIVATE-SOURCE-LINK"
            self.assertEqual(
                main(
                    ["capability", "init", str(target)],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                ),
                0,
            )
            try:
                linked.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            stdout = io.StringIO()
            stderr = io.StringIO()

            code = main(
                ["capability", "test", str(linked)],
                stdout=stdout,
                stderr=stderr,
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "asterion: command failed\n")
        self.assertNotIn(linked.name, stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
