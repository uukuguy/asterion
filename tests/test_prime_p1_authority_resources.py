"""Static, non-authoritative Prime P1 image-resource admission tests."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    load_operator_config,
)
from asterion.applications.prime_agent.operator.authority_resources import (
    PrimeP1AuthorityResourceError,
    admit_static_image_resource,
)
from asterion.applications.prime_agent.operator.image_input_lock import (
    ImagePlatformDescriptor,
)


_VALUES = {
    "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
    "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
    "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/asterion/seccomp.json",
    "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "linux",
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd64",
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "none",
    "ASTERION_PRIME_P1_MODEL_ID": "deepseek-chat",
    "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/lib/asterion/evidence",
    "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "p1-2026",
    "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
    "DEEPSEEK_API_KEY": "RESOURCE_SECRET_SENTINEL",
}


class TestPrimeP1AuthorityResources(unittest.TestCase):
    def _config(self) -> object:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            path = Path(temp) / "operator.env"
            path.write_text("".join(f"{key}={value}\n" for key, value in _VALUES.items()))
            path.chmod(0o600)
            fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
            return load_operator_config(fd)

    def test_empty_code_owned_catalog_fails_closed_and_redacted(self) -> None:
        config = self._config()
        with self.assertRaises(PrimeP1AuthorityResourceError) as raised:
            admit_static_image_resource(config)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn("RESOURCE_SECRET_SENTINEL", str(raised.exception))
        self.assertNotIn("RESOURCE_SECRET_SENTINEL", repr(raised.exception))

    def test_normalizes_none_only_at_resource_admission(self) -> None:
        config = self._config()
        import asterion.applications.prime_agent.operator.authority_resources as module

        with patch.object(
            module,
            "resolve_promoted_image_input_lock",
            side_effect=ValueError("test resolver rejection"),
        ) as resolver:
            with self.assertRaises(PrimeP1AuthorityResourceError):
                admit_static_image_resource(config)
        resolver.assert_called_once_with(ImagePlatformDescriptor("linux", "amd64", None))

    def test_rejects_non_authority_config_before_resolving(self) -> None:
        import asterion.applications.prime_agent.operator.authority_resources as module

        with patch.object(module, "resolve_promoted_image_input_lock") as resolver:
            with self.assertRaises(PrimeP1AuthorityResourceError):
                admit_static_image_resource(object())
        resolver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
