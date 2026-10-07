"""Offline private research snapshot boundaries."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import p7_research_archive as archive


class TestP7ResearchArchive(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve() / "repo"
        self.repo.mkdir()
        for arguments in (["init", "-q"], ["config", "user.name", "fixture"],
                          ["config", "user.email", "fixture@example.invalid"]):
            subprocess.run(["git", "-C", str(self.repo), *arguments], check=True)
        (self.repo / "source.py").write_text("original\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "source.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "fixture"], check=True)
        self.live = self.repo / ".asterion-private/prime-p7-live"
        self.official = self.repo / ".asterion-private/prime-p7-official"
        for path, body in [(self.live / "success/trace.jsonl", "trace\n"),
                           (self.live / "failure/workspace/notes.txt", "failed research\n"),
                           (self.live / "replays/game.html", "replay\n"),
                           (self.official / "success/official-receipt.json", '{"overall_score": 3}')]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        self.destination = self.repo.parent / "archive"

    def snapshot(self):
        return archive.create_archive(self.repo, self.destination)

    def test_snapshot_preserves_all_attempts_private_permissions_and_git(self):
        (self.repo / "source.py").write_text("dirty\n")
        result = self.snapshot()
        snapshot = Path(result["snapshot"])
        manifest = json.loads((snapshot / "manifest.json").read_text())
        self.assertTrue(manifest["source_git"]["dirty"])
        for path in ["success/trace.jsonl", "failure/workspace/notes.txt", "replays/game.html"]:
            copied = snapshot / "data/.asterion-private/prime-p7-live" / path
            self.assertTrue(copied.is_file())
            self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o700)
        self.assertEqual(archive.verify_archive(self.destination)["files"], result["files"])
        subprocess.run(["git", "-C", str(self.repo), "bundle", "verify",
                        str(snapshot / "source.bundle")], check=True, capture_output=True)

    def test_credentials_and_disposable_caches_are_excluded_and_recorded(self):
        for relative in ["launches/vercel-production.env", "run/.env", "run/auth.json",
                         "run/settings.json", "run/credentials.json", "run/__pycache__/x.pyc"]:
            path = self.live / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("SENTINEL_SECRET")
        snapshot = Path(self.snapshot()["snapshot"])
        manifest = json.loads((snapshot / "manifest.json").read_text())
        self.assertEqual(len(manifest["exclusions"]), 6)
        self.assertFalse(any(b"SENTINEL_SECRET" in path.read_bytes()
                             for path in snapshot.rglob("*") if path.is_file()))

    def test_verify_rejects_changed_missing_added_and_escaping_paths(self):
        snapshot = Path(self.snapshot()["snapshot"])
        target = snapshot / "data/.asterion-private/prime-p7-live/success/trace.jsonl"
        original = target.read_bytes()
        for change in ("changed", "missing", "added", "escape"):
            with self.subTest(change=change):
                if change == "changed":
                    target.write_text("tampered")
                elif change == "missing":
                    target.unlink()
                elif change == "added":
                    (snapshot / "unexpected").write_text("new")
                else:
                    manifest = json.loads((snapshot / "manifest.json").read_text())
                    manifest["files"][0]["path"] = "../escape"
                    (snapshot / "manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(archive.ArchiveError):
                    archive.verify_archive(snapshot)
                if change in {"changed", "missing"}:
                    target.write_bytes(original)
                elif change == "added":
                    (snapshot / "unexpected").unlink()

    def test_source_change_or_symlink_never_updates_latest(self):
        self.snapshot()
        latest = (self.destination / "latest.json").read_bytes()
        original_copy = archive.copy_file
        changed = False

        def copy_and_change(source, destination):
            nonlocal changed
            value = original_copy(source, destination)
            if not changed:
                changed = True
                (self.live / "success/trace.jsonl").write_text("changed during copy")
            return value

        with patch.object(archive, "copy_file", copy_and_change):
            with self.assertRaises(archive.ArchiveError):
                self.snapshot()
        self.assertEqual((self.destination / "latest.json").read_bytes(), latest)
        (self.live / "link").symlink_to(self.repo / "source.py")
        with self.assertRaises(archive.ArchiveError):
            self.snapshot()
        self.assertEqual((self.destination / "latest.json").read_bytes(), latest)
        self.assertFalse(list(self.destination.glob(".staging-*")))

    def test_destination_must_be_outside_repo(self):
        with self.assertRaises(archive.ArchiveError):
            archive.create_archive(self.repo, self.repo / "archive")
        alternate = self.repo.parent / "other"
        alternate.mkdir()
        with self.assertRaises(archive.ArchiveError):
            archive.create_archive(self.repo, alternate / ".." / "repo" / "archive")

    def test_latest_requires_manifest_digest(self):
        self.snapshot()
        latest = json.loads((self.destination / "latest.json").read_text())
        del latest["manifest_sha256"]
        (self.destination / "latest.json").write_text(json.dumps(latest))
        with self.assertRaises(archive.ArchiveError):
            archive.verify_archive(self.destination)

    def test_optional_arc_assets_preserve_games_and_sdk_without_virtualenv(self):
        arc = self.repo.parent / "arc-assets"
        for relative in ["environment_files/game.py", "wheels/sdk.whl", "versions.json",
                         "venv/bin/python", ".env"]:
            path = arc / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative)
        snapshot = Path(archive.create_archive(self.repo, self.destination, arc_root=arc)["snapshot"])
        self.assertTrue((snapshot / "arc-assets/environment_files/game.py").is_file())
        self.assertTrue((snapshot / "arc-assets/wheels/sdk.whl").is_file())
        self.assertFalse((snapshot / "arc-assets/venv").exists())
        archive.verify_archive(snapshot)

    def test_excludes_active_projection_and_dependencies_preserves_sealed_launch_proofs(self):
        for relative in ["cloud-sync/index.json", "launches/vercel-cloud-sync-daemon.log",
                         "launches/pinned-console-old-env/pyvenv.cfg", "x/node_modules/dependency.js",
                         "launches/complete25-cloud-proof.json"]:
            path = self.live / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        snapshot = Path(self.snapshot()["snapshot"])
        copied = snapshot / "data/.asterion-private/prime-p7-live"
        self.assertTrue((copied / "launches/complete25-cloud-proof.json").is_file())
        self.assertFalse((copied / "cloud-sync").exists())
        self.assertFalse((copied / "launches/pinned-console-old-env").exists())
        self.assertFalse((copied / "x/node_modules").exists())
