from __future__ import annotations

import unittest

from asterion.agents.prime import PrimeApplicationToolRegistry
from asterion.runtime.protocol import ProtocolError


class TestPrimeApplicationToolRegistry(unittest.TestCase):
    def test_accepts_sorted_unique_names_and_freezes_input(self) -> None:
        registry = PrimeApplicationToolRegistry(
            "prime.example.tools", "prime.tool.example", ("ipython", "tool.z")
        )
        self.assertEqual(registry.allowed_tool_names, ("ipython", "tool.z"))
        self.assertTrue(registry.matches("prime.example.tools", "prime.tool.example"))
        with self.assertRaises(AttributeError):
            registry.tool_names = ("changed",)  # type: ignore[misc]

    def test_rejects_unsorted_duplicate_or_mutable_names(self) -> None:
        with self.assertRaises(ProtocolError):
            PrimeApplicationToolRegistry(
                "prime.example.tools", "prime.tool.example", ("z", "a")
            )
        with self.assertRaises(ProtocolError):
            PrimeApplicationToolRegistry(
                "prime.example.tools", "prime.tool.example", ("a", "a")
            )
        with self.assertRaises(ProtocolError):
            PrimeApplicationToolRegistry(
                "prime.example.tools", "prime.tool.example", ["a"]  # type: ignore[arg-type]
            )

    def test_matches_rejects_cross_module_capability(self) -> None:
        registry = PrimeApplicationToolRegistry(
            "prime.example.tools", "prime.tool.example", ("ipython",)
        )
        self.assertFalse(registry.matches("prime.other.tools", "prime.tool.example"))
        self.assertFalse(registry.matches("prime.example.tools", "prime.tool.other"))


if __name__ == "__main__":
    unittest.main()
