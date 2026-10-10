from __future__ import annotations

import ast
from pathlib import Path
import unittest
import tempfile
import time

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

    def test_p7_owner_carries_the_concrete_artifact_registry(self) -> None:
        from asterion.agents.prime.application import (
            PrimeApplicationSpec, PrimeOperatorContext, PrimeToolModuleArtifact,
            prepare_prime_application,
        )
        from asterion.agents.prime.deadline import TaskDeadline
        from asterion.agents.prime.execution import AsterionPrimeLimits

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            artifact = PrimeToolModuleArtifact(root / 'p7-tools.mjs', P7_TOOL_REGISTRY)
            spec = PrimeApplicationSpec('test.p7', '1.0.0', 'persistent-code-tools', tools=artifact)
            operator = PrimeOperatorContext(
                executable=root / 'node', entry=None, cwd=root, provider='openai-codex',
                model='gpt-6.1-sol', effort='medium', environment={},
                task_deadline=TaskDeadline(deadline_monotonic=time.monotonic() + 30, deadline_epoch=time.time() + 30))
            owner = prepare_prime_application(spec, operator, authorization=AsterionPrimeLimits(1, 1, 30000))
            self.assertIs(owner.tool_registry, artifact.registry)
            self.assertIs(owner.tool_registry, P7_TOOL_REGISTRY)
            self.assertEqual(owner.tool_registry.module_id, "prime.p7.application-tools")


if __name__ == "__main__":
    unittest.main()
