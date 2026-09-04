"""Contract tests for the non-authoritative IPC parsing boundary."""

from __future__ import annotations

import json
import unittest

from asterion.applications.prime_agent.operator.authority_protocol import (
    AuthoritySession,
    PrimeP1AuthorityProtocolError,
    encode_frame,
)


KEY = bytes.fromhex("11" * 32)
SESSION = "a" * 32
CONTRACT = "b" * 64
RESOURCE_SET = "c" * 64
APPLICATION = "d" * 64


class TestPrimeP1AuthorityProtocol(unittest.TestCase):
    def test_frame_is_canonical_authenticated_and_has_exact_execute_shape(self) -> None:
        packet = encode_frame(
            key=KEY,
            session_id=SESSION,
            sequence=0,
            kind="execute",
            payload={
                "application_request_sha256": APPLICATION,
                "request_contract_sha256": CONTRACT,
                "run_id": "run-1",
            },
        )
        self.assertEqual(packet.decode("utf-8"), json.dumps(json.loads(packet), separators=(",", ":"), sort_keys=True))

        session = AuthoritySession(
            session_id=SESSION,
            session_key=KEY,
            request_contract_sha256=CONTRACT,
            resource_set_sha256=RESOURCE_SET,
        )
        frame = session.accept_supervisor_packet(packet)
        self.assertEqual(frame.kind, "execute")
        self.assertEqual(frame.payload["run_id"], "run-1")

    def test_rejects_replayed_execute_using_host_owned_ledger(self) -> None:
        packet = encode_frame(
            key=KEY,
            session_id=SESSION,
            sequence=0,
            kind="execute",
            payload={
                "application_request_sha256": APPLICATION,
                "request_contract_sha256": CONTRACT,
                "run_id": "run-1",
            },
        )
        session = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        session.accept_supervisor_packet(packet)
        with self.assertRaisesRegex(PrimeP1AuthorityProtocolError, "unavailable"):
            session.accept_supervisor_packet(packet)

    def test_rejects_noncanonical_tampered_or_unfixed_requests_without_secret_leakage(self) -> None:
        session = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        tampered = json.loads(
            encode_frame(
                key=KEY,
                session_id=SESSION,
                sequence=0,
                kind="execute",
                payload={
                    "application_request_sha256": APPLICATION,
                    "request_contract_sha256": CONTRACT,
                    "run_id": "run-1",
                },
            )
        )
        tampered["payload"]["prompt"] = "SENTINEL_PROMPT"
        packet = json.dumps(tampered, separators=(",", ":")).encode()
        with self.assertRaises(PrimeP1AuthorityProtocolError) as caught:
            session.accept_supervisor_packet(packet)
        self.assertEqual(str(caught.exception), "prime P1 authority IPC is unavailable")
        self.assertNotIn("SENTINEL_PROMPT", repr(caught.exception))

    def test_cancel_is_only_allowed_after_execute_and_once(self) -> None:
        rejected_session = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        cancel = encode_frame(KEY, SESSION, 1, "cancel", {})
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            rejected_session.accept_supervisor_packet(cancel)
        session = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        execute = encode_frame(
            KEY, SESSION, 0, "execute",
            {"run_id": "run-1", "request_contract_sha256": CONTRACT, "application_request_sha256": APPLICATION},
        )
        session.accept_supervisor_packet(execute)
        self.assertEqual(session.accept_supervisor_packet(cancel).kind, "cancel")
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            session.accept_supervisor_packet(cancel)


if __name__ == "__main__":
    unittest.main()
