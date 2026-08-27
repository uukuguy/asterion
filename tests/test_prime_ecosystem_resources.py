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
    PINNED_SOURCE,
    REAL_HARNESS,
    _node_22,
)
from tools.setup_prime_agent import resolve_prime_ecosystem_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/prime_ecosystem/v1/resources"
SCENARIO_PACKAGE = "resources"
FEATURE_IDS = [
    "ecosystem.collision-diagnostics",
    "ecosystem.context-files",
    "ecosystem.prompt-templates",
    "ecosystem.skills",
]
ASSERTION_IDS = [
    "resources.collision-digest",
    "resources.context-order",
    "resources.no-python-import",
    "resources.prompt-expansion",
    "resources.redacted-receipt",
    "resources.skill-identities",
]
PUBLIC_KEYS = {
    "assertion_ids",
    "collision_digest",
    "collision_count",
    "context_count",
    "feature_ids",
    "format",
    "model_credential_reads",
    "observation_digest",
    "owned_process_count_after_close",
    "prompt_count",
    "provider_operations",
    "resource_count",
    "scenario_package",
    "skill_count",
    "status",
}
EXPECTED_COLLISION_DIGEST = (
    "0816b1f15a7f0cf028a4de1f2b57d3c4c3c77f25d5b1b22560564b719be5a091"
)
RESOURCE_KINDS = {
    "context-global": ("context-file", "global"),
    "context-project": ("context-file", "project"),
    "prompt-collision-a": ("prompt-template", "project"),
    "prompt-collision-b": ("prompt-template", "project"),
    "prompt-resource": ("prompt-template", "project"),
    "skill-markdown": ("markdown-skill", "project"),
    "skill-python": ("python-skill", "project"),
}
BODY_SENTINELS = (
    "GLOBAL_CONTEXT_BODY_SENTINEL",
    "PROJECT_CONTEXT_BODY_SENTINEL",
    "COLLISION_PROMPT_A_BODY_SENTINEL",
    "COLLISION_PROMPT_B_BODY_SENTINEL",
    "MARKDOWN_SKILL_BODY_SENTINEL",
    "PYTHON_IMPORT_SENTINEL",
    "PYTHON_SKILL_BODY_SENTINEL",
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


def _fixture_files(resource_id: str) -> tuple[EcosystemPrivateFile, ...]:
    root = FIXTURE_ROOT / resource_id
    declarations = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        body = path.read_bytes()
        declarations.append(
            EcosystemPrivateFile(
                path.relative_to(root).as_posix(),
                _sha256(body),
                len(body),
            )
        )
    return tuple(declarations)


def _private_resource(resource_id: str) -> EcosystemPrivateResource:
    return EcosystemPrivateResource(
        resource_id,
        f"source-{resource_id}",
        _fixture_files(resource_id),
    )


def _portfolio_for(
    resources: tuple[EcosystemPrivateResource, ...],
):
    refs = []
    for private in resources:
        kind, scope = RESOURCE_KINDS[private.resource_id]
        refs.append(
            EcosystemResourceRef(
                private.resource_id,
                "1.0.0",
                kind,  # type: ignore[arg-type]
                scope,  # type: ignore[arg-type]
                EcosystemSourceRef(
                    private.source_id,
                    "local-child",
                    "1.0.0",
                    _canonical_digest(
                        {
                            "files": [
                                {
                                    "relative_path": item.relative_path,
                                    "sha256": item.sha256,
                                    "size_bytes": item.size_bytes,
                                }
                                for item in private.files
                            ],
                            "source_id": private.source_id,
                        }
                    ),
                ),
                _canonical_digest(
                    [
                        {
                            "relative_path": item.relative_path,
                            "sha256": item.sha256,
                            "size_bytes": item.size_bytes,
                        }
                        for item in private.files
                    ]
                ),
            )
        )
    return build_ecosystem_portfolio(
        portfolio_id="portfolio-resources",
        authority_id="authority-resources",
        authority_revision=1,
        resources=refs,
        registrations=(),
    )


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


def _command_with_artifact_lock(
    node: Path,
    sealed_root: Path,
    artifact_lock: Path,
    descriptor_manifest: Path,
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
        "--descriptor-manifest",
        str(descriptor_manifest),
    )


def _committed_artifact_lock() -> bytes:
    completed = subprocess.run(
        (
            "git",
            "show",
            "HEAD:packages/typescript/prime-gateway/resources/"
            "prime-artifact-lock.json",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        timeout=10,
    )
    if completed.returncode != 0 or not completed.stdout:
        raise AssertionError("real Prime ecosystem resource harness failed")
    return completed.stdout


def _descriptor_manifest_for(
    portfolio,
    *,
    mismatch: str | None = None,
) -> dict[str, object]:
    resources = []
    for resource in portfolio.resources:
        source_id = resource.source.source_id
        if mismatch == "source-id" and resource.resource_id == "prompt-collision-a":
            source_id = "source-prompt-collision-z"
        resources.append(
            {
                "content_sha256": resource.content_sha256,
                "kind": resource.kind,
                "resource_id": resource.resource_id,
                "scope": resource.scope,
                "source": {
                    "content_sha256": resource.source.content_sha256,
                    "kind": resource.source.kind,
                    "source_id": source_id,
                    "version": resource.source.version,
                },
                "version": resource.version,
            }
        )
    return {
        "format": "asterion.prime-ecosystem-resource-descriptor-manifest/v1",
        "portfolio_digest": portfolio.digest,
        "resources": resources,
    }


def _run_resource_harness_result(
    node: Path,
    *,
    mismatch: str | None = None,
) -> tuple[int, dict[str, object] | None, str]:
    private_resources = tuple(
        _private_resource(resource_id) for resource_id in sorted(RESOURCE_KINDS)
    )
    roots = {
        item.source_id: (FIXTURE_ROOT / item.resource_id).resolve()
        for item in private_resources
    }
    portfolio = _portfolio_for(private_resources)
    with tempfile.TemporaryDirectory(
        prefix="asterion-prime-ecosystem-resources-", dir="/tmp"
    ) as temporary:
        parent = Path(temporary).resolve()
        parent.chmod(0o700)
        artifact_lock = parent / "prime-artifact-lock.json"
        artifact_lock.write_bytes(_committed_artifact_lock())
        artifact_lock.chmod(0o600)
        descriptor_manifest = parent / "resource-descriptor-manifest.json"
        descriptor_manifest.write_text(
            json.dumps(
                _descriptor_manifest_for(portfolio, mismatch=mismatch),
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        descriptor_manifest.chmod(0o600)
        resolved = resolve_prime_ecosystem_module(
            PINNED_SOURCE,
            MODULE_LOCK,
            artifact_lock_path=artifact_lock,
        )
        if resolved.bundle_path.name != "prime-ecosystem-module.mjs":
            raise AssertionError("real Prime ecosystem resource harness failed")
        private_home = parent / "home"
        private_home.mkdir(mode=0o700)
        materializer = SealedEcosystemMaterializer(parent / "sealed")
        store = FileEcosystemPrivateSourceStore(
            roots=roots,
            resources=private_resources,
        )
        projection = materializer.materialize(portfolio, store)
        try:
            completed = subprocess.run(
                _command_with_artifact_lock(
                    node,
                    projection.root,
                    artifact_lock,
                    descriptor_manifest,
                ),
                cwd=ROOT,
                env=_closed_environment(private_home),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            materializer.close(projection)
        stdout = completed.stdout
        report = None
        if stdout:
            try:
                value = json.loads(stdout)
            except (json.JSONDecodeError, TypeError):
                value = None
            if isinstance(value, dict):
                report = value
        if (
            str(parent) in stdout
            or str(PINNED_SOURCE) in stdout
            or str(FIXTURE_ROOT) in stdout
        ):
            raise AssertionError("real Prime ecosystem resource harness leaked a path")
    return completed.returncode, report, stdout + completed.stderr


def _run_resource_harness(node: Path) -> tuple[dict[str, object], str]:
    returncode, report, output = _run_resource_harness_result(node)
    if returncode != 0 or report is None:
        raise AssertionError("real Prime ecosystem resource harness failed")
    return report, output


@unittest.skipUnless(
    PINNED_SOURCE.is_dir(), "external pinned Prime ecosystem source is unavailable"
)
class TestPrimeEcosystemResources(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = _node_22()
        if cls.node is None:
            raise unittest.SkipTest("an offline pinned Node 22 executable is unavailable")

    def test_real_prime_resource_receipt_is_safe_and_exact(self) -> None:
        report, stdout = _run_resource_harness(self.node)

        self.assertEqual(set(report), PUBLIC_KEYS)
        self.assertEqual(report["format"], "asterion.prime-ecosystem-observation/v1")
        self.assertEqual(report["scenario_package"], SCENARIO_PACKAGE)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["feature_ids"], FEATURE_IDS)
        self.assertEqual(report["assertion_ids"], ASSERTION_IDS)
        self.assertEqual(report["context_count"], 2)
        self.assertEqual(report["prompt_count"], 3)
        self.assertEqual(report["skill_count"], 2)
        self.assertEqual(report["collision_count"], 1)
        self.assertEqual(report["collision_digest"], EXPECTED_COLLISION_DIGEST)
        self.assertEqual(report["resource_count"], len(RESOURCE_KINDS))
        self.assertEqual(report["provider_operations"], 0)
        self.assertEqual(report["model_credential_reads"], 0)
        self.assertEqual(report["owned_process_count_after_close"], 0)
        self.assertEqual(
            stdout,
            json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        )
        for sentinel in BODY_SENTINELS:
            self.assertNotIn(sentinel, stdout)
        self.assertNotIn("SENTINEL_MODEL_CREDENTIAL", stdout)

    def test_resource_receipt_digest_is_two_process_deterministic(self) -> None:
        first, _ = _run_resource_harness(self.node)
        second, _ = _run_resource_harness(self.node)

        self.assertEqual(first["observation_digest"], second["observation_digest"])
        self.assertEqual(first["provider_operations"], 0)
        self.assertEqual(second["provider_operations"], 0)

    def test_resource_descriptor_identity_mismatch_is_rejected_redacted(self) -> None:
        returncode, report, output = _run_resource_harness_result(
            self.node,
            mismatch="source-id",
        )

        self.assertNotEqual(returncode, 0)
        self.assertIsNone(report)
        for sentinel in BODY_SENTINELS:
            self.assertNotIn(sentinel, output)
        self.assertNotIn("SENTINEL_MODEL_CREDENTIAL", output)


if __name__ == "__main__":
    unittest.main()
