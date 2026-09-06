from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest


_PROBE_ROOT = Path("/tmp/arc-agi-probe.zAWnDU/normal-env/ls20/9607627b")


class TestP7DevelopmentResourceLock(unittest.TestCase):
    def _root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "resources"
        root.mkdir()
        for name in ("ls20.py", "metadata.json"):
            shutil.copyfile(_PROBE_ROOT / name, root / name)
        return temporary, root

    def test_accepts_only_the_exact_direct_game_resources(self) -> None:
        from asterion.applications.prime_agent.operator.p7_resource_lock import verify_p7_development_resources

        temporary, root = self._root()
        with temporary:
            verified = verify_p7_development_resources(root)
            self.assertEqual(verified.game_id, "ls20-9607627b")
            self.assertEqual(verified.root, root)

    def test_rejects_mutated_metadata_and_symlinked_source(self) -> None:
        from asterion.applications.prime_agent.operator.p7_resource_lock import P7DevelopmentResourceLockError, verify_p7_development_resources

        for mutation in ("metadata", "symlink"):
            temporary, root = self._root()
            with temporary, self.subTest(mutation=mutation), self.assertRaises(P7DevelopmentResourceLockError):
                if mutation == "metadata":
                    (root / "metadata.json").write_bytes(b"{}")
                else:
                    target = root / "source"
                    target.write_bytes((root / "ls20.py").read_bytes())
                    (root / "ls20.py").unlink()
                    (root / "ls20.py").symlink_to(target.name)
                verify_p7_development_resources(root)
