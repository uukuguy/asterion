from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from asterion.applications.prime.p7.tool_registry import (
    P7_APPLICATION_TOOL_NAMES,
    P7_TOOL_CAPABILITY_ID,
    P7_TOOL_MODULE_ID,
    P7_TOOL_REGISTRY,
)
from asterion.runtime.protocol import ProtocolError


class TestP7ToolRegistry(unittest.TestCase):
    def test_live_selects_explicit_application_artifacts(self) -> None:
        from asterion.applications.prime.p7 import live

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            resources = root / "resources"
            resources.mkdir()
            for name in ("ipython-extension", "p7-research-extension", "p7-legacy-extension"):
                (resources / (name + ".mjs")).write_text("export default function register() {}")
            with patch.object(live.importlib_resources, "files", return_value=root):
                self.assertEqual(live.extension_path().name, "p7-research-extension.mjs")
                self.assertEqual(live.extension_path(research_mode=False).name, "p7-legacy-extension.mjs")
                (resources / "p7-research-extension.mjs").unlink()
                with self.assertRaises(live.P7LiveSolveError):
                    live.extension_path()

    def test_registry_has_exact_identity_and_canonical_names(self) -> None:
        self.assertEqual(P7_TOOL_MODULE_ID, "prime.p7.application-tools")
        self.assertEqual(P7_TOOL_CAPABILITY_ID, "prime.tool.p7")
        self.assertEqual(P7_TOOL_REGISTRY.allowed_tool_names, P7_APPLICATION_TOOL_NAMES)
        self.assertEqual(P7_APPLICATION_TOOL_NAMES, tuple(sorted(set(P7_APPLICATION_TOOL_NAMES))))
        self.assertEqual(P7_APPLICATION_TOOL_NAMES, ('ipython', 'p7_execute_plan', 'p7_workspace'))

    def test_live_reexports_one_registry_tuple(self) -> None:
        from asterion.applications.prime.p7 import live

        self.assertIs(live.P7_APPLICATION_TOOL_NAMES, P7_APPLICATION_TOOL_NAMES)
        command = live.pi_base_command(
            node=Path("/usr/bin/node"), pi_entry=Path("/tmp/rpc-entry.js")
        )
        tools = command[command.index("--tools") + 1].split(",")
        self.assertEqual(tuple(tools), P7_APPLICATION_TOOL_NAMES)

    def test_prompt_registry_rejects_unknown_executable_name(self) -> None:
        from asterion.applications.prime.p7.broker import P7ToolRegistry, Tool

        registry = P7ToolRegistry()
        registry.register(
            Tool(
                name="unknown_tool",
                description="unknown",
                signature="unknown()",
                category="test",
            )
        )
        with self.assertRaises(ProtocolError):
            registry.validate_executable_names()
