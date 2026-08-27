from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from asterion.control.ecosystem import (
    EcosystemPrivateFile,
    EcosystemPrivateResource,
    EcosystemRegistrationRef,
    EcosystemResourceRef,
    EcosystemSourceRef,
    build_ecosystem_portfolio,
)
from asterion.control.ecosystem_materialization import (
    FileEcosystemPrivateSourceStore,
    SealedEcosystemMaterializer,
)
from tests.test_prime_ecosystem_real_process import (
    MODEL_CREDENTIAL_VARIABLES,
    MODULE_LOCK,
    REAL_HARNESS,
    _node_22,
    pinned_prime_source_root,
)
from tests.test_prime_ecosystem_resources import _committed_artifact_lock
from tools.setup_prime_agent import resolve_prime_ecosystem_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/prime_ecosystem/v1/extensions"
SCENARIO_PACKAGE = "extensions"
FEATURE_IDS = [
    "ecosystem.custom-providers-models",
    "ecosystem.extension-state-commands",
    "ecosystem.extensions-lifecycle",
    "ecosystem.tools",
]
ASSERTION_IDS = [
    "extensions.command-state-digest",
    "extensions.lifecycle-order",
    "extensions.no-provider-invocation",
    "extensions.provider-model-lookup",
    "extensions.tool-output-digest",
]
PUBLIC_KEYS = {
    "assertion_ids",
    "command_count",
    "command_state_digest",
    "feature_ids",
    "failure_matrix_count",
    "failure_matrix_digest",
    "format",
    "lifecycle_count",
    "model_credential_reads",
    "observation_digest",
    "owned_process_count_after_close",
    "provider_model_count",
    "provider_operations",
    "reopened_command_state_digest",
    "reopened_nonterminal_status",
    "registration_count",
    "resource_count",
    "scenario_package",
    "status",
    "tool_count",
}
BODY_SENTINELS = (
    "ECOSYSTEM_PROVIDER_KEY_SHOULD_NOT_BE_READ",
    "SENTINEL_EXTENSION_ERROR",
    "HOSTILE_TOOL_OUTPUT",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return _sha256(encoded)


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


def _private_resource(source_root: Path) -> EcosystemPrivateResource:
    body = (source_root / "exact-extension.ts").read_bytes()
    return EcosystemPrivateResource(
        "exact-extension",
        "source-exact-extension",
        (
            EcosystemPrivateFile(
                "exact-extension.ts",
                _sha256(body),
                len(body),
            ),
        ),
    )


def _portfolio_for(private: EcosystemPrivateResource):
    files = [
        {
            "relative_path": item.relative_path,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in private.files
    ]
    resource = EcosystemResourceRef(
        private.resource_id,
        "1.0.0",
        "extension",
        "project",
        EcosystemSourceRef(
            private.source_id,
            "local-child",
            "1.0.0",
            _canonical_digest({"files": files, "source_id": private.source_id}),
        ),
        _canonical_digest(files),
    )
    return build_ecosystem_portfolio(
        portfolio_id="portfolio-extensions",
        authority_id="authority-extensions",
        authority_revision=1,
        resources=(resource,),
        registrations=(
            EcosystemRegistrationRef(
                "ecosystem-local:model-1",
                "provider-model",
                "exact-extension",
                "1.0.0",
            ),
            EcosystemRegistrationRef(
                "ecosystem-state",
                "command",
                "exact-extension",
                "1.0.0",
            ),
            EcosystemRegistrationRef(
                "ecosystem_echo",
                "tool",
                "exact-extension",
                "1.0.0",
            ),
        ),
    )


def _command_with_artifact_lock(
    node: Path,
    sealed_root: Path,
    artifact_lock: Path,
) -> tuple[str, ...]:
    return (
        str(node),
        str(REAL_HARNESS),
        "--module-lock",
        str(MODULE_LOCK),
        "--artifact-lock",
        str(artifact_lock),
        "--sealed-root",
        str(sealed_root),
        "--scenario-package",
        SCENARIO_PACKAGE,
    )


def _run_extension_harness(
    node: Path,
    *,
    source_root: Path = FIXTURE_ROOT,
) -> tuple[int, dict[str, object] | None, str]:
    private_resource = _private_resource(source_root)
    portfolio = _portfolio_for(private_resource)
    with tempfile.TemporaryDirectory(
        prefix="asterion-prime-ecosystem-extensions-", dir="/tmp"
    ) as temporary:
        parent = Path(temporary).resolve()
        parent.chmod(0o700)
        artifact_lock = parent / "prime-artifact-lock.json"
        artifact_lock.write_bytes(_committed_artifact_lock())
        artifact_lock.chmod(0o600)
        resolved = resolve_prime_ecosystem_module(
            pinned_prime_source_root(),
            MODULE_LOCK,
            artifact_lock_path=artifact_lock,
        )
        if resolved.bundle_path.name != "prime-ecosystem-module.mjs":
            raise AssertionError("real Prime ecosystem extension harness failed")
        private_home = parent / "home"
        private_home.mkdir(mode=0o700)
        materializer = SealedEcosystemMaterializer(parent / "sealed")
        store = FileEcosystemPrivateSourceStore(
            roots={private_resource.source_id: source_root.resolve()},
            resources=(private_resource,),
        )
        projection = materializer.materialize(portfolio, store)
        try:
            completed = subprocess.run(
                _command_with_artifact_lock(node, projection.root, artifact_lock),
                cwd=ROOT,
                env=_closed_environment(private_home),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            materializer.close(projection)
        report = None
        if completed.stdout:
            try:
                value = json.loads(completed.stdout)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, dict):
                report = value
        if str(parent) in completed.stdout or str(FIXTURE_ROOT) in completed.stdout:
            raise AssertionError("real Prime ecosystem extension harness leaked a path")
        return completed.returncode, report, completed.stdout + completed.stderr


@unittest.skipUnless(
    pinned_prime_source_root().is_dir(),
    "external pinned Prime ecosystem source is unavailable",
)
class TestPrimeEcosystemExtensions(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = _node_22()
        if cls.node is None:
            raise unittest.SkipTest("an offline pinned Node 22 executable is unavailable")

    def test_real_prime_extension_receipt_is_safe_and_exact(self) -> None:
        returncode, report, output = _run_extension_harness(self.node)

        self.assertEqual(returncode, 0)
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(set(report), PUBLIC_KEYS)
        self.assertEqual(report["format"], "asterion.prime-ecosystem-observation/v1")
        self.assertEqual(report["scenario_package"], SCENARIO_PACKAGE)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["feature_ids"], FEATURE_IDS)
        self.assertEqual(report["assertion_ids"], ASSERTION_IDS)
        self.assertEqual(report["resource_count"], 1)
        self.assertEqual(report["registration_count"], 3)
        self.assertEqual(report["lifecycle_count"], 1)
        self.assertEqual(report["command_count"], 1)
        self.assertEqual(report["tool_count"], 1)
        self.assertEqual(report["provider_model_count"], 1)
        self.assertRegex(report["command_state_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            report["reopened_command_state_digest"],
            report["command_state_digest"],
        )
        self.assertEqual(report["reopened_nonterminal_status"], "uncertain")
        self.assertEqual(report["failure_matrix_count"], 7)
        self.assertRegex(report["failure_matrix_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["model_credential_reads"], 0)
        self.assertEqual(report["owned_process_count_after_close"], 0)
        self.assertEqual(
            output,
            json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        )
        for sentinel in BODY_SENTINELS:
            self.assertNotIn(sentinel, output)
        self.assertNotIn("SENTINEL_MODEL_CREDENTIAL", output)

    def test_extension_receipt_digest_is_two_process_deterministic(self) -> None:
        first_code, first, _ = _run_extension_harness(self.node)
        second_code, second, _ = _run_extension_harness(self.node)

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        assert first is not None
        assert second is not None
        self.assertEqual(first["observation_digest"], second["observation_digest"])
        self.assertEqual(first["provider_operations"], 0)
        self.assertEqual(second["provider_operations"], 0)

    def test_extension_harness_rejects_hostile_variants_redacted(self) -> None:
        original = (FIXTURE_ROOT / "exact-extension.ts").read_text(encoding="utf-8")
        variants = {
            "hostile-tool-output": original.replace(
                "echo:${params.message}",
                "HOSTILE_TOOL_OUTPUT:${params.message}",
            ),
            "sentinel-error": original.replace(
                'extensionState.events.push("shutdown");',
                'throw new Error("SENTINEL_EXTENSION_ERROR");',
            ),
            "teardown-throw": original.replace(
                "pi.on(\"session_shutdown\", () => {",
                "pi.on(\"session_shutdown\", () => { throw new Error(\"SENTINEL_EXTENSION_ERROR\");",
            ),
            "state-append-failure": original.replace(
                'pi.appendEntry("ecosystem-state", { args });',
                'throw new Error("SENTINEL_EXTENSION_ERROR");',
            ),
            "provider-invocation-attempt": original.replace(
                'baseUrl: "http://127.0.0.1/unused",',
                'baseUrl: "http://127.0.0.1/unused/ECOSYSTEM_PROVIDER_KEY_SHOULD_NOT_BE_READ",',
            ),
        }
        for name, body in variants.items():
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory(
                    prefix="asterion-extension-variant-", dir="/tmp"
                ) as temporary:
                    source_root = Path(temporary).resolve()
                    source_root.chmod(0o700)
                    (source_root / "exact-extension.ts").write_text(
                        body,
                        encoding="utf-8",
                    )
                    returncode, report, output = _run_extension_harness(
                        self.node,
                        source_root=source_root,
                    )
                self.assertNotEqual(returncode, 0)
                self.assertIsNone(report)
                for sentinel in BODY_SENTINELS:
                    self.assertNotIn(sentinel, output)


if __name__ == "__main__":
    unittest.main()
