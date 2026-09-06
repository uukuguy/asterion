from __future__ import annotations

import base64
import csv
from hashlib import sha256
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


class TestP7DevelopmentRuntimeLock(unittest.TestCase):
    _packages = {"arc_agi": ("arc-agi", "0.9.9"), "arcengine": ("arcengine", "0.9.3")}

    def _wheel(self, distribution: str, version: str) -> bytes:
        package = distribution.replace("-", "_")
        dist_info = f"{package}-{version}.dist-info"
        files = {
            f"{package}/__init__.py": f"NAME = {package!r}\n".encode(),
            f"{package}/module.py": b"VALUE = 1\n",
            f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\n",
            f"{dist_info}/METADATA": f"Name: {distribution}\nVersion: {version}\n".encode(),
        }
        rows = []
        for name, value in sorted(files.items()):
            digest = base64.urlsafe_b64encode(sha256(value).digest()).rstrip(b"=").decode()
            rows.append([name, "sha256=" + digest, str(len(value))])
        rows.append([f"{dist_info}/RECORD", "", ""])
        files[f"{dist_info}/RECORD"] = "".join(",".join(row) + "\n" for row in rows).encode()
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(package + "/", b"")
            archive.writestr(dist_info + "/", b"")
            for name, value in files.items():
                archive.writestr(name, value)
        return output.getvalue()

    def _root(self) -> tuple[tempfile.TemporaryDirectory[str], Path, dict[str, tuple[str, str, str, str]]]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve()
        interpreter = root / "venv/bin/python3"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("#!/bin/sh\nexit 0\n")
        interpreter.chmod(0o700)
        site_packages = root / "venv/lib/python/site-packages"
        site_packages.mkdir(parents=True)
        wheels = root / "wheels"
        wheels.mkdir()
        entries: dict[str, tuple[str, str, str, str]] = {}
        for key, (distribution, version) in self._packages.items():
            filename = f"{distribution.replace('-', '_')}-{version}-py3-none-any.whl" if distribution == "arc-agi" else f"{distribution}-{version}-py3-none-any.whl"
            # The real arc-agi filename intentionally retains its underscore.
            if key == "arc_agi":
                filename = "arc_agi-0.9.9-py3-none-any.whl"
            payload = self._wheel(distribution, version)
            (wheels / filename).write_bytes(payload)
            entries[key] = (filename, distribution, version, "sha256:" + sha256(payload).hexdigest())
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    destination = site_packages / info.filename
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(info))
            dist_info = site_packages / f"{distribution.replace('-', '_')}-{version}.dist-info"
            (dist_info / "INSTALLER").write_text("uv\n")
            (dist_info / "REQUESTED").write_text("")
            source_record = list(csv.reader((dist_info / "RECORD").read_text().splitlines()))
            source_record[:0] = [[f"{dist_info.name}/INSTALLER", "sha256=unused", "3"], [f"{dist_info.name}/REQUESTED", "sha256=unused", "0"]]
            (dist_info / "RECORD").write_text("".join(",".join(row) + "\n" for row in source_record))
        return temporary, root, entries

    def _probe(self, root: Path) -> subprocess.CompletedProcess[bytes]:
        site_packages = root / "venv/lib/python/site-packages"
        payload: dict[str, object] = {"prefix": str(root / "venv"), "site_packages": str(site_packages)}
        for key, (distribution, version) in self._packages.items():
            payload[key] = {"version": version, "module": str(site_packages / distribution.replace("-", "_") / "__init__.py")}
        return subprocess.CompletedProcess((), 0, json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())

    def test_accepts_exact_wheels_and_matching_installed_packages(self) -> None:
        from asterion.applications.prime_agent.operator import p7_runtime_lock as lock

        temporary, root, wheels = self._root()
        with temporary, patch.object(lock, "_WHEELS", wheels), patch.object(lock.subprocess, "run", return_value=self._probe(root)):
            verified = lock.verify_p7_development_runtime(root)
        self.assertRegex(verified.runtime_sha256, r"\Asha256:[0-9a-f]{64}\Z")
        self.assertEqual(repr(verified), "P7DevelopmentRuntimeSet(redacted)")

    def test_rejects_tampered_installed_package_file(self) -> None:
        from asterion.applications.prime_agent.operator import p7_runtime_lock as lock

        for package in ("arc_agi", "arcengine"):
            temporary, root, wheels = self._root()
            with temporary, self.subTest(package=package), patch.object(lock, "_WHEELS", wheels), patch.object(lock.subprocess, "run", return_value=self._probe(root)):
                (root / f"venv/lib/python/site-packages/{package}/module.py").write_text("VALUE = 999\n")
                with self.assertRaises(lock.P7DevelopmentRuntimeLockError):
                    lock.verify_p7_development_runtime(root)

    def test_rejects_extra_or_symlinked_package_member(self) -> None:
        from asterion.applications.prime_agent.operator import p7_runtime_lock as lock

        for mutation in ("extra", "symlink"):
            temporary, root, wheels = self._root()
            with temporary, self.subTest(mutation=mutation), patch.object(lock, "_WHEELS", wheels), patch.object(lock.subprocess, "run", return_value=self._probe(root)):
                package = root / "venv/lib/python/site-packages/arc_agi"
                if mutation == "extra":
                    (package / "injected.py").write_text("raise RuntimeError\n")
                else:
                    target = package / "module.py"
                    target.rename(package / "saved.py")
                    target.symlink_to("saved.py")
                with self.assertRaises(lock.P7DevelopmentRuntimeLockError):
                    lock.verify_p7_development_runtime(root)
