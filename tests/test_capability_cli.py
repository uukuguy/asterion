from __future__ import annotations

import io
import hashlib
import json
import os
import py_compile
import shutil
import tempfile
import unittest
from importlib import resources
from pathlib import Path
from unittest.mock import patch

from asterion.cli import main
from asterion.capability_packages.payload import open_portable_payload


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "extensions" / "minimal"
PACKAGE = "example.package@1.0.0"
SOURCE_ID = "example.package.local-directory"


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        code = main(argv, stdout=stdout, stderr=stderr)
    except SystemExit as error:
        code = error.code if isinstance(error.code, int) else 1
    return code, stdout.getvalue(), stderr.getvalue()


def copy_fixture(target: Path) -> Path:
    target = target.parent.resolve() / target.name
    root = target / "minimal"
    shutil.copytree(FIXTURE_ROOT, root)
    return root


def local_args(root: Path) -> list[str]:
    return local_args_for(root, package=PACKAGE, source_id=SOURCE_ID)


def local_args_for(root: Path, *, package: str, source_id: str) -> list[str]:
    payload_sha256 = open_portable_payload(root / "payload").payload_sha256
    return [
        "--package",
        package,
        "--source-id",
        source_id,
        "--root",
        str(root),
        "--payload-root",
        "payload",
        "--module-path",
        "provider.py",
        "--factory-name",
        "create_package",
        "--payload-sha256",
        payload_sha256,
    ]


