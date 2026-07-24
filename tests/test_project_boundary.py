from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "src/asterion"


class AsterionProjectBoundaryTests(unittest.TestCase):
    def test_production_source_never_imports_original_dci_or_repository_tests(self) -> None:
        forbidden: list[tuple[Path, str]] = []
        for path in SOURCE.rglob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    names = [node.module]
                else:
                    continue
                for name in names:
                    if (
                        name == "dci"
                        or name.startswith("dci.")
                        or name == "tests"
                        or name.startswith("tests.")
                    ):
                        forbidden.append((path.relative_to(PROJECT), name))
        self.assertEqual(forbidden, [])

    def test_project_metadata_and_resources_are_internal(self) -> None:
        self.assertTrue((PROJECT / "pyproject.toml").is_file())
        self.assertTrue((PROJECT / "schemas/agent-runtime/v1/event.schema.json").is_file())
        self.assertTrue((SOURCE / "dci/resources/batch-profiles.json").is_file())

    def test_project_metadata_does_not_require_a_parent_workspace(self) -> None:
        text = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("../", text)
        self.assertNotRegex(text, r"(?m)^\s*members\s*=")


if __name__ == "__main__":
    unittest.main()
