from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class TestP7DevelopmentRuntimeLock(unittest.TestCase):
    def _root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name).resolve()
        interpreter = root / "venv/bin/python3"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("#!/bin/sh\nexit 0\n")
        interpreter.chmod(0o700)
        wheels = root / "wheels"
        wheels.mkdir()
        (wheels / "arc_agi-0.9.9-py3-none-any.whl").write_bytes(b"arc-agi")
        (wheels / "arcengine-0.9.3-py3-none-any.whl").write_bytes(b"arcengine")
        return temporary, root

    def _wheels(self) -> dict[str, tuple[str, str, str, str]]:
        return {
            "arc_agi": ("arc_agi-0.9.9-py3-none-any.whl", "arc-agi", "0.9.9", "sha256:" + sha256(b"arc-agi").hexdigest()),
            "arcengine": ("arcengine-0.9.3-py3-none-any.whl", "arcengine", "0.9.3", "sha256:" + sha256(b"arcengine").hexdigest()),
        }

    def _probe(self, root: Path, *, outside: bool = False) -> subprocess.CompletedProcess[bytes]:
        venv = root / "venv"
        module_root = root / ("other" if outside else "venv") / "lib/python/site-packages"
        return subprocess.CompletedProcess(
            (),
            0,
            json.dumps({
                "prefix": str(venv),
                "arc_agi": {"version": "0.9.9", "module": str(module_root / "arc_agi/__init__.py")},
                "arcengine": {"version": "0.9.3", "module": str(module_root / "arcengine/__init__.py")},
            }, separators=(",", ":"), sort_keys=True).encode(),
        )

    def test_accepts_exact_wheels_and_target_venv_imports(self) -> None:
        from asterion.applications.prime_agent.operator import p7_runtime_lock as lock

        temporary, root = self._root()
        with temporary, patch.object(lock, "_WHEELS", self._wheels()), patch.object(lock.subprocess, "run", return_value=self._probe(root)):
            verified = lock.verify_p7_development_runtime(root)
        self.assertRegex(verified.runtime_sha256, r"\Asha256:[0-9a-f]{64}\Z")
        self.assertEqual(repr(verified), "P7DevelopmentRuntimeSet(redacted)")

    def test_rejects_symlinked_wheel_and_import_outside_target_venv(self) -> None:
        from asterion.applications.prime_agent.operator import p7_runtime_lock as lock

        for mutation in ("symlink", "outside"):
            temporary, root = self._root()
            with temporary, self.subTest(mutation=mutation), patch.object(lock, "_WHEELS", self._wheels()), self.assertRaises(lock.P7DevelopmentRuntimeLockError):
                if mutation == "symlink":
                    wheel = root / "wheels/arc_agi-0.9.9-py3-none-any.whl"
                    target = root / "wheels/target"
                    wheel.rename(target)
                    wheel.symlink_to(target.name)
                    lock.verify_p7_development_runtime(root)
                else:
                    with patch.object(lock.subprocess, "run", return_value=self._probe(root, outside=True)):
                        lock.verify_p7_development_runtime(root)