class CapabilityCliTests(unittest.TestCase):
    def test_help_lists_author_commands_without_provider_or_cost_options(self) -> None:
        code, stdout, stderr = run_cli(["capability", "--help"])

        self.assertEqual(code, 0, stderr)
        for command in ("init", "validate", "inspect", "test", "pack", "convert"):
            self.assertIn(command, stdout)
        self.assertIn("pack and convert are staged", stdout)
        self.assertNotIn("--provider", stdout)
        self.assertNotIn("cost", stdout.lower())
        self.assertNotIn("registry", stdout.lower())
        self.assertNotIn("token", stdout.lower())

    def test_template_provider_uses_public_sdk_only(self) -> None:
        provider = (
            Path(str(resources.files("asterion.capability_sdk")))
            / "templates/minimal/provider.py"
        )
        text = provider.read_text(encoding="utf-8")

        self.assertIn("from asterion.capability_sdk import", text)
        self.assertNotIn("asterion.capability_packages.payload", text)
        self.assertNotIn("CapabilityImplementationBinding", text)

    def test_validate_accepts_portable_payload_and_reports_safe_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))

            code, stdout, stderr = run_cli(["capability", "validate", str(root / "payload")])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(
            payload,
            {
                "package_id": "example.package",
                "version": "1.0.0",
                "payload_sha256": payload["payload_sha256"],
                "capability_count": 1,
                "benchmark_suite_count": 1,
                "resource_count": 1,
                "conformance_count": 1,
            },
        )
        self.assertRegex(payload["payload_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn(temp_dir, stdout)

    def test_validate_redacts_private_paths_and_exception_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SECRET-capability-cli-") as temp_dir:
            root = Path(temp_dir) / "missing"

            code, stdout, stderr = run_cli(["capability", "validate", str(root)])

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "asterion: command failed\n")
        self.assertNotIn("SECRET-capability-cli", stderr)
        self.assertNotIn(str(root), stderr)

    def test_inspect_uses_explicit_local_source_without_provider_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))
            previous = os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT")
            os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = "1"
            try:
                code, stdout, stderr = run_cli(
                    ["capability", "inspect", *local_args(root)]
                )
            finally:
                if previous is None:
                    os.environ.pop("ASTERION_TEST_FORBID_PROVIDER_IMPORT", None)
                else:
                    os.environ["ASTERION_TEST_FORBID_PROVIDER_IMPORT"] = previous

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload["package"], PACKAGE)
        self.assertEqual(payload["source_id"], SOURCE_ID)
        self.assertEqual(payload["source_kind"], "local-directory")
        self.assertEqual(payload["capabilities"], ["example.research@1.0.0"])
        self.assertEqual(payload["benchmark_suites"], ["example.suite@1.0.0"])
        self.assertNotIn(temp_dir, stdout)
        self.assertNotIn("provider.py", stdout)

    def test_inspect_rejects_symlinked_root_without_revealing_secret_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SECRET-capability-root-") as temp_dir:
            base = Path(temp_dir)
            root = copy_fixture(base / "real")
            link_parent = base / "linked-parent"
            link_parent.symlink_to(root.parent, target_is_directory=True)
            args = local_args(root)
            args[args.index("--root") + 1] = str(link_parent / root.name)

            code, stdout, stderr = run_cli(
                [
                    "capability",
                    "inspect",
                    *args,
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "asterion: command failed\n")
        self.assertNotIn("SECRET-capability-root", stderr)

    def test_test_runs_public_conformance_without_executing_implementations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = copy_fixture(Path(temp_dir))
            (root / "provider.py").write_text(
                '''\
from pathlib import Path

from asterion.capability_sdk import (
    BenchmarkTaskBinding,
    CapabilityPackageRef,
    CapabilityRef,
    InstalledCapabilityPackage,
)
from asterion.capability_packages.payload import open_portable_payload


class ExplodingImplementation:
    called = False

    async def execute(self, invocation):
        type(self).called = True
        raise AssertionError("implementation executed")


def create_package():
    payload_root = Path(__file__).resolve().parent / "payload"
    package_ref = CapabilityPackageRef("example.package", "1.0.0")
    payload = open_portable_payload(payload_root)
    return InstalledCapabilityPackage(
        package_ref=package_ref,
        payload_sha256=payload.payload_sha256,
        source_id="example.package.local-directory",
        source_kind="local-directory",
        catalog_roots=(payload_root / "capabilities",),
        benchmark_suite_paths=(payload_root / "benchmark-suites",),
        implementations=(
            (CapabilityRef("example.research", "1.0.0"), ExplodingImplementation()),
        ),
        benchmark_bindings=(
            BenchmarkTaskBinding(
                owner_package=package_ref,
                binding_id="example.task",
                implementation=ExplodingImplementation(),
            ),
        ),
    )
''',
                encoding="utf-8",
            )

            code, stdout, stderr = run_cli(["capability", "test", *local_args(root)])

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(payload, {"passed": True, "errors": []})
        self.assertNotIn(temp_dir, stdout)

    def test_init_copies_closed_template_atomically_without_overwrite_or_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir).resolve()
            target = base / "author-package"

            code, stdout, stderr = run_cli(
                ["capability", "init", str(target), "--package-id", "acme.demo"]
            )

            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout), {"created": "acme.demo@0.1.0"})
            self.assertTrue((target / "payload" / "capability-package.json").is_file())
            self.assertTrue((target / "provider.py").is_file())
            self.assertFalse(any(path.is_symlink() for path in target.rglob("*")))

            overwrite_code, overwrite_out, overwrite_err = run_cli(
                ["capability", "init", str(target), "--package-id", "acme.demo"]
            )
            self.assertEqual(overwrite_code, 2)
            self.assertEqual(overwrite_out, "")
            self.assertEqual(overwrite_err, "asterion: command failed\n")

            link = base / "link"
            link.symlink_to(target, target_is_directory=True)
            link_code, link_out, link_err = run_cli(
                ["capability", "init", str(link), "--package-id", "acme.demo"]
            )
            self.assertEqual(link_code, 2)
            self.assertEqual(link_out, "")
            self.assertEqual(link_err, "asterion: command failed\n")

    def test_init_rejects_dotdot_targets_without_creating_escape_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SECRET-init-target-") as temp_dir:
            base = Path(temp_dir)
            existing = base / "existing"
            existing.mkdir()
            target = existing / ".." / "escape"

            code, stdout, stderr = run_cli(
                ["capability", "init", str(target), "--package-id", "acme.demo"]
            )

            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "asterion: command failed\n")
            self.assertFalse((base / "escape").exists())
            self.assertNotIn("SECRET-init-target", stderr)

    def test_init_ignores_generated_template_cache_without_copying_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SECRET-template-copy-") as temp_dir:
            base = Path(temp_dir).resolve()
            source_template = (
                Path(str(resources.files("asterion.capability_sdk")))
                / "templates/minimal"
            )
            fake_sdk = base / "sdk"
            fake_template = fake_sdk / "templates/minimal"
            shutil.copytree(source_template, fake_template)
            cache = fake_template / "__pycache__"
            cache.mkdir(exist_ok=True)
            py_compile.compile(
                str(fake_template / "provider.py"),
                cfile=str(cache / "provider.cpython-314.pyc"),
            )
            target = base / "target"

            def files(anchor):
                if anchor == "asterion.capability_sdk":
                    return fake_sdk
                return resources.files(anchor)

            with patch("asterion.cli_capability.resources.files", side_effect=files):
                code, stdout, stderr = run_cli(
                    ["capability", "init", str(target), "--package-id", "acme.demo"]
                )

            self.assertEqual(code, 0, stderr)
            self.assertEqual(json.loads(stdout), {"created": "acme.demo@0.1.0"})
            self.assertFalse((target / "__pycache__").exists())
            self.assertFalse(any(path.suffix == ".pyc" for path in target.rglob("*")))
            self.assertFalse(any(base.glob(".target.*")))
            self.assertNotIn("SECRET-template-copy", stderr)

    def test_init_rejects_unknown_template_children_and_cleans_temporary_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SECRET-template-extra-") as temp_dir:
            base = Path(temp_dir).resolve()
            source_template = (
                Path(str(resources.files("asterion.capability_sdk")))
                / "templates/minimal"
            )
            fake_sdk = base / "sdk"
            fake_template = fake_sdk / "templates/minimal"
            shutil.copytree(
                source_template,
                fake_template,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            (fake_template / "unexpected.txt").write_text(
                "SECRET-template-body", encoding="utf-8"
            )
            target = base / "target"

            def files(anchor):
                if anchor == "asterion.capability_sdk":
                    return fake_sdk
                return resources.files(anchor)

            with patch("asterion.cli_capability.resources.files", side_effect=files):
                code, stdout, stderr = run_cli(
                    ["capability", "init", str(target), "--package-id", "acme.demo"]
                )

            self.assertEqual(code, 2)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "asterion: command failed\n")
            self.assertFalse(target.exists())
            self.assertFalse(any(base.glob(".target.*")))
            self.assertNotIn("SECRET-template-extra", stderr)
            self.assertNotIn("SECRET-template-body", stderr)

    def test_init_generated_provider_detects_payload_edits_without_private_helpers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="SECRET-edited-payload-") as temp_dir:
            target = Path(temp_dir).resolve() / "author-package"
            init_code, _, init_err = run_cli(
                ["capability", "init", str(target), "--package-id", "acme.demo"]
            )
            self.assertEqual(init_code, 0, init_err)
            changed_resource = b'{"changed":true}\n'
            (target / "payload/resources/example.conformance").write_bytes(
                changed_resource
            )
            descriptor_path = target / "payload/capability-package.json"
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            descriptor["resources"][0]["sha256"] = hashlib.sha256(
                changed_resource
            ).hexdigest()
            descriptor_path.write_text(
                json.dumps(descriptor, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            code, stdout, stderr = run_cli(
                [
                    "capability",
                    "test",
                    *local_args_for(
                        target,
                        package="acme.demo@0.1.0",
                        source_id="acme.demo.local-directory",
                    ),
                ]
            )

        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "asterion: command failed\n")
        self.assertNotIn("SECRET-edited-payload", stderr)

    def test_pack_and_convert_validate_arguments_then_return_stable_unsupported(self) -> None:
        cases = (
            [
                "pack",
                "--package",
                PACKAGE,
                "--source",
                "local-directory",
                "--output",
                "package.tar",
            ],
            [
                "convert",
                "--package",
                PACKAGE,
                "--from",
                "local-directory",
                "--to",
                "archive",
                "--output",
                "package.tar",
            ],
        )
        for command in cases:
            with self.subTest(command=command[0]):
                code, stdout, stderr = run_cli(["capability", *command])

                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    stderr,
                    "asterion: capability archive forms are not supported yet\n",
                )

        invalid_code, invalid_out, invalid_err = run_cli(
            [
                "capability",
                "convert",
                "--package",
                "example.package@1.0.0",
                "--from",
                "local-directory",
                "--to",
                "local-directory",
                "--output",
                "package.tar",
            ]
        )
        self.assertEqual(invalid_code, 2)
        self.assertEqual(invalid_out, "")
        self.assertEqual(invalid_err, "asterion: command failed\n")

        with tempfile.TemporaryDirectory(prefix="SECRET-output-target-") as temp_dir:
            base = Path(temp_dir)
            existing = base / "existing"
            existing.mkdir()
            output = existing / ".." / "escape.tar"

            output_code, output_out, output_err = run_cli(
                [
                    "capability",
                    "pack",
                    "--package",
                    PACKAGE,
                    "--source",
                    "local-directory",
                    "--output",
                    str(output),
                ]
            )

            self.assertEqual(output_code, 2)
            self.assertEqual(output_out, "")
            self.assertEqual(output_err, "asterion: command failed\n")
            self.assertFalse((base / "escape.tar").exists())
            self.assertNotIn("SECRET-output-target", output_err)

    def test_pack_and_convert_reject_unstaged_sources_without_argparse_echo(self) -> None:
        secret = "registry-SECRET-authority"
        cases = (
            [
                "pack",
                "--package",
                PACKAGE,
                "--source",
                secret,
                "--output",
                "package.tar",
            ],
            [
                "convert",
                "--package",
                PACKAGE,
                "--from",
                "local-directory",
                "--to",
                secret,
                "--output",
                "package.tar",
            ],
        )
        for command in cases:
            with self.subTest(command=command[0]):
                code, stdout, stderr = run_cli(["capability", *command])

                self.assertEqual(code, 2)
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, "asterion: command failed\n")
                self.assertNotIn(secret, stderr)


if __name__ == "__main__":
    unittest.main()
