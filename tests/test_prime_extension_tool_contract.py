from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

from asterion.applications.prime.p7.tool_registry import P7_APPLICATION_TOOL_NAMES


PROJECT = Path(__file__).resolve().parents[1]
BUNDLE = PROJECT / "src/asterion/applications/prime/resources/ipython-extension.mjs"


class TestPrimeExtensionToolContract(unittest.TestCase):
    def test_bundled_extension_exports_the_python_prime_tool_set(self) -> None:
        script = (
            "import { toolNames } from "
            + json.dumps(BUNDLE.as_uri())
            + "; process.stdout.write(JSON.stringify(toolNames()));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=PROJECT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(tuple(json.loads(result.stdout)), P7_APPLICATION_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
