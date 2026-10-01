from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path
import unittest


class TestPrimeOperatorConfig(unittest.TestCase):
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
