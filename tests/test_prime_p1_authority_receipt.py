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


class TestPrimeP1AuthorityReceiptCustody(unittest.TestCase):
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
