"""Contract tests for the non-authoritative IPC parsing boundary."""

from __future__ import annotations

import json
import unittest
from collections.abc import Mapping
from dataclasses import replace
import hmac
from asterion.applications.prime_agent.operator.authority_receipt import (
    _AuthorityTerminalBinding,
    _IssuedAuthorityReceipt,
    _UnavailableReceiptMaterial,
    _issue_unavailable_receipt,
    _new_authority_receipt_issuer,
)

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
def _material() -> _UnavailableReceiptMaterial:
    return _UnavailableReceiptMaterial(
        authority_version="1.0.0", authority_executable_sha256="1" * 64,
        operator_config_binding_hmac_sha256="2" * 64, receipt_key_id="key-1",
        assembly_sha256="3" * 64, package_manifest_sha256="4" * 64,
        source_sha256="5" * 64, build_input_sha256="6" * 64,
        image_config_digest="sha256:" + "7" * 64, workload_sha256="8" * 64,
        starter_sha256="9" * 64, oracle_sha256="a" * 64, seccomp_sha256="b" * 64,
    )


class TestPrimeP1AuthorityProtocol(unittest.TestCase):
    def _live_pair(self) -> tuple[AuthoritySession, SupervisorSession]:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
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
    def test_sessions_keep_receipt_hmac_key_out_of_their_apis(self) -> None:
        with self.assertRaises(TypeError):
            SupervisorSession(SESSION, KEY, CONTRACT, receipt_hmac_key=KEY)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET, receipt_hmac_key=KEY)  # type: ignore[call-arg]

    def test_cancelled_session_rejects_terminal_reservation(self) -> None:
        authority, supervisor = self._live_pair()
        authority.accept_supervisor_packet(supervisor.cancel_packet())
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.reserve_terminal_binding()

    def test_terminal_requires_one_bound_issued_unavailable_receipt(self) -> None:
        authority, supervisor = self._live_pair()
        binding = authority.reserve_terminal_binding()
        issued = _issue_unavailable_receipt(
            _new_authority_receipt_issuer("2" * 64), binding, _material()
        )

        receipt = supervisor.accept_authority_packet(authority.terminal_packet(issued))

        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt.status, "UNAVAILABLE")
        self.assertEqual(receipt.values["reason_code"], "unavailable")
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet(issued)

    def test_issued_receipt_cannot_terminalize_value_identical_session_twice(self) -> None:
        first_authority, first_supervisor = self._live_pair()
        second_authority, _ = self._live_pair()
        first_binding = first_authority.reserve_terminal_binding()
        second_authority.reserve_terminal_binding()
        issued = _issue_unavailable_receipt(
            _new_authority_receipt_issuer("2" * 64), first_binding, _material()
        )

        first_supervisor.accept_authority_packet(first_authority.terminal_packet(issued))

        with self.assertRaises(PrimeP1AuthorityProtocolError):
            second_authority.terminal_packet(issued)

    def test_terminal_rejects_constructed_or_replaced_issued_receipts(self) -> None:
        first_authority, first_supervisor = self._live_pair()
        second_authority, _ = self._live_pair()
        first_binding = first_authority.reserve_terminal_binding()
        second_binding = second_authority.reserve_terminal_binding()
        issued = _issue_unavailable_receipt(
            _new_authority_receipt_issuer("2" * 64), first_binding, _material()
        )
        first_supervisor.accept_authority_packet(first_authority.terminal_packet(issued))

        for forged in (
            _IssuedAuthorityReceipt(second_binding, issued._payload),
            replace(issued, _binding=second_binding),
        ):
            with self.subTest(forged=repr(forged)):
                with self.assertRaises(PrimeP1AuthorityProtocolError):
                    second_authority.terminal_packet(forged)

    def test_terminal_rejects_raw_receipt_mapping_binding_mismatch_and_wrong_state(self) -> None:
        authority = AuthoritySession(SESSION, KEY, CONTRACT, RESOURCE_SET)
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet({})  # type: ignore[arg-type]
        authority.ready_packet()
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet({})  # type: ignore[arg-type]

        authority, _ = self._live_pair()
        authority.reserve_terminal_binding()
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet({})  # type: ignore[arg-type]

        authority, _ = self._live_pair()
        authority.reserve_terminal_binding()
        mismatched = _AuthorityTerminalBinding(
            SESSION, "run-2", CONTRACT, APPLICATION, RESOURCE_SET
        )
        issued = _issue_unavailable_receipt(
            _new_authority_receipt_issuer("2" * 64), mismatched, _material()
        )
        with self.assertRaises(PrimeP1AuthorityProtocolError):
            authority.terminal_packet(issued)

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



if __name__ == "__main__":
    unittest.main()
