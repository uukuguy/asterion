from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.setup_prime_agent import resolve_prime_ecosystem_module


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PINNED_SOURCE = ROOT / "3th-party/prime-agent"
PINNED_SOURCE = DEFAULT_PINNED_SOURCE
MODULE_LOCK = (
    ROOT
    / "packages/typescript/prime-gateway/resources/prime-ecosystem-module-lock.json"
)
ARTIFACT_LOCK = (
    ROOT / "packages/typescript/prime-gateway/resources/prime-artifact-lock.json"
)
REAL_HARNESS = (
    ROOT / "tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs"
)
SCENARIO_PACKAGE = "lock-boundary"
MODEL_CREDENTIAL_VARIABLES = (
    "AI_GATEWAY_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_OAUTH_TOKEN",
    "AWS_ACCESS_KEY_ID",
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_PROFILE",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AZURE_OPENAI_API_KEY",
    "CEREBRAS_API_KEY",
    "CLOUDFLARE_API_KEY",
    "DEEPSEEK_API_KEY",
    "FIREWORKS_API_KEY",
    "GCLOUD_PROJECT",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_CLOUD_API_KEY",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_CLOUD_PROJECT",
    "GROQ_API_KEY",
    "KIMI_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "MISTRAL_API_KEY",
    "MOONSHOT_API_KEY",
    "OPENAI_API_KEY",
    "OPENCODE_API_KEY",
    "OPENROUTER_API_KEY",
    "PI_API_KEY",
    "PRIME_AGENT_TRACES_API_KEY",
    "PRIME_API_KEY",
    "PRIME_TEAM_ID",
    "PROXY_API_KEY",
    "SERPER_API_KEY",
    "XAI_API_KEY",
    "XIAOMI_API_KEY",
    "XIAOMI_TOKEN_PLAN_AMS_API_KEY",
    "XIAOMI_TOKEN_PLAN_CN_API_KEY",
    "XIAOMI_TOKEN_PLAN_SGP_API_KEY",
    "ZAI_API_KEY",
)
PUBLIC_KEYS = {
    "format",
    "model_credential_reads",
    "module_count",
    "observation_digest",
    "owned_process_count_after_close",
    "provider_operations",
    "real_prime_runtime",
    "scenario_package",
    "status",
}


