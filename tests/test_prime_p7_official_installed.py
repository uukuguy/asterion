"""Installed-wheel official gameplay smoke test with a deterministic game."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FAKE_PI = ROOT / "tests/fixtures/asterion_prime/fake_pi_rpc.py"
EXTENSION = "asterion/applications/prime/resources/ipython-extension.mjs"
GAMEPLAY_ASSEMBLY = "asterion/applications/prime/assemblies/prime-arc-agi-3-gameplay.json"


def _run(
    command: tuple[str, ...], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _official_fake_pi_source() -> str:
    """Give the existing fake Pi one valid gameplay cell in both protocol spots."""
    cell = (
        'import p7_client; p7_client.act([{"name":"ACTION1","data":{}}] * 13); '
        'print("completed")'
    )
    source = FAKE_PI.read_text(encoding="utf-8")
    assert source.count("fixture.solve()") == 2
    source = source.replace(
        '"args": {"code": "fixture.solve()"}',
        '"args": {"code": ' + repr(cell) + "}",
    )
    # The JS source is itself held inside a Python triple-quoted string.
    js_literal = json.dumps(cell).replace("\\", "\\\\")
    source = source.replace(
        "{code: 'fixture.solve()'}",
        "{code: " + js_literal + "}",
    )
    source = source.replace(
        "result.content[0]?.text !== 'completed'",
        "!result.content[0]?.text.includes('completed')",
    )
    assert "fixture.solve()" not in source
    return source


_RUNNER = textwrap.dedent(
    """
    import asyncio
    import json
    from importlib import resources
    from pathlib import Path
    import sys

    from asterion.applications.prime.p7.game import ArcGameContract
    from asterion.applications.prime.p7.official_operator import (
        OfficialInvocation,
        _resolve_gameplay_application,
        _run_game,
    )

    class Engine:
        game_id = "ab12-12345678"
        guid = "fixture-guid"
        seed = 0
        win_levels = 1

        def __init__(self, marker):
            self.actions = 0
            self.marker = marker

        def observe(self):
            return {
                "available_actions": ["ACTION1"],
                "frame": [[[self.actions]]],
                "levels_completed": int(self.actions >= 13),
                "state": "WIN" if self.actions >= 13 else "NOT_FINISHED",
                "win_levels": self.win_levels,
            }

        def step(self, action, data=None):
            assert action == "ACTION1"
            self.actions += 1
            return self.observe()

        def close(self):
            self.marker.write_text("closed", encoding="utf-8")

    async def main():
        root = Path.cwd()
        marker = root / "closed"
        evidence = root / "evidence"
        evidence.mkdir()
        extension = Path(str(resources.files("asterion.applications.prime").joinpath(
            "resources/ipython-extension.mjs"
        ))).resolve()
        invocation = OfficialInvocation(
            root,
            {"DEEPSEEK_API_KEY": "fixture-only"},
            (sys.executable, str(root / "fake_pi_rpc.py"), str(Path(sys.argv[1]).resolve())),
            extension,
            "arc-fixture-only",
        )
        engine = Engine(marker)
        await _run_game(
            invocation,
            _resolve_gameplay_application(),
            evidence,
            engine,
            ArcGameContract("ab12-12345678", win_levels=1),
            "official-fixture",
        )
        trace = evidence / "official-fixture" / "trace" / "prime-trace.jsonl"
        entries = [json.loads(line) for line in trace.read_text().splitlines()]
        terminal = next(row for row in entries if row["kind"] == "arc.run.completed")
        print(json.dumps({
            "actions": engine.actions,
            "closed": marker.read_text(),
            "trace_entries": len(entries),
            "terminal": terminal["payload"]["terminal_reason"],
            "sealed": entries[-1]["kind"] == "trace.sealed",
        }, sort_keys=True))

    asyncio.run(main())
    """
)


class TestPrimeP7OfficialInstalled(unittest.TestCase):
    def test_installed_official_gameplay_runs_and_seals_evidence(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-p7-official-installed-", dir="/tmp"
        ) as temporary:
            root = Path(temporary).resolve()
            dist = root / "dist"
            dist.mkdir()
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            environment["UV_OFFLINE"] = "1"

            built = _run(
                ("uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            wheel = next(dist.glob("asterion-*.whl"))
            with zipfile.ZipFile(wheel) as archive:
                self.assertTrue(
                    {EXTENSION, GAMEPLAY_ASSEMBLY} <= set(archive.namelist())
                )

            virtual = root / "venv"
            created = _run(
                ("uv", "venv", "--seed", str(virtual)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            python = virtual / "bin" / "python"
            installed = _run(
                ("uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)),
                cwd=root,
                environment=environment,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)

            node = shutil.which("node")
            self.assertIsNotNone(node)
            loader_dir = (
                virtual
                / "lib"
                / f"python{sys.version_info.major}.{sys.version_info.minor}"
                / "site-packages"
                / "asterion"
                / "runtimes"
                / "resources"
            )
            earendil_host = Path(
                "/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent"
            )
            self.assertTrue(earendil_host.is_dir())
            link = loader_dir / "node_modules" / "@earendil-works" / "pi-coding-agent"
            link.parent.mkdir(parents=True)
            link.symlink_to(earendil_host)

            (root / "fake_pi_rpc.py").write_text(
                _official_fake_pi_source(), encoding="utf-8"
            )
            script = root / "run.py"
            script.write_text(_RUNNER, encoding="utf-8")
            result = _run(
                (str(python), "-I", str(script), str(Path(node).resolve())),
                cwd=root,
                environment={
                    **environment,
                    "ASTERION_TEST_FORBID_PRIME_SOURCE": "1",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(result.stdout)
            self.assertEqual(evidence["actions"], 13)
            self.assertEqual(evidence["closed"], "closed")
            self.assertEqual(evidence["terminal"], "game-won")
            self.assertTrue(evidence["sealed"])
            self.assertGreaterEqual(evidence["trace_entries"], 2)


if __name__ == "__main__":
    unittest.main()
