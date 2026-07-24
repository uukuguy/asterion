from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SETUP_PI_SOURCE = PROJECT / "scripts/setup_pi.sh"


class PiSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.source = self.root / "source-pi"
        self.pi_dir = self.project / "pi"
        (self.project / "scripts").mkdir(parents=True)
        self.source.mkdir()
        self.git("init", "-b", "main", cwd=self.source)
        self.git("config", "user.name", "Asterion Test", cwd=self.source)
        self.git(
            "config", "user.email", "asterion-test@example.invalid", cwd=self.source
        )

        for package in ("tui", "ai", "agent", "coding-agent"):
            package_dir = self.source / "packages" / package
            package_dir.mkdir(parents=True)
            (package_dir / ".keep").write_text("\n", encoding="utf-8")
        cli = self.source / "packages/coding-agent/dist/cli.js"
        cli.parent.mkdir()
        cli.write_text("commit-a\n", encoding="utf-8")
        self.git("add", ".", cwd=self.source)
        self.git("commit", "-m", "commit a", cwd=self.source)
        self.commit_a = self.git("rev-parse", "HEAD", cwd=self.source)

        cli.write_text("commit-b\n", encoding="utf-8")
        self.git("add", ".", cwd=self.source)
        self.git("commit", "-m", "commit b", cwd=self.source)
        self.commit_b = self.git("rev-parse", "HEAD", cwd=self.source)
        (self.project / "pi-revision.txt").write_text(
            f"{self.commit_a}\n", encoding="utf-8"
        )

        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.npm_log = self.root / "npm.log"
        fake_npm = self.bin_dir / "npm"
        fake_npm.write_text(
            "#!/bin/sh\n"
            f"printf '%s:%s\\n' \"$PWD\" \"$*\" >> {self.npm_log!s}\n",
            encoding="utf-8",
        )
        fake_npm.chmod(fake_npm.stat().st_mode | stat.S_IXUSR)

    def git(self, *args: str, cwd: Path) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def install_script(self) -> Path:
        target = self.project / "scripts/setup_pi.sh"
        if SETUP_PI_SOURCE.exists():
            shutil.copy2(SETUP_PI_SOURCE, target)
        return target

    def run_setup(
        self, *, revision: str | None = None, check_only: bool = False
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "DCI_PI_DIR": str(self.pi_dir),
                "DCI_PI_REPO_URL": str(self.source),
                "PATH": f"{self.bin_dir}{os.pathsep}{environment['PATH']}",
            }
        )
        if revision is None:
            environment.pop("DCI_PI_REVISION", None)
        else:
            environment["DCI_PI_REVISION"] = revision
        return subprocess.run(
            [
                "bash",
                str(self.install_script()),
                *(["--check"] if check_only else []),
            ],
            cwd=self.project,
            env=environment,
            capture_output=True,
            text=True,
        )

    def clone_at(self, revision: str) -> None:
        self.git("clone", str(self.source), str(self.pi_dir), cwd=self.root)
        self.git("checkout", "--detach", revision, cwd=self.pi_dir)

    def test_new_checkout_uses_locked_commit(self) -> None:
        result = self.run_setup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.pi_dir), self.commit_a)

    def test_built_checkout_at_pin_is_idempotent(self) -> None:
        self.clone_at(self.commit_a)

        result = self.run_setup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.npm_log.exists())

    def test_clean_mismatch_moves_to_locked_commit(self) -> None:
        self.clone_at(self.commit_b)

        result = self.run_setup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.pi_dir), self.commit_a)
        self.assertTrue(self.npm_log.exists())

    def test_dirty_mismatch_is_rejected_without_mutation(self) -> None:
        self.clone_at(self.commit_b)
        marker = self.pi_dir / "local-change.txt"
        marker.write_text("keep me\n", encoding="utf-8")
        before = self.git("rev-parse", "HEAD", cwd=self.pi_dir)

        result = self.run_setup()

        self.assertEqual(result.returncode, 3)
        self.assertIn("dirty", result.stderr.lower())
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.pi_dir), before)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep me\n")
        self.assertFalse(self.npm_log.exists())

    def test_revision_override_selects_exact_commit(self) -> None:
        result = self.run_setup(revision=self.commit_b)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.pi_dir), self.commit_b)

    def test_revision_override_must_also_be_a_full_commit(self) -> None:
        result = self.run_setup(revision="main")

        self.assertEqual(result.returncode, 2)
        self.assertIn("40-character", result.stderr)
        self.assertFalse(self.pi_dir.exists())

    def test_check_mode_rejects_mismatch_without_mutation(self) -> None:
        self.clone_at(self.commit_b)
        before = self.git("rev-parse", "HEAD", cwd=self.pi_dir)

        result = self.run_setup(check_only=True)

        self.assertEqual(result.returncode, 4)
        self.assertIn("does not match", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.pi_dir), before)
        self.assertFalse(self.npm_log.exists())

    def test_check_mode_does_not_create_missing_checkout(self) -> None:
        result = self.run_setup(check_only=True)

        self.assertEqual(result.returncode, 4)
        self.assertIn("does not exist", result.stderr)
        self.assertFalse(self.pi_dir.exists())
        self.assertFalse(self.npm_log.exists())

    def test_check_mode_accepts_matching_dirty_source_without_mutation(self) -> None:
        self.clone_at(self.commit_a)
        marker = self.pi_dir / "local-change.txt"
        marker.write_text("keep me\n", encoding="utf-8")
        before = self.git("rev-parse", "HEAD", cwd=self.pi_dir)

        result = self.run_setup(check_only=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("contains local changes", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.pi_dir), before)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep me\n")
        self.assertFalse(self.npm_log.exists())

    def test_malformed_lock_fails_before_clone(self) -> None:
        (self.project / "pi-revision.txt").write_text("main\n", encoding="utf-8")

        result = self.run_setup()

        self.assertEqual(result.returncode, 2)
        self.assertIn("40-character", result.stderr)
        self.assertFalse(self.pi_dir.exists())

    def test_symlinked_checkout_is_rejected(self) -> None:
        target = self.root / "pi-target"
        target.mkdir()
        try:
            os.symlink(target, self.pi_dir)
        except OSError as error:
            self.skipTest(f"symlinks unavailable: {error}")

        result = self.run_setup()

        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr.lower())
        self.assertFalse(self.npm_log.exists())

    def test_setup_does_not_read_or_copy_authentication(self) -> None:
        self.clone_at(self.commit_a)
        auth = self.pi_dir / ".pi/agent/auth.json"
        auth.parent.mkdir(parents=True)
        auth.write_text("SECRET-AUTH-BODY\n", encoding="utf-8")

        result = self.run_setup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(auth.read_text(encoding="utf-8"), "SECRET-AUTH-BODY\n")
        self.assertNotIn("SECRET-AUTH-BODY", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
