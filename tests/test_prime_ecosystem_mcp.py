from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
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
from tests.test_prime_ecosystem_resources import _committed_artifact_lock
from tools.setup_prime_agent import resolve_prime_ecosystem_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/prime_ecosystem/v1/mcp"
LOCAL_SERVER = FIXTURE_ROOT / "local-server.mjs"
SCENARIO_PACKAGE = "mcp"
FEATURE_IDS = ["ecosystem.mcp"]
ASSERTION_IDS = [
    "mcp.exact-local-server",
    "mcp.manager-and-oauth-surface",
    "mcp.no-provider-invocation",
    "mcp.redacted-receipt",
]
PUBLIC_KEYS = {
    "assertion_ids",
    "feature_ids",
    "format",
    "mcp_count",
    "mcp_surface_digest",
    "model_credential_reads",
    "observation_digest",
    "owned_process_count_after_close",
    "provider_operations",
    "resource_count",
    "scenario_package",
    "status",
}
BODY_SENTINELS = (
    "SENTINEL_MODEL_CREDENTIAL",
    "opaque-mcp-refresh-token",
    str(FIXTURE_ROOT),
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_digest(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


EXPECTED_PRIVATE_MCP_OBSERVATION = {
    "challenge_count": 1,
    "config_url_digest": _canonical_digest("http://127.0.0.1/owned-mcp"),
    "credential_refresh_count": 1,
    "initialize_count": 2,
    "list_count": 1,
    "manager_status_count": 1,
    "manager_status_enabled_after_refresh": True,
    "manager_status_uses_oauth": True,
    "mcp_count": 1,
    "mcp_manager_available": True,
    "oauth_available": True,
    "provider_operations": 0,
    "replay_refresh_count": 0,
    "shutdown_count": 1,
}


def _private_resource() -> EcosystemPrivateResource:
    files = []
    for path in sorted(item for item in FIXTURE_ROOT.rglob("*") if item.is_file()):
        body = path.read_bytes()
        files.append(
            EcosystemPrivateFile(
                path.relative_to(FIXTURE_ROOT).as_posix(),
                _sha256(body),
                len(body),
            )
        )
    return EcosystemPrivateResource("local-server", "source-local-mcp", tuple(files))


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
        "mcp-server",
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
        portfolio_id="portfolio-mcp",
        authority_id="authority-mcp",
        authority_revision=1,
        resources=(resource,),
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
    mcp_channel_command: tuple[str, ...],
) -> tuple[str, ...]:
    return (
        str(node),
        str(REAL_HARNESS),
        "--module-lock",
        str(MODULE_LOCK),
        "--artifact-lock",
        str(artifact_lock),
        "--mcp-channel-command",
        json.dumps(mcp_channel_command),
        "--sealed-root",
        str(sealed_root),
        "--scenario-package",
        SCENARIO_PACKAGE,
    )


def _write_mcp_channel_bridge(parent: Path, node: Path) -> tuple[str, ...]:
    bridge = parent / "owned-mcp-channel.py"
    bridge.write_text(
        textwrap.dedent(
            """
            from __future__ import annotations

            import json
            import sys
            from pathlib import Path

            sys.path.insert(0, sys.argv[4])

            from asterion.control.ecosystem_mcp import (
                EcosystemMcpDescriptor,
                OwnedMcpFixtureService,
            )


            SERVER_ID = "ecosystem-mcp-local"
            LEASE_ID = "mcp-lease:local"


            def emit(value: dict[str, object]) -> None:
                sys.stdout.write(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\\n")
                sys.stdout.flush()


            def main() -> int:
                private_root = Path(sys.argv[1])
                node = sys.argv[2]
                local_server = sys.argv[3]
                service = OwnedMcpFixtureService(private_root)
                descriptor = EcosystemMcpDescriptor(
                    server_id=SERVER_ID,
                    version="1.0.0",
                    command=(node, local_server),
                    credential_lease_id=LEASE_ID,
                )
                channel = None
                for line in sys.stdin:
                    try:
                        message = json.loads(line)
                        payload = message.get("payload", {})
                        message_type = message.get("type")
                        if message_type == "server_id":
                            emit({"server_id": SERVER_ID})
                        elif message_type == "initialize":
                            if channel is not None:
                                raise RuntimeError("duplicate initialize")
                            if payload.get("lease_id") != LEASE_ID:
                                raise RuntimeError("wrong lease")
                            channel = service.open_channel(descriptor)
                            emit(channel.initialize_challenge())
                        elif message_type == "refresh":
                            if (
                                channel is None
                                or payload.get("lease_id") != LEASE_ID
                                or payload.get("challenge_digest") != descriptor.challenge_digest
                            ):
                                raise RuntimeError("refresh rejected")
                            emit({"credential": channel.refresh()})
                        elif message_type == "initialize_with_credential":
                            if channel is None or not isinstance(payload.get("credential"), str):
                                raise RuntimeError("credential rejected")
                            emit(channel.initialize_with_credential(payload["credential"]))
                        elif message_type == "list":
                            if channel is None:
                                raise RuntimeError("missing channel")
                            emit(channel.list())
                        elif message_type == "shutdown":
                            if channel is None:
                                raise RuntimeError("missing channel")
                            emit(channel.shutdown().to_public_mapping())
                        elif message_type == "replay":
                            if channel is None:
                                raise RuntimeError("missing channel")
                            emit(channel.replay().to_public_mapping())
                        else:
                            raise RuntimeError("unknown message")
                    except Exception:
                        emit({"error": "MCP fixture failed"})
                        return 1
                return 0


            if __name__ == "__main__":
                raise SystemExit(main())
            """
        ),
        encoding="utf-8",
    )
    bridge.chmod(0o700)
    return (
        sys.executable,
        str(bridge),
        str(parent / "owned-channel"),
        str(node),
        str(LOCAL_SERVER),
        str(ROOT),
    )


def _run_mcp_harness(node: Path) -> tuple[int, dict[str, object] | None, str]:
    private_resource = _private_resource()
    portfolio = _portfolio_for(private_resource)
    with tempfile.TemporaryDirectory(prefix="asterion-prime-ecosystem-mcp-", dir="/tmp") as temporary:
        parent = Path(temporary).resolve()
        parent.chmod(0o700)
        artifact_lock = parent / "prime-artifact-lock.json"
        artifact_lock.write_bytes(_committed_artifact_lock())
        artifact_lock.chmod(0o600)
        mcp_channel_command = _write_mcp_channel_bridge(parent, node)
        resolved = resolve_prime_ecosystem_module(
            PINNED_SOURCE,
            MODULE_LOCK,
            artifact_lock_path=artifact_lock,
        )
        if resolved.bundle_path.name != "prime-ecosystem-module.mjs":
            raise AssertionError("real Prime ecosystem MCP harness failed")
        private_home = parent / "home"
        private_home.mkdir(mode=0o700)
        materializer = SealedEcosystemMaterializer(parent / "sealed")
        store = FileEcosystemPrivateSourceStore(
            roots={private_resource.source_id: FIXTURE_ROOT.resolve()},
            resources=(private_resource,),
        )
        projection = materializer.materialize(portfolio, store)
        try:
            completed = subprocess.run(
                _command_with_artifact_lock(
                    node,
                    projection.root,
                    artifact_lock,
                    mcp_channel_command,
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
    report = None
    if completed.stdout:
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            report = value
    if str(FIXTURE_ROOT) in completed.stdout or str(FIXTURE_ROOT) in completed.stderr:
        raise AssertionError("real Prime ecosystem MCP harness leaked a source path")
    return completed.returncode, report, completed.stdout + completed.stderr


@unittest.skipUnless(
    PINNED_SOURCE.is_dir(), "external pinned Prime ecosystem source is unavailable"
)
class TestPrimeEcosystemMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = _node_22()
        if cls.node is None:
            raise unittest.SkipTest("an offline pinned Node 22 executable is unavailable")

    def test_real_prime_mcp_receipt_is_safe_exact_and_deterministic(self) -> None:
        first_code, first, first_output = _run_mcp_harness(self.node)
        second_code, second, second_output = _run_mcp_harness(self.node)

        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertEqual(set(first), PUBLIC_KEYS)
        self.assertEqual(first["format"], "asterion.prime-ecosystem-observation/v1")
        self.assertEqual(first["scenario_package"], SCENARIO_PACKAGE)
        self.assertEqual(first["status"], "PASS")
        self.assertEqual(first["feature_ids"], FEATURE_IDS)
        self.assertEqual(first["assertion_ids"], ASSERTION_IDS)
        self.assertEqual(first["mcp_count"], 1)
        self.assertEqual(first["resource_count"], 1)
        self.assertEqual(first["provider_operations"], 0)
        self.assertEqual(first["model_credential_reads"], 0)
        self.assertEqual(first["owned_process_count_after_close"], 0)
        self.assertRegex(first["mcp_surface_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            first["mcp_surface_digest"],
            _canonical_digest(EXPECTED_PRIVATE_MCP_OBSERVATION),
        )
        self.assertEqual(first["observation_digest"], second["observation_digest"])
        self.assertEqual(
            first_output,
            json.dumps(first, sort_keys=True, separators=(",", ":")) + "\n",
        )
        for output in (first_output, second_output):
            for sentinel in BODY_SENTINELS:
                self.assertNotIn(sentinel, output)


if __name__ == "__main__":
    unittest.main()
