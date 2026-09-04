"""Contract tests for the non-authoritative IPC parsing boundary."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
import hashlib
import hmac

from asterion.applications.prime_agent.operator.authority_protocol import (
    AuthoritySession,
    PrimeP1AuthorityProtocolError,
    SupervisorSession,
    decode_frame,
    encode_frame,
)


KEY = bytes.fromhex("11" * 32)
SESSION = "a" * 64
CONTRACT = "b" * 64
RESOURCE_SET = "c" * 64
APPLICATION = "d" * 64
RECEIPT_KEY = bytes.fromhex("22" * 32)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _receipt() -> dict[str, object]:
    receipt: dict[str, object] = {
        "format": "asterion.prime-p1-authority-receipt/v1",
        "status": "PASS",
        "reason_code": "completed",
        "run_id": "run-1",
        "session_id": SESSION,
        "request_contract_sha256": CONTRACT,
        "application_request_sha256": APPLICATION,
        "authority": {
            "authority_version": "1.0.0",
            "authority_executable_sha256": "1" * 64,
            "operator_config_binding_hmac_sha256": "2" * 64,
            "production_resource_set_sha256": RESOURCE_SET,
            "receipt_key_id": "key-1",
        },
        "identity": {
            "provider_id": "prime-agent",
            "application_id": "prime.ipython-coding",
            "application_version": "1.0.0",
            "assembly_ref": "prime.ipython-coding@1.0.0",
            "assembly_sha256": "3" * 64,
            "package_ref": "prime-agent@1.0.0",
            "package_manifest_sha256": "4" * 64,
            "implementation_ref": "prime.ipython-coding@1.0.0",
            "runtime_id": "prime.agent",
            "prime_sdk_ref": "prime-agent@0.7.1",
            "source_sha256": "5" * 64,
            "build_input_sha256": "6" * 64,
            "image_config_digest": "sha256:" + "7" * 64,
            "workload_sha256": "8" * 64,
            "starter_sha256": "9" * 64,
            "oracle_sha256": "a" * 64,
            "seccomp_sha256": "b" * 64,
        },
        "model_accounting": {
            "request_count": 1,
            "input_bytes": 1,
            "output_bytes": 1,
            "provider_reported_input_tokens": 1,
            "provider_reported_output_tokens": 1,
            "charged_cost_microunits": 1,
            "cost_basis": "reserved-ceiling",
            "max_requests": 1,
            "max_input_bytes": 1,
            "max_output_bytes": 1,
            "max_input_tokens": 1,
            "max_output_tokens": 1,
            "max_cost_microunits": 1,
            "deadline_milliseconds": 1,
            "request_sha256": "c" * 64,
            "response_sha256": "d" * 64,
            "broker_receipt_sha256": "e" * 64,
            "transport_reaped": True,
        },
        "worker_evidence": {
            "worker_count": 1,
            "container_id_sha256": "f" * 64,
            "model_tool_calls": 1,
            "ipython_tool_calls": 1,
            "sent_cell_sha256": "0" * 64,
            "initial_workspace_sha256": "1" * 64,
            "post_workspace_sha256": "2" * 64,
            "initial_oracle_passed": False,
            "final_oracle_passed": True,
            "mutation_after_model_response": True,
            "broker_quiesced": True,
            "container_removed": True,
            "daemon_absence_verified": True,
        },
        "causal_evidence": {
            "event_count": 1,
            "first_sequence": 1,
            "last_sequence": 1,
            "event_chain_sha256": "3" * 64,
            "result_projection_sha256": "4" * 64,
        },
    }
    digest = hashlib.sha256(
        b"asterion.prime-p1-authority-receipt/v1\0" + _canonical(receipt)
    ).hexdigest()
    receipt["evidence_id"] = "prime-p1-" + digest
    receipt["receipt_sha256"] = digest
    receipt["receipt_hmac_sha256"] = hmac.new(
        RECEIPT_KEY,
        b"asterion.prime-p1-authority-receipt/v1\0" + _canonical(receipt),
        "sha256",
    ).hexdigest()
    return receipt


def _resign(receipt: dict[str, object]) -> None:
    unsigned = {name: value for name, value in receipt.items() if name not in {"evidence_id", "receipt_sha256", "receipt_hmac_sha256"}}
    digest = hashlib.sha256(b"asterion.prime-p1-authority-receipt/v1\0" + _canonical(unsigned)).hexdigest()
    receipt["evidence_id"] = "prime-p1-" + digest
    receipt["receipt_sha256"] = digest
    receipt["receipt_hmac_sha256"] = hmac.new(RECEIPT_KEY, b"asterion.prime-p1-authority-receipt/v1\0" + _canonical({**unsigned, "evidence_id": receipt["evidence_id"], "receipt_sha256": digest}), "sha256").hexdigest()


class TestPrimeP1AuthorityProtocol(unittest.TestCase):
    def _live_pair(self, *, authority_key: bool = False) -> tuple[AuthoritySession, SupervisorSession]:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET, receipt_hmac_key=RECEIPT_KEY if authority_key else None)
        supervisor = SupervisorSession(SESSION, KEY, CONTRACT)
        supervisor.accept_authority_packet(authority.ready_packet())
        authority.accept_supervisor_packet(supervisor.execute_packet("run-1", APPLICATION))
        return authority, supervisor
    def test_authority_requires_one_ready_before_execute_and_poison_latches(self) -> None:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        execute = encode_frame(KEY, SESSION, 0, "execute", {"run_id": "run-1", "request_contract_sha256": CONTRACT, "application_request_sha256": APPLICATION})
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.accept_supervisor_packet(execute)
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.ready_packet()

    def test_supervisor_rejects_second_ready_and_latches_failure(self) -> None:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        supervisor = SupervisorSession(SESSION, KEY, CONTRACT)
        ready = authority.ready_packet()
        supervisor.accept_authority_packet(ready)
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            supervisor.accept_authority_packet(ready)
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            supervisor.execute_packet("run-1", APPLICATION)

    def test_authority_rejects_second_ready(self) -> None:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        authority.ready_packet()
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.ready_packet()

    def test_shared_native_json_tree_is_not_a_cycle(self) -> None:
        shared = {"value": [1]}
        packet = encode_frame(KEY, SESSION, 1, "terminal", {"left": shared, "right": shared})
        self.assertEqual(decode_frame(packet, KEY).kind, "terminal")
    def test_supervisor_keeps_receipt_hmac_key_out_of_its_api(self) -> None:
        with self.assertRaises(TypeError):
            SupervisorSession(SESSION, KEY, CONTRACT, receipt_hmac_key=RECEIPT_KEY)  # type: ignore[call-arg]

    def test_cancelled_sessions_only_accept_cancelled_receipts(self) -> None:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET, receipt_hmac_key=RECEIPT_KEY)
        supervisor = SupervisorSession(SESSION, KEY, CONTRACT)
        supervisor.accept_authority_packet(authority.ready_packet())
        authority.accept_supervisor_packet(supervisor.execute_packet("run-1", APPLICATION))
        authority.accept_supervisor_packet(supervisor.cancel_packet())
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet(_receipt())

    def test_authority_terminal_signing_requires_the_receipt_key(self) -> None:
        authority, _ = self._live_pair()
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet(_receipt())

    def test_rejects_unbound_receipt_run_request_and_resource(self) -> None:
        for field, value in (("run_id", "run-2"), ("application_request_sha256", "not-a-digest"), ("reason_code", "invented"), ("status", "FAIL")):
            with self.subTest(field=field):
                _, supervisor = self._live_pair()
                receipt = _receipt()
                receipt[field] = value
                _resign(receipt)
                with self.assertRaises(PrimeP1AuthorityProtocolError):
                    supervisor.accept_authority_packet(encode_frame(KEY, SESSION, 1, "terminal", receipt))
        receipt = _receipt()
        receipt["authority"]["production_resource_set_sha256"] = "0" * 64  # type: ignore[index]
        _resign(receipt)
        authority, supervisor = self._live_pair(authority_key=True)
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            supervisor.accept_authority_packet(encode_frame(KEY, SESSION, 1, "terminal", receipt))
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet(receipt)

    def test_rejects_pass_after_cancel_limits_and_bad_authority_hmac(self) -> None:
        authority, supervisor = self._live_pair(authority_key=True)
        authority.accept_supervisor_packet(supervisor.cancel_packet())
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet(_receipt())
        _, supervisor = self._live_pair()
        supervisor.cancel_packet()
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            supervisor.accept_authority_packet(
                encode_frame(KEY, SESSION, 1, "terminal", _receipt())
            )
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            supervisor.accept_authority_packet(
                encode_frame(KEY, SESSION, 1, "terminal", _receipt())
            )
        for field, value in (("input_bytes", 2), ("charged_cost_microunits", 0)):
            with self.subTest(field=field):
                _, supervisor = self._live_pair()
                receipt = _receipt()
                receipt["model_accounting"][field] = value  # type: ignore[index]
                _resign(receipt)
                with self.assertRaises(PrimeP1AuthorityProtocolError):
                    supervisor.accept_authority_packet(encode_frame(KEY, SESSION, 1, "terminal", receipt))
        authority, _ = self._live_pair(authority_key=True)
        receipt = _receipt()
        receipt["receipt_hmac_sha256"] = "0" * 64
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet(receipt)

    def test_rejects_non_json_constants_and_deeply_nested_frames(self) -> None:
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            encode_frame(KEY, SESSION, 1, "terminal", {"value": float("nan")})
        value: object = []
        for _ in range(40):
            value = [value]
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            encode_frame(KEY, SESSION, 1, "terminal", {"value": value})
        payload = '{"value":' + "[" * 40 + "0" + "]" * 40 + "}"
        body = f'{{"kind":"terminal","payload":{payload},"protocol":"asterion.prime-p1-authority-ipc/v1","sequence":1,"session_id":"{SESSION}"}}'.encode()
        mac = hmac.new(KEY, b"asterion.prime-p1-authority-ipc/v1\0" + body, "sha256").hexdigest()
        packet = b'{"frame_hmac_sha256":"' + mac.encode() + b'",' + body[1:]
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            decode_frame(packet, KEY)

    def test_encoder_rejects_cycles_and_non_native_json_values(self) -> None:
        cycle: list[object] = []
        cycle.append(cycle)
        for payload in ({"value": cycle}, {"value": object()}):
            with self.subTest(payload=repr(payload)):
                with self.assertRaises(PrimeP1AuthorityProtocolError):
                    encode_frame(KEY, SESSION, 1, "terminal", payload)

    def test_authority_does_not_emit_an_unsigned_terminal_receipt(self) -> None:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        supervisor = SupervisorSession(SESSION, KEY, CONTRACT)
        supervisor.accept_authority_packet(authority.ready_packet())
        authority.accept_supervisor_packet(supervisor.execute_packet("run-1", APPLICATION))
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet(_receipt())
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
        self.assertEqual(
            packet.decode("utf-8"),
            json.dumps(json.loads(packet), separators=(",", ":"), sort_keys=True),
        )

        session = AuthoritySession(
            session_id=SESSION,
            session_key=KEY,
            request_contract_sha256=CONTRACT,
            resource_set_sha256=RESOURCE_SET,
        )
        session.ready_packet()
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
        session.ready_packet()
        session.accept_supervisor_packet(packet)
        with self.assertRaisesRegex(PrimeP1AuthorityProtocolError, "unavailable"):
            session.accept_supervisor_packet(packet)

    def test_rejects_noncanonical_tampered_or_unfixed_requests_without_secret_leakage(
        self,
    ) -> None:
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
        session.ready_packet()
        execute = encode_frame(
            KEY,
            SESSION,
            0,
            "execute",
            {
                "run_id": "run-1",
                "request_contract_sha256": CONTRACT,
                "application_request_sha256": APPLICATION,
            },
        )
        session.accept_supervisor_packet(execute)
        self.assertEqual(session.accept_supervisor_packet(cancel).kind, "cancel")
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            session.accept_supervisor_packet(cancel)

    def test_rejects_128_bit_session_identifiers(self) -> None:
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            encode_frame(KEY, "a" * 32, 0, "cancel", {})

    def test_decoded_payload_is_deeply_immutable(self) -> None:
        packet = encode_frame(
            KEY,
            SESSION,
            0,
            "execute",
            {
                "run_id": "run-1",
                "request_contract_sha256": CONTRACT,
                "application_request_sha256": APPLICATION,
            },
        )
        frame = decode_frame(packet, KEY)
        self.assertIsInstance(frame.payload, Mapping)
        with self.assertRaises(TypeError):
            frame.payload["run_id"] = "replaced"  # type: ignore[index]

    def test_rejects_oversized_outgoing_and_hmac_tampering(self) -> None:
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            encode_frame(KEY, SESSION, 1, "terminal", {"padding": "x" * 8_192})
        self.assertGreater(len(b"x" * 8_193), 8_192)
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            decode_frame(b"x" * 8_193, KEY)
        value = json.loads(encode_frame(KEY, SESSION, 1, "cancel", {}))
        supplied = value["frame_hmac_sha256"]
        value["frame_hmac_sha256"] = supplied[:-1] + (
            "0" if supplied[-1] != "0" else "1"
        )
        packet = json.dumps(value, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            decode_frame(packet, KEY)

    def test_supervisor_accepts_exact_ready_execute_optional_cancel_and_one_terminal(
        self,
    ) -> None:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        supervisor = SupervisorSession(SESSION, KEY, CONTRACT)
        supervisor.accept_authority_packet(authority.ready_packet())
        execute = supervisor.execute_packet("run-1", APPLICATION)
        authority.accept_supervisor_packet(execute)
        cancel = supervisor.cancel_packet()
        authority.accept_supervisor_packet(cancel)
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            supervisor.cancel_packet()
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.accept_supervisor_packet(execute)

    def test_supervisor_accepts_only_authenticated_exact_terminal_receipt(self) -> None:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        supervisor = SupervisorSession(SESSION, KEY, CONTRACT)
        supervisor.accept_authority_packet(authority.ready_packet())
        authority.accept_supervisor_packet(
            supervisor.execute_packet("run-1", APPLICATION)
        )
        terminal = encode_frame(KEY, SESSION, 1, "terminal", _receipt())
        receipt = supervisor.accept_authority_packet(terminal)
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt.status, "PASS")
        self.assertIsInstance(receipt.values, Mapping)
        with self.assertRaises(TypeError):
            receipt.values["status"] = "FAIL"  # type: ignore[index]
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            supervisor.accept_authority_packet(terminal)

    def test_supervisor_rejects_malformed_terminal_receipt_digest_and_hmac(
        self,
    ) -> None:
        for field in ("receipt_sha256", "evidence_id"):
            with self.subTest(field=field):
                receipt = _receipt()
                receipt[field] = (
                    "0" * 64 if field != "evidence_id" else "prime-p1-" + "0" * 64
                )
                packet = encode_frame(KEY, SESSION, 1, "terminal", receipt)
                supervisor = SupervisorSession(SESSION, KEY, CONTRACT)
                authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
                supervisor.accept_authority_packet(authority.ready_packet())
                authority.accept_supervisor_packet(
                    supervisor.execute_packet("run-1", APPLICATION)
                )
                with self.assertRaises(PrimeP1AuthorityProtocolError):
                    supervisor.accept_authority_packet(packet)


if __name__ == "__main__":
    unittest.main()
