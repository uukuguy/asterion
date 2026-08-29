from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from zipfile import ZipFile

from tests.test_prime_operational_auth import _zero_effect_counts
from tests.test_prime_operational_harness import (
    PINNED_ROOT,
    _external_pinned_root,
    _rebuild_locked_workspaces,
)
from tools.setup_prime_agent import PINNED_PRIME_COMMIT


PROJECT = Path(__file__).resolve().parents[1]
INSTALLED_OPERATIONAL_RESOURCES = {
    "asterion/control/providers/prime/resources/prime-operational-harness.mjs",
    "asterion/control/providers/prime/resources/prime-operational-module-lock.json",
    "asterion/control/providers/prime/resources/prime-operational-module.mjs",
    "asterion/control/providers/prime/resources/prime-settings-keybindings-request.schema.json",
    "asterion/control/providers/prime/resources/prime-settings-keybindings-validator.mjs",
}
INSTALLED_OPERATIONAL_SCHEMAS = {
    "asterion/schemas/operation/v1/auth-request.schema.json",
    "asterion/schemas/operation/v1/controlled-update-restart-request.schema.json",
    "asterion/schemas/operation/v1/doctor-request.schema.json",
    "asterion/schemas/operation/v1/model-selection-request.schema.json",
    "asterion/schemas/operation/v1/operation-receipt.schema.json",
    "asterion/schemas/operation/v1/operation-request-descriptor.schema.json",
    "asterion/schemas/operation/v1/operation-transaction.schema.json",
    "asterion/schemas/operation/v1/settings-keybindings-request.schema.json",
    "asterion/schemas/operation/v1/telemetry-usage-request.schema.json",
}


def _build_and_extract_wheel(parent: Path) -> Path:
    dist = parent / "dist"
    subprocess.run(
        ("uv", "build", "--wheel", "--out-dir", str(dist), "."),
        cwd=PROJECT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    wheel = next(dist.glob("*.whl"))
    installed = parent / "installed"
    with ZipFile(wheel) as archive:
        archive.extractall(installed)
    return installed


def _promotion_report(
    *,
    installed: Path,
    external_prime_root: Path,
) -> Mapping[str, object]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = f"{installed}{os.pathsep}{PROJECT}"
    code = (
        "import json, os; "
        "from pathlib import Path; "
        "from tools.check_promotion import _promotion_report; "
        "print(json.dumps(_promotion_report("
        "external_prime_root=Path(os.environ['PRIME_ROOT'])), sort_keys=True))"
    )
    completed = subprocess.run(
        (sys.executable, "-c", code),
        cwd=installed.parent,
        env={**environment, "PRIME_ROOT": str(external_prime_root)},
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=90,
    )
    return json.loads(completed.stdout)


class TestPrimeOperationalPackaging(unittest.TestCase):
    def test_wheel_contains_complete_operational_resource_closure(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-operational-wheel-"
        ) as temporary:
            installed = _build_and_extract_wheel(Path(temporary))
            wheel_root = installed.parent / "dist"
            wheel = next(wheel_root.glob("*.whl"))

            with ZipFile(wheel) as archive:
                members = frozenset(archive.namelist())
                for packaged in sorted(
                    INSTALLED_OPERATIONAL_RESOURCES | INSTALLED_OPERATIONAL_SCHEMAS
                ):
                    with self.subTest(resource=packaged):
                        self.assertIn(packaged, members)

                self.assertEqual(
                    archive.read(
                        "asterion/control/providers/prime/resources/"
                        "prime-operational-harness.mjs"
                    ),
                    (
                        PROJECT
                        / "tests/fixtures/prime_gateway/v1/real-prime-operations.mjs"
                    ).read_bytes(),
                )
                self.assertEqual(
                    json.loads(
                        archive.read(
                            "asterion/control/providers/prime/resources/"
                            "prime-settings-keybindings-request.schema.json"
                        )
                    ),
                    json.loads(
                        (
                            PROJECT
                            / "schemas/operation/v1/"
                            "settings-keybindings-request.schema.json"
                        ).read_text(encoding="utf-8")
                    ),
                )

            for relative in INSTALLED_OPERATIONAL_RESOURCES:
                self.assertTrue((installed / relative).is_file(), relative)

    def test_installed_wheel_rejects_repo_local_prime_root_without_private_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-operational-reject-"
        ) as temporary:
            installed = _build_and_extract_wheel(Path(temporary))
            environment = dict(os.environ)
            environment["PYTHONPATH"] = f"{installed}{os.pathsep}{PROJECT}"
            code = (
                "import os, sys; "
                "from pathlib import Path; "
                "from tools.check_promotion import _promotion_report; "
                "try: "
                "_promotion_report(external_prime_root=Path(os.environ['PRIME_ROOT'])); "
                "except Exception as error: "
                "print(str(error), file=sys.stderr); raise SystemExit(1)"
            )
            completed = subprocess.run(
                (sys.executable, "-c", code),
                cwd=installed.parent,
                env={**environment, "PRIME_ROOT": str(PINNED_ROOT)},
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(str(PROJECT), completed.stdout + completed.stderr)
        self.assertNotIn(str(PINNED_ROOT), completed.stdout + completed.stderr)

    def test_installed_wheel_runs_operational_resource_only_against_external_pinned_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-operational-installed-"
        ) as temporary:
            parent = Path(temporary)
            installed = _build_and_extract_wheel(parent)
            external_prime_root = _external_pinned_root(parent)
            try:
                _rebuild_locked_workspaces(external_prime_root)
                report = _promotion_report(
                    installed=installed,
                    external_prime_root=external_prime_root,
                )
            finally:
                subprocess.run(
                    (
                        "git",
                        "-C",
                        str(PINNED_ROOT),
                        "worktree",
                        "remove",
                        "--force",
                        str(external_prime_root),
                    ),
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=20,
                )

        self.assertEqual(report["source_commit"], PINNED_PRIME_COMMIT)
        self.assertTrue(report["external_prime_root"])
        self.assertEqual(report["effect_counts"], _zero_effect_counts())
        self.assertEqual(report["package_count"], 6)
        self.assertNotIn(str(parent), json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
