from __future__ import annotations

import os
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
    def test_observation_values_exist_only_in_copied_child_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            observation_path = root / "SENTINEL-observation.ts"
            client = _client(root)
            client = PiRpcClient(
                package_dir=client.package_dir,
                cwd=client.cwd,
                agent_dir=client.agent_dir,
                provider=client.provider,
                model=client.model,
                tools=client.tools,
                show_tools=client.show_tools,
                system_prompt_file=None,
                append_system_prompt_file=None,
                extra_args=(),
                literal_extra_args=(),
                keep_session=False,
                node_max_old_space_size_mb=None,
                observation_extension_path=observation_path,
                observation_fd=37,
                observation_contract="SENTINEL-private-contract/v1",
            )
            inherited = {
                "PATH": "/usr/bin",
                "ASTERION_DCI_PATHLIGHT_PRIVATE_FD": "SENTINEL-attacker-fd",
                "ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT": "SENTINEL-attacker-contract",
            }
            with patch.dict("os.environ", inherited, clear=True):
                before = dict(os.environ)
                environment = client._child_environment(node_bin="/usr/bin/node")
                after = dict(os.environ)

        self.assertEqual(before, after)
        self.assertEqual(environment["ASTERION_DCI_PATHLIGHT_PRIVATE_FD"], "37")
        self.assertEqual(
            environment["ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT"],
            "SENTINEL-private-contract/v1",
        )
        self.assertNotIn(str(observation_path), environment.values())

    def test_absent_observation_configuration_scrubs_inherited_private_values(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = _client(Path(directory).resolve())
            inherited = {
                "PATH": "/usr/bin",
                "ASTERION_DCI_PATHLIGHT_PRIVATE_FD": "SENTINEL-attacker-fd",
                "ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT": "SENTINEL-attacker-contract",
            }
            with patch.dict("os.environ", inherited, clear=True):
                before = dict(os.environ)
                environment = client._child_environment(node_bin="/usr/bin/node")
                after = dict(os.environ)

        self.assertEqual(before, after)
        self.assertNotIn("ASTERION_DCI_PATHLIGHT_PRIVATE_FD", environment)
        self.assertNotIn("ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT", environment)

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
