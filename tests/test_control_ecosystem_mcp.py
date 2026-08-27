from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from asterion.control.ecosystem_mcp import (
    MCP_CHALLENGE_DIGEST,
    EcosystemMcpDescriptor,
    EcosystemMcpError,
    OwnedMcpFixtureService,
)
from tests.test_prime_ecosystem_real_process import _node_22


ROOT = Path(__file__).resolve().parents[1]
LOCAL_SERVER = ROOT / "tests/fixtures/prime_ecosystem/v1/mcp/local-server.mjs"
SERVER_ID = "ecosystem-mcp-local"
LEASE_ID = "mcp-lease:local"
BODY_SENTINELS = (
    "SENTINEL_MODEL_CREDENTIAL",
    "opaque-mcp-refresh-token",
    str(LOCAL_SERVER),
)


class _FlipAfterChallengeCancellation:
    def __init__(self) -> None:
        self._reads = 0

    @property
    def cancelled(self) -> bool:
        self._reads += 1
        return self._reads >= 2


def _duplicate_refresh(temporary: str, descriptor: EcosystemMcpDescriptor) -> None:
    service = OwnedMcpFixtureService(temporary)
    service.refresh(descriptor.credential_lease_id, descriptor.challenge_digest)
    service.refresh(descriptor.credential_lease_id, descriptor.challenge_digest)


@unittest.skipUnless(LOCAL_SERVER.is_file(), "local MCP fixture server is unavailable")
class TestOwnedMcpFixtureService(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = _node_22()
        if cls.node is None:
            raise unittest.SkipTest("an offline pinned Node 22 executable is unavailable")

    def _descriptor(self, *extra: str, server_id: str = SERVER_ID, max_output_bytes: int = 8192) -> EcosystemMcpDescriptor:
        return EcosystemMcpDescriptor(
            server_id=server_id,
            version="1.0.0",
            command=(str(self.node), str(LOCAL_SERVER), *extra),
            credential_lease_id=LEASE_ID,
            max_output_bytes=max_output_bytes,
        )

    def test_direct_launch_refresh_list_shutdown_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-mcp-owned-", dir="/tmp") as temporary:
            service = OwnedMcpFixtureService(temporary)
            session = service.start(self._descriptor())
            replayed = service.replay(session)
            self.assertEqual(stat.S_IMODE(session.discovery_path.stat().st_mode), 0o600)
            receipt = service.close(session)

        self.assertEqual(replayed.credential_refresh_count, 1)
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(receipt.server_id, SERVER_ID)
        self.assertEqual(receipt.challenge_digest, MCP_CHALLENGE_DIGEST)
        self.assertEqual(receipt.credential_refresh_count, 1)
        self.assertEqual(receipt.initialize_count, 2)
        self.assertEqual(receipt.list_count, 1)
        self.assertEqual(receipt.provider_operations, 0)
        self.assertEqual(receipt.model_credential_reads, 0)
        self.assertEqual(receipt.owned_process_count_after_close, 0)
        self.assertRegex(receipt.discovery_digest, r"^[0-9a-f]{64}$")
        public = json.dumps(receipt.to_public_mapping(), sort_keys=True)
        public_session = repr(session)
        for sentinel in BODY_SENTINELS:
            self.assertNotIn(sentinel, public)
            self.assertNotIn(sentinel, public_session)

    def test_failure_matrix_rejects_unsafe_or_drifting_inputs_redacted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-mcp-failures-", dir="/tmp") as temporary:
            cases = {
                "relative-command": lambda: EcosystemMcpDescriptor(
                    server_id=SERVER_ID,
                    version="1.0.0",
                    command=("node", str(LOCAL_SERVER)),
                    credential_lease_id=LEASE_ID,
                ),
                "wrong-server-identity": lambda: OwnedMcpFixtureService(temporary).start(
                    self._descriptor(server_id="ecosystem-mcp-other")
                ),
                "wrong-challenge": lambda: EcosystemMcpDescriptor(
                    server_id=SERVER_ID,
                    version="1.0.0",
                    command=(str(self.node), str(LOCAL_SERVER)),
                    credential_lease_id=LEASE_ID,
                    challenge_digest="f" * 64,
                ),
                "duplicate-refresh": lambda: _duplicate_refresh(temporary, self._descriptor()),
                "output-cap": lambda: OwnedMcpFixtureService(temporary).start(
                    self._descriptor("--large-output", max_output_bytes=128)
                ),
            }
            for name, trigger in cases.items():
                with self.subTest(name=name), self.assertRaises(EcosystemMcpError) as raised:
                    trigger()
                rendered = repr(raised.exception)
                for sentinel in BODY_SENTINELS:
                    self.assertNotIn(sentinel, rendered)

    def test_refresh_requires_bound_lease_and_rejects_replay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-mcp-refresh-", dir="/tmp") as temporary:
            service = OwnedMcpFixtureService(temporary)
            with self.assertRaises(EcosystemMcpError):
                service.refresh(LEASE_ID, MCP_CHALLENGE_DIGEST)

            session = service.start(self._descriptor())
            service.close(session)
            with self.assertRaises(EcosystemMcpError):
                service.refresh(LEASE_ID, MCP_CHALLENGE_DIGEST)

    def test_cancellation_kills_and_reaps_child_without_refresh(self) -> None:
        with tempfile.TemporaryDirectory(prefix="asterion-mcp-cancel-", dir="/tmp") as temporary:
            service = OwnedMcpFixtureService(temporary)
            session = service.start(
                self._descriptor(),
                cancellation=_FlipAfterChallengeCancellation(),
            )
            receipt = service.close(session)

        self.assertEqual(receipt.status, "cancelled")
        self.assertEqual(receipt.credential_refresh_count, 0)
        self.assertEqual(receipt.initialize_count, 1)
        self.assertEqual(receipt.list_count, 0)
        self.assertEqual(receipt.owned_process_count_after_close, 0)
        self.assertIsNone(session.process)


if __name__ == "__main__":
    unittest.main()
