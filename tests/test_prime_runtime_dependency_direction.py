from __future__ import annotations

from dataclasses import fields
import ast
from pathlib import Path
import unittest

from asterion.applications.prime.p7.tool_registry import P7_TOOL_REGISTRY


ROOT = Path(__file__).resolve().parents[1]


class TestPrimeRuntimeDependencyDirection(unittest.TestCase):
    def test_root_binding_has_no_eager_p7_imports(self) -> None:
        source = (
            ROOT / "src/asterion/applications/prime/runtime_binding.py"
        ).read_text()
        module = ast.parse(source)
        eager_p7_imports = [
            node
            for node in module.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            and "prime.p7" in ast.unparse(node)
        ]
        self.assertEqual(eager_p7_imports, [])

    def test_p7_launch_carries_the_concrete_registry(self) -> None:
        from asterion.applications.prime.p7.runtime_binding import PrimeLaunch

        self.assertIn("tool_registry", {field.name for field in fields(PrimeLaunch)})
        self.assertEqual(P7_TOOL_REGISTRY.module_id, "prime.p7.application-tools")


if __name__ == "__main__":
    unittest.main()
