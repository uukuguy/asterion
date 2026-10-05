from __future__ import annotations

import unittest
from pathlib import Path

from asterion.applications.prime.p7.tool_registry import (
    P7_APPLICATION_TOOL_NAMES,
    P7_TOOL_CAPABILITY_ID,
    P7_TOOL_MODULE_ID,
    P7_TOOL_REGISTRY,
)
from asterion.runtime.protocol import ProtocolError


class TestP7ToolRegistry(unittest.TestCase):
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
