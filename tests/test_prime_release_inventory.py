from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from asterion.applications.prime.inventory import prime_application_index


PROJECT = Path(__file__).resolve().parents[1]


class PrimeReleaseInventoryTests(unittest.TestCase):
    def test_pyproject_index_matches_exact_release_inventory(self) -> None:
        index = tomllib.loads(
            (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
        )["project"]["entry-points"]["asterion.application_index"]
        actual = {
            name: target for name, target in index.items() if name.startswith("prime.")
        }

        self.assertEqual(actual, prime_application_index())


if __name__ == "__main__":
    unittest.main()
