"""Adversarial tests for the authority-only operator configuration loader."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from asterion.applications.prime_agent.operator.authority_config import (
    PrimeP1OperatorConfigError,
    load_operator_config,
)


VALUES = {
    "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
    "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
    "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/asterion/seccomp.json",
    "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
    "ASTERION_PRIME_P1_MODEL_ID": "deepseek-chat",
    "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/lib/asterion/evidence",
    "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "p1-2026",
    "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
    "DEEPSEEK_API_KEY": "SENTINEL_SECRET",
}


class TestPrimeP1OperatorConfig(unittest.TestCase):
    def _write(self, root: Path, text: str | None = None, name: str = "operator.env") -> Path:
        path = root / name
        path.write_text(text or "".join(f"{key}={value}\n" for key, value in VALUES.items()), encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_loads_only_an_explicit_secure_external_file(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            root.chmod(0o700)
            config = load_operator_config(self._write(root), authority_uid=os.getuid(), application_uid=65534)
        self.assertEqual(config.model_id, "deepseek-chat")
        self.assertNotIn("SENTINEL_SECRET", repr(config))

    def test_rejects_dotenv_symlinks_duplicates_interpolation_and_ambient_values(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            root.chmod(0o700)
            target = self._write(root)
            link = root / "link.env"
            link.symlink_to(target)
            cases = {
                ".env": self._write(root, name=".env"),
                "symlink": link,
                "duplicate": self._write(root, text="".join(f"{key}={value}\n" for key, value in VALUES.items()) + "DEEPSEEK_API_KEY=other\n"),
                "interpolation": self._write(root, text="".join(f"{key}={value}\n" for key, value in {**VALUES, "ASTERION_PRIME_P1_MODEL_ID": "${HOME}"}.items())),
            }
            os.environ["DEEPSEEK_API_KEY"] = "AMBIENT_SENTINEL"
            for label, path in cases.items():
                with self.subTest(label=label), self.assertRaisesRegex(PrimeP1OperatorConfigError, "unavailable"):
                    load_operator_config(path, authority_uid=os.getuid(), application_uid=65534)

    def test_rejects_non_owner_only_file_and_reports_no_path_or_secret(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            root.chmod(0o700)
            path = self._write(root)
            path.chmod(0o640)
            with self.assertRaises(PrimeP1OperatorConfigError) as caught:
                load_operator_config(path, authority_uid=os.getuid(), application_uid=65534)
        self.assertEqual(str(caught.exception), "prime P1 operator configuration is unavailable")
        self.assertNotIn(str(path), repr(caught.exception))


if __name__ == "__main__":
    unittest.main()
