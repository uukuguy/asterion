#!/usr/bin/env python3
"""Offline, operator-private P7 research snapshots; never runs an SDK or model."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid


SCHEMA = "asterion.p7.research-archive/v1"
DEFAULT_ROOTS = (".asterion-private/prime-p7-live", ".asterion-private/prime-p7-official",
                 ".asterion-private/p7-console-manual", "docs/results/arc-agi-3")


class ArchiveError(Exception):
    """Fixed, body-free archive failure."""

    def __init__(self, reason, path=None):
        super().__init__(reason)
        self.reason = reason
        self.path = path


class Progress:
    """Sparse body-free progress for a multi-gigabyte local copy."""

    def begin(self, stage):
        self.stage, self.files, self.bytes = stage, 0, 0
        self.last = time.monotonic()
        self.emit()

    def add(self, size):
        self.files += 1
        self.bytes += size
        if time.monotonic() - self.last >= 30:
            self.emit()
            self.last = time.monotonic()

    def emit(self):
        print(json.dumps({"stage": self.stage, "files": self.files, "bytes": self.bytes}),
              file=sys.stderr, flush=True)


def canonical(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode()


def safe_relative(value):
    if (not isinstance(value, str) or not value or "\\" in value
            or PurePosixPath(value).is_absolute()
            or any(part in {".", "..", ""} for part in value.split("/"))):
        raise ArchiveError("invalid-relative-path")
    return Path(value)


def no_symlinks(path):
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ArchiveError("symlink-rejected")


def absolute_path(path):
    original = Path(path).absolute()
    no_symlinks(original)
    return Path(os.path.abspath(original))


def private_directory(path):
    no_symlinks(path)
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
    if not path.is_dir():
        raise ArchiveError("directory-required")
    path.chmod(0o700)


def signature(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def read_file(path, destination=None):
    no_symlinks(path)
    try:
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            raise ArchiveError("nonregular-file-rejected")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ArchiveError("file-unavailable") from None
    digest = hashlib.sha256()
    size = 0
    output = None
    try:
        with os.fdopen(descriptor, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ArchiveError("nonregular-file-rejected")
            if destination is not None:
                private_directory(destination.parent)
                output = os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                                           0o600), "wb")
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                if output is not None:
                    output.write(chunk)
            if (signature(before) != signature(os.fstat(source.fileno()))
                    or signature(before) != signature(path.stat(follow_symlinks=False))):
                raise ArchiveError("source-changed")
    finally:
        if output is not None:
            output.close()
    return {"bytes": size, "sha256": digest.hexdigest()}


def copy_file(source, destination):
    """Copy bytes to a new private regular file, with no hardlinks."""
    return read_file(source, destination)


def exclusion(name, relative=""):
    lower = name.lower()
    if relative == ".asterion-private/prime-p7-live/cloud-sync":
        return "live-cloud-projection-rebuilt-from-preserved-private-evidence"
    if relative in {".asterion-private/prime-p7-live/launches/vercel-cloud-sync-daemon.log",
                    ".asterion-private/prime-p7-live/launches/vercel-cloud-sync-daemon.json"}:
        return "active-cloud-publisher-state-and-log-not-research-evidence"
    if "/launches/" in relative and lower.endswith("-env"):
        return "launch-virtual-environment-recreated-from-preserved-sdk-wheels"
    if (lower.startswith(".env") or lower.endswith((".env", ".token", ".key", ".pem"))
            or lower in {"auth.json", "settings.json", ".pi", "pi-agent", "credentials",
                         "secrets.json", "token.json", "api-key.json", "api_key.json",
                         "id_rsa", "id_ed25519"}
            or lower.startswith(("credentials.", "credential.", "privatekey", "private-key", "private_key"))):
        return "operator-credentials-or-configuration"
    if lower == "__pycache__" or lower.endswith((".pyc", ".pyo")):
        return "python-bytecode-rebuildable-from-preserved-source"
    if lower in {"venv", ".venv"} or lower.startswith("venv-"):
        return "virtual-environment-recreated-from-preserved-sdk-wheels"
    if lower == "node_modules":
        return "node-dependencies-reinstallable-from-source-lockfiles"
    return None


def contextual_file(path, relative, destination=None):
    try:
        return copy_file(path, destination) if destination is not None else read_file(path)
    except ArchiveError as error:
        raise ArchiveError(error.reason, relative) from None


def directory_error(error):
    raise ArchiveError("directory-unavailable", Path(error.filename).name) from None


def inventory(operator_root, roots, progress=None):
    files, directories, exclusions, missing = {}, [], [], []
    for relative in roots:
        source = operator_root / safe_relative(relative)
        try:
            no_symlinks(source)
        except ArchiveError as error:
            raise ArchiveError(error.reason, relative) from None
        if not source.exists():
            missing.append(relative)
            continue
        if source.is_file():
            reason = exclusion(source.name, relative)
            if reason:
                exclusions.append({"path": relative, "reason": reason})
            else:
                files[relative] = contextual_file(source, relative)
                if progress:
                    progress.add(files[relative]["bytes"])
            continue
        if not source.is_dir():
            raise ArchiveError("nonregular-file-rejected")
        for current, dirs, names in os.walk(source, followlinks=False, onerror=directory_error):
            dirs.sort()
            names.sort()
            parent = Path(current)
            directories.append(parent.relative_to(operator_root).as_posix())
            for name in (*dirs.copy(), *names):
                path = parent / name
                if path.is_symlink():
                    raise ArchiveError("symlink-rejected", path.relative_to(operator_root).as_posix())
                reason = exclusion(name, path.relative_to(operator_root).as_posix())
                if reason:
                    exclusions.append({"path": path.relative_to(operator_root).as_posix(),
                                       "reason": reason})
                    if name in dirs:
                        dirs.remove(name)
                    continue
                if name in names:
                    key = path.relative_to(operator_root).as_posix()
                    files[key] = contextual_file(path, key)
                    if progress:
                        progress.add(files[key]["bytes"])
    return {"files": files, "directories": sorted(set(directories)),
            "exclusions": sorted(exclusions, key=lambda value: value["path"]),
            "missing_roots": missing}


def git(repo, *arguments):
    result = subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True)
    if result.returncode:
        raise ArchiveError("git-operation-failed")
    return result.stdout


def git_state(repo):
    status = git(repo, "status", "--porcelain=v1", "--untracked-files=normal").decode()
    return {"commit": git(repo, "rev-parse", "HEAD").decode().strip(),
            "dirty": bool(status), "working_tree_status": status.splitlines(),
            "refs_sha256": hashlib.sha256(git(repo, "show-ref")).hexdigest(),
            "bundle_scope": "all Git refs; committed source only; dirty files are not in bundle"}


def write_json(path, value):
    private_directory(path.parent)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
        output.write(canonical(value))


def snapshot_summary(snapshot, manifest):
    return {"snapshot": str(snapshot), "files": len(manifest["files"]),
            "bytes": sum(entry["bytes"] for entry in manifest["files"])}


def source_roots(operator_root, extra_roots):
    private = operator_root / ".asterion-private"
    no_symlinks(private)
    discovered = (path.relative_to(operator_root).as_posix()
                  for path in private.glob("prime-p7-*"))
    return tuple(sorted(set((*DEFAULT_ROOTS, *extra_roots, *discovered))))


def arc_inventory(arc_root, progress=None):
    no_symlinks(arc_root)
    if not arc_root.is_dir():
        raise ArchiveError("arc-assets-unavailable")
    roots = tuple(sorted(path.name for path in arc_root.iterdir()))
    selected = tuple(root for root in roots
                     if root in {"environment_files", "wheels", "archived-local-games"})
    result = inventory(arc_root, selected, progress)
    for root in roots:
        if root not in selected:
            result["exclusions"].append({"path": root, "reason": exclusion(root)
                                         or "outside-game-assets-and-sdk-wheels-scope"})
    result["source_roots"] = list(selected)
    return result


def require_stable(before, after, prefix=""):
    if before == after:
        return
    keys = set(before["files"]) | set(after["files"])
    changed = next((key for key in sorted(keys)
                    if before["files"].get(key) != after["files"].get(key)), "source-entry-set")
    raise ArchiveError("source-changed", prefix + changed)


def create_archive(repo, destination=None, *, operator_root=None, extra_roots=(), arc_root=None,
                   progress=None):
    repo = absolute_path(repo)
    operator_root = absolute_path(operator_root or repo)
    destination = absolute_path(destination or repo.parent / "asterion-research-archive/arc-agi-3")
    no_symlinks(repo)
    no_symlinks(operator_root)
    no_symlinks(destination)
    if destination == repo or repo in destination.parents or destination == operator_root or operator_root in destination.parents:
        raise ArchiveError("destination-must-be-outside-source")
    roots = source_roots(operator_root, extra_roots)
    for root in roots:
        safe_relative(root)
        if any(root != other and root.startswith(other + "/") for other in roots):
            raise ArchiveError("overlapping-source-roots")
        if any(exclusion(part) for part in Path(root).parts):
            raise ArchiveError("credential-root-rejected")
    if progress:
        progress.begin("hash-research-before")
    before = inventory(operator_root, roots, progress)
    arc_root = absolute_path(arc_root) if arc_root is not None else None
    if arc_root is not None and (destination == arc_root or arc_root in destination.parents):
        raise ArchiveError("destination-must-be-outside-source")
    if progress and arc_root is not None:
        progress.begin("hash-arc-assets-before")
    arc_before = arc_inventory(arc_root, progress) if arc_root is not None else None
    if not before["files"]:
        raise ArchiveError("no-research-files")
    source_git = git_state(repo)
    private_directory(destination)
    no_symlinks(destination / "latest.json")
    required = sum(value["bytes"] for value in before["files"].values())
    if arc_before is not None:
        required += sum(value["bytes"] for value in arc_before["files"].values())
    object_counts = dict(line.split(": ", 1)
                         for line in git(repo, "count-objects", "-v").decode().splitlines())
    required += (int(object_counts["size"]) + int(object_counts["size-pack"])) * 1024 + 16 * 1024 * 1024
    if shutil.disk_usage(destination).free < required:
        raise ArchiveError("insufficient-disk-space")
    snapshot_name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex[:8]
    staging = destination / (".staging-" + snapshot_name)
    staging.mkdir(mode=0o700)
    snapshot = destination / snapshot_name
    try:
        if progress:
            progress.begin("copy-research")
        files = []
        for relative in before["directories"]:
            private_directory(staging / "data" / relative)
        for relative, expected in sorted(before["files"].items()):
            copied = contextual_file(operator_root / relative, relative, staging / "data" / relative)
            if copied != expected:
                raise ArchiveError("source-changed", relative)
            if progress:
                progress.add(copied["bytes"])
            files.append({"path": "data/" + relative, **copied})
        if arc_before is not None:
            for relative in arc_before["directories"]:
                private_directory(staging / "arc-assets" / relative)
            for relative, expected in sorted(arc_before["files"].items()):
                copied = contextual_file(arc_root / relative, "arc-assets/" + relative,
                                         staging / "arc-assets" / relative)
                if copied != expected:
                    raise ArchiveError("source-changed", "arc-assets/" + relative)
                if progress:
                    progress.add(copied["bytes"])
                files.append({"path": "arc-assets/" + relative, **copied})
        if progress:
            progress.begin("bundle-committed-source")
        git(repo, "bundle", "create", str(staging / "source.bundle"), "--all")
        (staging / "source.bundle").chmod(0o600)
        files.append({"path": "source.bundle", **read_file(staging / "source.bundle")})
        if source_roots(operator_root, extra_roots) != roots:
            raise ArchiveError("source-changed", "source-roots")
        if progress:
            progress.begin("hash-research-after")
        require_stable(before, inventory(operator_root, roots, progress))
        if arc_before is not None:
            if progress:
                progress.begin("hash-arc-assets-after")
            require_stable(arc_before, arc_inventory(arc_root, progress), "arc-assets/")
        if git_state(repo) != source_git:
            raise ArchiveError("source-changed", "git-state")
        manifest = {"schema": SCHEMA, "status": "completed", "snapshot": snapshot_name,
                    "created_at": datetime.now(timezone.utc).isoformat(), "source_git": source_git,
                    "source_roots": list(roots), "missing_roots": before["missing_roots"],
                    "exclusions": before["exclusions"],
                    "directories": sorted(path.relative_to(staging).as_posix()
                                          for path in staging.rglob("*") if path.is_dir()),
                    "official_receipt_files": sorted(entry["path"] for entry in files
                                                     if entry["path"].endswith("/official-receipt.json")),
                    "public_result_json_files": sorted(entry["path"] for entry in files
                                                       if entry["path"].startswith("data/docs/results/arc-agi-3/")
                                                       and entry["path"].endswith(".json")),
                    "files": sorted(files, key=lambda value: value["path"])}
        if arc_before is not None:
            manifest["arc_asset_roots"] = arc_before["source_roots"]
            manifest["exclusions"].extend({"path": "arc-assets/" + item["path"],
                                           "reason": item["reason"]}
                                          for item in arc_before["exclusions"])
        write_json(staging / "manifest.json", manifest)
        verify_archive(staging, progress=progress)
        if snapshot.exists():
            raise ArchiveError("snapshot-already-exists")
        staging.rename(snapshot)
        latest = {"schema": SCHEMA, "snapshot": snapshot_name,
                  "manifest_sha256": read_file(snapshot / "manifest.json")["sha256"]}
        latest_temp = destination / (".latest-" + uuid.uuid4().hex + ".json")
        try:
            write_json(latest_temp, latest)
            os.replace(latest_temp, destination / "latest.json")
        finally:
            latest_temp.unlink(missing_ok=True)
        return snapshot_summary(snapshot, manifest)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def load_json(path):
    no_symlinks(path)
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        raise ArchiveError("invalid-archive-metadata") from None


def verify_archive(location, *, progress=None):
    location = absolute_path(location)
    no_symlinks(location)
    expected_manifest = None
    if not (location / "manifest.json").is_file():
        latest = load_json(location / "latest.json")
        if not isinstance(latest, dict) or latest.get("schema") != SCHEMA:
            raise ArchiveError("invalid-latest-pointer")
        relative = safe_relative(latest.get("snapshot"))
        if len(relative.parts) != 1 or relative.name.startswith("."):
            raise ArchiveError("invalid-latest-pointer")
        location = location / relative
        expected_manifest = latest.get("manifest_sha256")
        if not isinstance(expected_manifest, str) or re.fullmatch("[0-9a-f]{64}", expected_manifest) is None:
            raise ArchiveError("invalid-latest-pointer")
    if expected_manifest is not None and read_file(location / "manifest.json")["sha256"] != expected_manifest:
        raise ArchiveError("manifest-digest-mismatch")
    manifest = load_json(location / "manifest.json")
    if (not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA
            or manifest.get("status") != "completed" or not isinstance(manifest.get("files"), list)
            or not isinstance(manifest.get("directories"), list)):
        raise ArchiveError("invalid-manifest")
    expected_files = {"manifest.json"}
    if progress:
        progress.begin("verify-snapshot")
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise ArchiveError("invalid-manifest")
        relative = safe_relative(entry.get("path"))
        key = relative.as_posix()
        if key in expected_files or type(entry.get("bytes")) is not int or entry["bytes"] < 0:
            raise ArchiveError("invalid-manifest")
        expected_files.add(key)
        if contextual_file(location / relative, key) != {"bytes": entry["bytes"], "sha256": entry.get("sha256")}:
            raise ArchiveError("file-digest-mismatch", key)
        if progress:
            progress.add(entry["bytes"])
    expected_directories = {safe_relative(value).as_posix() for value in manifest["directories"]}
    if len(expected_directories) != len(manifest["directories"]):
        raise ArchiveError("invalid-manifest")
    actual_files, actual_directories = set(), set()
    for current, dirs, files in os.walk(location, followlinks=False, onerror=directory_error):
        parent = Path(current)
        for name in (*dirs, *files):
            path = parent / name
            if path.is_symlink():
                raise ArchiveError("symlink-rejected")
            relative = path.relative_to(location).as_posix()
            if name in dirs:
                actual_directories.add(relative)
            elif stat.S_ISREG(path.stat().st_mode):
                actual_files.add(relative)
            else:
                raise ArchiveError("nonregular-file-rejected")
    if actual_files != expected_files or actual_directories != expected_directories:
        raise ArchiveError("archive-entry-set-mismatch")
    return snapshot_summary(location, manifest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("archive", "verify"))
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--operator-root", type=Path)
    parser.add_argument("--arc-root", type=Path, help="optional offline game assets and SDK wheels; no virtualenv")
    parser.add_argument("--dest", type=Path)
    parser.add_argument("--include", action="append", default=[], help="additional relative research root")
    parser.add_argument("--snapshot", type=Path, help="verify one snapshot instead of latest")
    args = parser.parse_args(argv)
    try:
        if args.command == "archive":
            result = create_archive(args.repo, args.dest, operator_root=args.operator_root,
                                    extra_roots=args.include, arc_root=args.arc_root, progress=Progress())
        else:
            result = verify_archive(args.snapshot or args.dest or args.repo.parent / "asterion-research-archive/arc-agi-3",
                                    progress=Progress())
        print(json.dumps({"status": "completed" if args.command == "archive" else "verified", **result}))
        return 0
    except (ArchiveError, OSError, ValueError) as error:
        reason = str(error) if isinstance(error, ArchiveError) else "filesystem-or-metadata-failure"
        report = {"status": "failed", "reason": reason}
        if isinstance(error, ArchiveError) and error.path:
            report["path"] = error.path
        print(json.dumps(report), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
