"""Boundary tests for the semantic source-detachment gate.

Every forbidden token below is assembled from parts. The gate scans this file
too, so a literal token here would make the gate flag its own test suite.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.agents.prime.detachment import (
    find_source_detachment_violations,
)


def _t(*parts: str) -> str:
    """Assemble a forbidden token without writing it literally."""
    return "".join(parts)


CHECKOUT = _t("3th-party/", "prime-agent")
CODING_AGENT_DIST = _t("packages/", "coding-agent/dist")
LEGACY_PROVIDER = _t("asterion.applications.", "prime_agent")
SOURCE_ROOT_ENV = _t("ASTERION_PRIME_", "SOURCE_ROOT")


class TestDetachmentGate(unittest.TestCase):
    def _scan(self, files: dict[str, str]) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, body in files.items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body, encoding="utf-8")
            return [v.rule for v in find_source_detachment_violations(root)]

    def test_flags_prime_checkout_locator(self) -> None:
        rules = self._scan(
            {"src/asterion/applications/prime/p1/operator.py": f'PRIME = "{CHECKOUT}"\n'}
        )
        self.assertIn("prime-source-locator", rules)

    def test_flags_source_root_environment_variable(self) -> None:
        rules = self._scan(
            {"src/asterion/x.py": f'root = environment["{SOURCE_ROOT_ENV}"]\n'}
        )
        self.assertIn("prime-source-locator", rules)

    def test_flags_legacy_package_import(self) -> None:
        rules = self._scan({"src/asterion/x.py": f"from {LEGACY_PROVIDER} import provider\n"})
        self.assertIn("legacy-prime-import", rules)

    def test_flags_prime_coding_agent_launch(self) -> None:
        rules = self._scan(
            {"src/asterion/x.py": f'MAIN = root + "/{CODING_AGENT_DIST}/main.js"\n'}
        )
        self.assertIn("prime-source-locator", rules)

    def test_allows_asterion_owned_operator_root(self) -> None:
        # ASTERION_PRIME_OPERATOR_ROOT resolves to the Asterion repo/install
        # root and ASTERION_PRIME_NODE to a node executable path. Neither is a
        # Prime checkout, so a substring rule would false-positive here.
        rules = self._scan(
            {
                "src/asterion/applications/prime/p1/operator.py": (
                    'root = Path(environment["ASTERION_PRIME_OPERATOR_ROOT"])\n'
                    'node = Path(environment["ASTERION_PRIME_NODE"])\n'
                )
            }
        )
        self.assertEqual(rules, [])

    def test_flags_makefile_source_root_variable(self) -> None:
        rules = self._scan({"Makefile": f"{SOURCE_ROOT_ENV} ?= {CHECKOUT}\n"})
        self.assertIn("prime-source-locator", rules)

    def test_flags_pyproject_legacy_entry_point(self) -> None:
        rules = self._scan(
            {
                "pyproject.toml": (
                    f'"prime-agent" = "{LEGACY_PROVIDER}.provider:create_provider"\n'
                )
            }
        )
        self.assertIn("legacy-prime-import", rules)

    def test_flags_prime_sdk_identifiers(self) -> None:
        # The gate this one replaces enforced these three tokens. Dropping any
        # of them is a coverage regression: the Prime SDK session factory and
        # SDK loader are precisely the "Prime SDK session" execution edge the
        # design forbids, and the source-root getter is a checkout locator
        # under another name.
        for token in (
            _t("createAgent", "Session"),
            _t("loadPrime", "Sdk"),
            _t("prime", "SourceRoot"),
        ):
            with self.subTest(token=token):
                rules = self._scan({"src/asterion/x.py": f"await {token}\n"})
                self.assertIn("prime-sdk-edge", rules)

    def test_undecodable_file_fails_closed(self) -> None:
        # Returning "" for an undecodable file would treat it as clean. A
        # trust-boundary gate must fail closed instead.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src/asterion/x.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\xff\xff\xff")
            with self.assertRaises(AssertionError):
                find_source_detachment_violations(root)

    def test_scan_is_not_silenced_by_an_ancestor_directory_name(self) -> None:
        # A checkout under a directory named build/ must still be scanned.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "build" / "asterion"
            target = root / "src/asterion/x.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f'BAD = "{CHECKOUT}"\n', encoding="utf-8")
            rules = [v.rule for v in find_source_detachment_violations(root)]
            self.assertIn("prime-source-locator", rules)

    def test_reports_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "src/asterion/x.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"ok = 1\nBAD = '{CHECKOUT}'\n", encoding="utf-8")
            violations = find_source_detachment_violations(root)
            self.assertEqual(len(violations), 1)
            self.assertEqual(violations[0].line, 2)


if __name__ == "__main__":
    unittest.main()
