from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "src/asterion/applications/prime_agent/operator"
IMAGE = OPERATOR / "p7_solving_image"
TAG = "asterion-prime-p7-solving-test"


@unittest.skipUnless(shutil.which("docker"), "Docker is unavailable")
class TestP7SolvingKernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build = subprocess.run(
            ["docker", "build", "--pull=false", "--tag", TAG, "--file", str(IMAGE / "Dockerfile"), str(OPERATOR)],
            cwd=ROOT,
            capture_output=True,
            check=False,
            timeout=180,
        )
        if build.returncode:
            raise unittest.SkipTest("solve image cannot be built")

    def test_workspace_client_import_persists_across_two_cells(self) -> None:
        from asterion.applications.prime_agent.operator.p7_solving_client import (
            p7_solving_client_module_bytes,
        )

        with tempfile.TemporaryDirectory() as workspace:
            Path(workspace).chmod(0o777)
            (Path(workspace) / "p7_client.py").write_bytes(
                p7_solving_client_module_bytes("/broker/model.sock", "test-token")
            )
            started = subprocess.run(
                ["docker", "run", "--detach", "--rm", "--network", "none", "--read-only", "--tmpfs", "/tmp:rw,nodev,noexec,nosuid,size=16777216,uid=65534,gid=65534,mode=0700", "--volume", f"{workspace}:/workspace:rw,rprivate", TAG],
                capture_output=True,
                check=True,
                text=True,
                timeout=30,
            )
            container = started.stdout.strip()
            try:
                for _ in range(100):
                    probe = subprocess.run(
                        ["docker", "exec", container, "/usr/local/bin/python", "-c", "import os; raise SystemExit(not os.path.exists('/workspace/kernel.sock'))"],
                        capture_output=True,
                        check=False,
                        text=True,
                        timeout=5,
                    )
                    if probe.returncode == 0:
                        break
                    time.sleep(0.05)
                first = json.loads(subprocess.check_output(["docker", "exec", container, "/usr/local/bin/prime-p7-solving", "--client", base64.b64encode(b"import p7_client\np7_client._SEQUENCE = 41").decode()], text=True, timeout=10))
                second = json.loads(subprocess.check_output(["docker", "exec", container, "/usr/local/bin/prime-p7-solving", "--client", base64.b64encode(b"import p7_client, sys\nassert '/workspace' not in sys.path and '' not in sys.path\nprint(p7_client._SEQUENCE + 1)").decode()], text=True, timeout=10))
            finally:
                subprocess.run(["docker", "rm", "--force", container], capture_output=True, check=False)
        self.assertEqual(first["cell_count"], 1)
        self.assertFalse(first["is_error"])
        self.assertEqual(second["cell_count"], 2)
        self.assertFalse(second["is_error"])
        self.assertIn("42", second["output"])

    def test_code_output_and_cell_caps_share_one_boundary(self) -> None:
        launcher = (IMAGE / "launcher.py").read_text(encoding="utf-8")
        self.assertIn("_CELL_CAP = 16 * 1024", launcher)
        self.assertIn("_OUTPUT_CAP = 4096", launcher)
        self.assertIn("_CELL_LIMIT = 128", launcher)
