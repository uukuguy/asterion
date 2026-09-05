"""Opaque receipt-key custody tests for the Prime P1 authority."""

from __future__ import annotations

import os
from pathlib import Path
import pickle
import tempfile
import traceback
import unittest
from typing import Any, cast

from asterion.applications.prime_agent.operator.authority_config import (
    PrimeP1OperatorConfigError,
    load_operator_config,
)
from asterion.applications.prime_agent.operator.authority_receipt import (
    _AuthorityTerminalBinding,
    _UnavailableReceiptMaterial,
    _issue_unavailable_receipt,
    _new_authority_receipt_issuer,
)


def _binding() -> _AuthorityTerminalBinding:
    return _AuthorityTerminalBinding(
        session_id="a" * 64,
        run_id="run-1",
        request_contract_sha256="b" * 64,
        application_request_sha256="c" * 64,
        production_resource_set_sha256="d" * 64,
    )


def _material(**overrides: object) -> _UnavailableReceiptMaterial:
    values: dict[str, object] = {
        "authority_version": "1.0.0",
        "authority_executable_sha256": "1" * 64,
        "operator_config_binding_hmac_sha256": "2" * 64,
        "receipt_key_id": "p1-2026",
        "assembly_sha256": "3" * 64,
        "package_manifest_sha256": "4" * 64,
        "source_sha256": "5" * 64,
        "build_input_sha256": "6" * 64,
        "image_config_digest": "sha256:" + "7" * 64,
        "workload_sha256": "8" * 64,
        "starter_sha256": "9" * 64,
        "oracle_sha256": "a" * 64,
        "seccomp_sha256": "b" * 64,
    }
    values.update(overrides)
    return _UnavailableReceiptMaterial(**cast(Any, values))


