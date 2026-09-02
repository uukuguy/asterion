"""Static contract tests for the fixed Prime IPython image input."""

from __future__ import annotations

from hashlib import sha256
import io
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from asterion.applications.prime_agent.source_lock import PrimeSourceLock
from tools import build_prime_ipython_image as image


class TestPrimeIpythonImage(unittest.TestCase):
    def test_context_verifies_lock_before_reading_or_packing_source(self) -> None:
        root = Path("/private/prime-agent")
        lock = PrimeSourceLock("a" * 40, "b" * 64, "c" * 64)
        with mock.patch.object(image, "verify_prime_source_lock", side_effect=ValueError("bad")) as verify:
            with self.assertRaises(image.PrimeIpythonImageError):
                image.canonical_build_context(root, lock)
        verify.assert_called_once_with(root, lock)

    def test_context_is_deterministic_normalized_and_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = (Path(temporary) / "prime").resolve()
            root.mkdir()
            (root / "package.json").write_text('{"version":"1.0.0"}\n')
            (root / "package-lock.json").write_text("{}\n")
            (root / "src").mkdir()
            (root / "src" / "z.js").write_text("z\n")
            for name in (".git", "node_modules", ".cache"):
                (root / name).mkdir()
                (root / name / "hidden").write_text("no\n")
            (root / ".env").write_text("secret\n")
            lock = PrimeSourceLock("a" * 40, "b" * 64, "c" * 64)
            with mock.patch.object(image, "verify_prime_source_lock", return_value=lock):
                first = image.canonical_build_context(root, lock)
                second = image.canonical_build_context(root, lock)
        self.assertEqual(first.build_input_sha256, sha256(first.tar_bytes).hexdigest())
        self.assertEqual(first.tar_bytes, second.tar_bytes)
        with tarfile.open(fileobj=io.BytesIO(first.tar_bytes)) as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
        self.assertEqual(names, sorted(names))
        self.assertIn("prime/package-lock.json", names)
        self.assertIn("image/Dockerfile", names)
        self.assertFalse(any(".git" in name or "node_modules" in name or ".env" in name or ".cache" in name for name in names))
        self.assertTrue(all(member.uid == member.gid == member.mtime == 0 for member in members))
        self.assertTrue(all(member.mode in {0o644, 0o755} for member in members))

    def test_dockerfile_and_private_config_are_closed(self) -> None:
        dockerfile = image.image_root() / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")
        self.assertTrue(all("@sha256:" in line for line in content.splitlines() if line.startswith("FROM ")))
        self.assertNotIn("ARG", content)
        self.assertNotIn("ADD http", content)
        self.assertNotIn("secret", content.lower())
        with TemporaryDirectory() as temporary:
            target = (Path(temporary) / "operator-image.json").resolve()
            image.write_operator_image_config(target, "sha256:" + "d" * 64)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(image.PrimeIpythonImageError):
                image.write_operator_image_config(image.repository_root() / "image.json", "sha256:" + "d" * 64)

    def test_context_output_is_external_private_new_file_only(self) -> None:
        payload = b"canonical context"
        with TemporaryDirectory() as temporary:
            external = Path(temporary).resolve()
            source_root = (external / "prime").resolve()
            source_root.mkdir()
            target = external / "context.tar"
            image.write_context_output(target, payload, source_root)
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            for unsafe in (
                target,
                external / ".env",
                external / ".env.operator",
                source_root / "context.tar",
                image.repository_root() / "context.tar",
            ):
                with self.subTest(target=unsafe), self.assertRaises(image.PrimeIpythonImageError):
                    image.write_context_output(unsafe, payload, source_root)
            linked = external / "linked.tar"
            linked.symlink_to(target)
            with self.assertRaises(image.PrimeIpythonImageError):
                image.write_context_output(linked, payload, source_root)
            linked_parent = external / "linked-parent"
            linked_parent.symlink_to(external)
            with self.assertRaises(image.PrimeIpythonImageError):
                image.write_context_output(linked_parent / "context.tar", payload, source_root)
