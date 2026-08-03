from __future__ import annotations

import tempfile
import subprocess
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.capabilities.dci.implementation.runtime.pi_rpc import PiRpcClient


def _client(root: Path) -> PiRpcClient:
    package = root / "pi" / "packages" / "coding-agent"
    (root / "pi" / "node_modules" / "undici").mkdir(parents=True)
    (root / "pi" / "node_modules" / "undici" / "index.js").write_text(
        "import { writeFileSync } from 'node:fs';\n"
        "export class ProxyAgent { constructor(proxy) { if (!proxy) throw new Error(); } }\n"
        "export function setGlobalDispatcher() {\n"
        "  if (process.env.ASTERION_PROXY_MARKER) "
        "writeFileSync(process.env.ASTERION_PROXY_MARKER, 'installed');\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "pi" / "node_modules" / "undici" / "package.json").write_text(
        '{"type":"module"}\n', encoding="utf-8"
    )
    package.mkdir(parents=True)
    agent = root / "agent"
    agent.mkdir()
    return PiRpcClient(
        package_dir=package,
        cwd=root,
        agent_dir=agent,
        provider="openai-codex",
        model="gpt-test",
        tools="read",
        show_tools=False,
        system_prompt_file=None,
        append_system_prompt_file=None,
        extra_args=(),
        literal_extra_args=(),
        keep_session=False,
        node_max_old_space_size_mb=None,
    )


class DciPiRpcProxyTests(unittest.TestCase):
    def test_proxy_config_installs_node_fetch_dispatcher_without_secret_in_options(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            client = _client(root)
            with patch.dict(
                "os.environ",
                {
                    "PATH": "/usr/bin",
                    "HTTPS_PROXY": "http://PRIVATE_PROXY_SECRET.invalid:7890",
                    "NODE_OPTIONS": "--trace-warnings",
                },
                clear=True,
            ):
                environment = client._child_environment(node_bin="/usr/bin/node")

        self.assertIn("--trace-warnings", environment["NODE_OPTIONS"])
        self.assertIn("--import=file:", environment["NODE_OPTIONS"])
        self.assertNotIn("PRIVATE_PROXY_SECRET", environment["NODE_OPTIONS"])
        self.assertTrue(environment["ASTERION_PI_UNDICI_URL"].startswith("file:"))
        self.assertNotIn(
            "PRIVATE_PROXY_SECRET", environment["ASTERION_PI_UNDICI_URL"]
        )

    def test_absent_proxy_preserves_node_options_without_proxy_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            with patch.dict(
                "os.environ",
                {"PATH": "/usr/bin", "NODE_OPTIONS": "--trace-warnings"},
                clear=True,
            ):
                environment = client._child_environment(node_bin="/usr/bin/node")

        self.assertEqual(environment["NODE_OPTIONS"], "--trace-warnings")
        self.assertNotIn("ASTERION_PI_UNDICI_URL", environment)

    def test_node_process_installs_proxy_dispatcher_before_application_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            marker = root / "proxy-installed"
            client = _client(root)
            node_bin = shutil.which("node")
            self.assertIsNotNone(node_bin)
            assert node_bin is not None
            with patch.dict(
                "os.environ",
                {
                    "PATH": "/usr/bin:/bin",
                    "HTTPS_PROXY": "http://proxy.invalid:7890",
                },
                clear=True,
            ):
                environment = client._child_environment(node_bin=node_bin)
            environment["ASTERION_PROXY_MARKER"] = str(marker)
            completed = subprocess.run(
                [node_bin, "--input-type=module", "--eval", "void 0"],
                env=environment,
                capture_output=True,
                check=False,
                text=True,
            )
            marker_text = marker.read_text(encoding="utf-8")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(marker_text, "installed")


if __name__ == "__main__":
    unittest.main()
