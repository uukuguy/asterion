from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path
import unittest


class TestPrimeOperatorConfig(unittest.TestCase):
    def test_effort_preserves_defaults_and_accepts_concrete_pi_levels(self) -> None:
        from asterion.applications.prime import operator_config as config

        resolve = getattr(config, "resolve_pi_effort", None)
        self.assertTrue(callable(resolve), "Prime effort resolver is required")
        for default in ("off", "medium"):
            with self.subTest(default=default):
                self.assertEqual(resolve({}, default=default), default)
        for effort in ("off", "minimal", "low", "medium", "high", "xhigh", "max"):
            environment = {"ASTERION_PRIME_EFFORT": effort}
            with self.subTest(effort=effort):
                self.assertEqual(resolve(environment, default="medium"), effort)
                self.assertEqual(environment, {"ASTERION_PRIME_EFFORT": effort})

    def test_invalid_effort_fails_closed_without_echoing_value(self) -> None:
        from asterion.applications.prime import operator_config as config

        resolve = getattr(config, "resolve_pi_effort", None)
        self.assertTrue(callable(resolve), "Prime effort resolver is required")
        for effort in ("", "HIGH", " high ", "auto", "SENTINELSECRET", None, 1):
            with self.subTest(effort=effort), self.assertRaisesRegex(
                ValueError, "^Prime reasoning effort is invalid$"
            ):
                resolve({"ASTERION_PRIME_EFFORT": effort}, default="medium")

    def test_effort_overrides_command_once_and_preserves_missing_configuration(self) -> None:
        from asterion.applications.prime import operator_config as config

        apply = getattr(config, "apply_pi_effort", None)
        self.assertTrue(callable(apply), "Prime command effort binding is required")
        command = ("node", "pi", "--thinking", "medium", "--model", "example")
        self.assertIs(apply(command, {}), command)
        overridden = apply(command, {"ASTERION_PRIME_EFFORT": "high"})
        self.assertEqual(overridden, ("node", "pi", "--thinking", "high", "--model", "example"))
        self.assertEqual(command[3], "medium")
        self.assertEqual(apply(("node", "pi"), {"ASTERION_PRIME_EFFORT": "low"}),
                         ("node", "pi", "--thinking", "low"))

    def test_dotenv_effort_overrides_stale_process_effort(self) -> None:
        from asterion.applications.prime.operator_config import load_operator_environment

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("ASTERION_PRIME_EFFORT=high\n")
            values = load_operator_environment(root, {"ASTERION_PRIME_EFFORT": "low"})
            self.assertEqual(values["ASTERION_PRIME_EFFORT"], "high")
            (root / ".env").write_text("")
            self.assertEqual(load_operator_environment(root, {"ASTERION_PRIME_EFFORT": "low"})
                             ["ASTERION_PRIME_EFFORT"], "low")

    def test_loads_basic_dotenv_without_python_dotenv_import(self) -> None:
        module_name = "asterion.applications.prime.operator_config"
        original = sys.modules.pop(module_name, None)
        previous_dotenv = sys.modules.get("dotenv", ...)
        sys.modules["dotenv"] = None  # type: ignore[assignment]
        try:
            module = importlib.import_module(module_name)
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / ".env").write_text(
                    "ARC_API_KEY=from-dotenv\nPI_MODEL=\"quoted-model\"\n",
                    encoding="utf-8",
                )
                values = module.load_operator_environment(
                    root,
                    {"PI_MODEL": "from-process", "EXPLICIT": "yes"},
                )
            self.assertEqual(values["ARC_API_KEY"], "from-dotenv")
            self.assertEqual(values["PI_MODEL"], "from-process")
            self.assertEqual(values["EXPLICIT"], "yes")
        finally:
            sys.modules.pop(module_name, None)
            if previous_dotenv is ...:
                sys.modules.pop("dotenv", None)
            else:
                sys.modules["dotenv"] = previous_dotenv
            if original is not None:
                sys.modules[module_name] = original


if __name__ == "__main__":
    unittest.main()