def pinned_prime_source_root() -> Path:
    configured = os.environ.get("ASTERION_PRIME_SOURCE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_PINNED_SOURCE


def _closed_environment(private_home: Path) -> dict[str, str]:
    environment = {
        key: value
        for key in ("PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    environment["HOME"] = str(private_home)
    for key in MODEL_CREDENTIAL_VARIABLES:
        environment[key] = f"SENTINEL_MODEL_CREDENTIAL_{key}"
    return environment


def _node_22() -> Path | None:
    configured = os.environ.get("ASTERION_PRIME_NODE")
    candidates = [Path(configured)] if configured else []
    npm_environment = {
        key: value
        for key in ("HOME", "PATH", "SystemRoot", "TEMP", "TMP", "TMPDIR")
        if (value := os.environ.get(key)) is not None
    }
    try:
        completed = subprocess.run(
            (
                "npm",
                "exec",
                "--offline",
                "--yes",
                "--package=node@22",
                "--",
                "which",
                "node",
            ),
            cwd=ROOT,
            env=npm_environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if completed.returncode == 0 and completed.stdout.strip():
            candidates.append(Path(completed.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    for candidate in candidates:
        try:
            version = subprocess.run(
                (str(candidate), "--version"),
                cwd=ROOT,
                env=npm_environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if version.returncode == 0 and version.stdout.startswith("v22."):
                return candidate.resolve()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _command(node: Path, sealed_root: Path) -> tuple[str, ...]:
    return (
        str(node),
        str(REAL_HARNESS),
        "--module-lock",
        str(MODULE_LOCK),
        "--artifact-lock",
        str(ARTIFACT_LOCK),
        "--sealed-root",
        str(sealed_root),
        "--scenario-package",
        SCENARIO_PACKAGE,
    )


def _run_real_harness(node: Path) -> tuple[dict[str, object], str]:
    prime_source = pinned_prime_source_root()
    resolved = resolve_prime_ecosystem_module(prime_source, MODULE_LOCK)
    if resolved.bundle_path.name != "prime-ecosystem-module.mjs":
        raise AssertionError("real Prime ecosystem harness failed")
    with tempfile.TemporaryDirectory(
        prefix="asterion-prime-ecosystem-", dir="/tmp"
    ) as temporary:
        parent = Path(temporary).resolve()
        parent.chmod(0o700)
        sealed_root = parent / hashlib.sha256(b"empty-ecosystem").hexdigest()
        sealed_root.mkdir(mode=0o700)
        private_home = parent / "home"
        private_home.mkdir(mode=0o700)
        completed = subprocess.run(
            _command(node, sealed_root),
            cwd=ROOT,
            env=_closed_environment(private_home),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if completed.returncode != 0:
            raise AssertionError("real Prime ecosystem harness failed")
        stdout = completed.stdout
        try:
            report = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            raise AssertionError("real Prime ecosystem harness failed") from None
        if not isinstance(report, dict):
            raise AssertionError("real Prime ecosystem harness failed")
        if str(parent) in stdout or str(prime_source) in stdout:
            raise AssertionError("real Prime ecosystem harness leaked a private path")
    return report, stdout


@unittest.skipUnless(
    pinned_prime_source_root().is_dir(),
    "external pinned Prime ecosystem source is unavailable",
)
class TestPrimeEcosystemRealProcess(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = _node_22()
        if cls.node is None:
            raise unittest.SkipTest("an offline pinned Node 22 executable is unavailable")

    def test_real_harness_runs_twice_with_identical_public_digest(self) -> None:
        first, _ = _run_real_harness(self.node)
        second, _ = _run_real_harness(self.node)

        self.assertEqual(first["observation_digest"], second["observation_digest"])
        self.assertEqual(first["provider_operations"], 0)
        self.assertEqual(first["model_credential_reads"], 0)
        self.assertEqual(first["owned_process_count_after_close"], 0)

    def test_real_harness_emits_one_canonical_body_free_object(self) -> None:
        report, stdout = _run_real_harness(self.node)

        self.assertEqual(set(report), PUBLIC_KEYS)
        self.assertEqual(report["format"], "asterion.prime-ecosystem-observation/v1")
        self.assertEqual(report["scenario_package"], SCENARIO_PACKAGE)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["real_prime_runtime"])
        self.assertEqual(
            stdout,
            json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        )
        self.assertEqual(len(stdout.splitlines()), 1)
        self.assertNotIn("raw_observation", report)
        self.assertNotIn("stdout", report)
        self.assertNotIn("SENTINEL_MODEL_CREDENTIAL", stdout)

    def test_real_harness_rejects_extra_arguments_and_unsealed_roots(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="asterion-prime-ecosystem-invalid-", dir="/tmp"
        ) as temporary:
            parent = Path(temporary).resolve()
            private_home = parent / "home"
            private_home.mkdir(mode=0o700)
            unsealed = parent / "unsealed"
            unsealed.mkdir(mode=0o755)
            unsealed.chmod(0o755)
            commands = (
                (*_command(self.node, unsealed), "--unexpected", "value"),
                _command(self.node, unsealed),
            )
            for command in commands:
                with self.subTest(command=command[-2:]):
                    completed = subprocess.run(
                        command,
                        cwd=ROOT,
                        env=_closed_environment(private_home),
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertEqual(completed.stdout, "")
                    self.assertNotIn(str(parent), completed.stderr)
                    self.assertNotIn("SENTINEL_MODEL_CREDENTIAL", completed.stderr)


if __name__ == "__main__":
    unittest.main()