class TestPrimeP1AuthorityReceiptCustody(unittest.TestCase):
    def test_malformed_material_is_public_safe_after_custody_consumption(self) -> None:
        for malformed in (
            _material(image_config_digest=object()),
            _material(authority_version="CONFIG_SECRET_SENTINEL\ud800"),
            _material(receipt_key_id="\ud800"),
        ):
            with self.subTest(malformed=repr(malformed)):
                sentinel = "a" * 64
                issuer = _new_authority_receipt_issuer(sentinel)
                with self.assertRaises(ValueError) as raised:
                    _issue_unavailable_receipt(issuer, _binding(), malformed)
                self.assertIs(type(raised.exception), ValueError)
                self.assertEqual(
                    str(raised.exception), "prime P1 authority receipt is unavailable"
                )
                self.assertIsNone(raised.exception.__context__)
                rendered = "".join(traceback.format_exception(raised.exception))
                self.assertNotIn(sentinel, rendered)
                self.assertNotIn("CONFIG_SECRET_SENTINEL", rendered)
                with self.assertRaises(ValueError):
                    _issue_unavailable_receipt(issuer, _binding(), _material())

    def test_issuer_creates_one_redacted_unavailable_receipt(self) -> None:
        sentinel = "e" * 64
        issuer = _new_authority_receipt_issuer(sentinel)
        binding = _AuthorityTerminalBinding(
            session_id="a" * 64,
            run_id="run-1",
            request_contract_sha256="b" * 64,
            application_request_sha256="c" * 64,
            production_resource_set_sha256="d" * 64,
        )
        material = _UnavailableReceiptMaterial(
            authority_version="1.0.0",
            authority_executable_sha256="1" * 64,
            operator_config_binding_hmac_sha256="2" * 64,
            receipt_key_id="p1-2026",
            assembly_sha256="3" * 64,
            package_manifest_sha256="4" * 64,
            source_sha256="5" * 64,
            build_input_sha256="6" * 64,
            image_config_digest="sha256:" + "7" * 64,
            workload_sha256="8" * 64,
            starter_sha256="9" * 64,
            oracle_sha256="a" * 64,
            seccomp_sha256="b" * 64,
        )

        issued = _issue_unavailable_receipt(issuer, binding, material)

        payload = issued._payload
        self.assertEqual((payload["status"], payload["reason_code"]), ("UNAVAILABLE", "unavailable"))
        self.assertEqual(payload["model_accounting"]["request_count"], 0)  # type: ignore[index]
        self.assertEqual(payload["worker_evidence"]["worker_count"], 0)  # type: ignore[index]
        self.assertEqual(payload["worker_evidence"]["model_tool_calls"], 0)  # type: ignore[index]
        self.assertEqual(payload["worker_evidence"]["ipython_tool_calls"], 0)  # type: ignore[index]
        self.assertFalse(payload["worker_evidence"]["final_oracle_passed"])  # type: ignore[index]
        self.assertFalse(payload["worker_evidence"]["mutation_after_model_response"])  # type: ignore[index]
        for rendered in (repr(issuer), repr(issued)):
            self.assertNotIn(sentinel, rendered)
            self.assertNotIn("CONFIG_SECRET_SENTINEL", rendered)
        with self.assertRaises(ValueError) as raised:
            _issue_unavailable_receipt(issuer, binding, material)
        self.assertEqual(str(raised.exception), "prime P1 authority receipt is unavailable")

    def test_issuer_rejects_altered_binding_without_secret_disclosure(self) -> None:
        sentinel = "f" * 64
        issuer = _new_authority_receipt_issuer(sentinel)
        material = _UnavailableReceiptMaterial(
            authority_version="1.0.0", authority_executable_sha256="1" * 64,
            operator_config_binding_hmac_sha256="2" * 64, receipt_key_id="p1-2026",
            assembly_sha256="3" * 64, package_manifest_sha256="4" * 64,
            source_sha256="5" * 64, build_input_sha256="6" * 64,
            image_config_digest="sha256:" + "7" * 64, workload_sha256="8" * 64,
            starter_sha256="9" * 64, oracle_sha256="a" * 64, seccomp_sha256="b" * 64,
        )
        with self.assertRaises(ValueError) as raised:
            _issue_unavailable_receipt(
                issuer,
                _AuthorityTerminalBinding("not-a-session", "run-1", "b" * 64, "c" * 64, "d" * 64),
                material,
            )
        rendered = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn("CONFIG_SECRET_SENTINEL", rendered)

    def test_config_moves_receipt_key_into_opaque_issuer_without_public_capability(
        self,
    ) -> None:
        sentinel = "c" * 64
        values = {
            "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
            "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
            "ASTERION_PRIME_P1_DOCKER_SOCKET_OWNER_UID": "0",
            "ASTERION_PRIME_P1_DOCKER_SOCKET_GROUP_GID": "0",
            "ASTERION_PRIME_P1_DOCKER_SOCKET_MODE": "0600",
            "ASTERION_PRIME_P1_DOCKER_SERVER_API_VERSION": "1.41",
            "ASTERION_PRIME_P1_DOCKER_SERVER_VERSION": "26.1.4",
            "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/asterion/seccomp.json",
            "ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256": "c" * 64,
            "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "linux",
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd64",
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "none",
            "ASTERION_PRIME_P1_MODEL_ID": "deepseek-chat",
            "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/lib/asterion/evidence",
            "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "p1-2026",
            "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": sentinel,
            "DEEPSEEK_API_KEY": "CONFIG_SECRET_SENTINEL",
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            path = Path(temp) / "operator.env"
            path.write_text(
                "".join(f"{key}={value}\n" for key, value in values.items())
            )
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            config = load_operator_config(fd)
        issuer = config._receipt_issuer
        self.assertEqual(config.model_id, "deepseek-chat")
        self.assertNotIn("ASTERION_PRIME_P1_RECEIPT_HMAC_KEY", config._values)
        for rendered in (repr(config), repr(issuer)):
            self.assertNotIn(sentinel, rendered)
            self.assertNotIn("CONFIG_SECRET_SENTINEL", rendered)
        self.assertEqual(
            [
                name
                for name in dir(issuer)
                if not name.startswith("_")
                and any(
                    token in name.lower() for token in ("key", "sign", "get", "map")
                )
            ],
            [],
        )
        self.assertFalse(callable(issuer))
        with self.assertRaises(TypeError):
            bytes(cast(Any, issuer))
        with self.assertRaises(TypeError):
            pickle.dumps(issuer)
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_receipt_key_is_redacted_when_config_load_fails(self) -> None:
        sentinel = "d" * 64
        values = {
            "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
            "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
            "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/asterion/seccomp.json",
            "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
            "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/lib/asterion/evidence",
            "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "p1-2026",
            "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": sentinel,
            "DEEPSEEK_API_KEY": "CONFIG_SECRET_SENTINEL",
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            path = Path(temp) / "operator.env"
            path.write_text(
                "".join(f"{key}={value}\n" for key, value in values.items())
            )
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            with self.assertRaises(PrimeP1OperatorConfigError) as raised:
                load_operator_config(fd)
        self.assertIsNone(raised.exception.__context__)
        rendered = "".join(traceback.format_exception(raised.exception))
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn("CONFIG_SECRET_SENTINEL", rendered)
