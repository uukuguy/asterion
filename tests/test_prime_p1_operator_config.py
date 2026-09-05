"""Adversarial tests for the descriptor-only Prime P1 authority config."""

from __future__ import annotations

import os
import copy
import pickle
import platform
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from asterion.applications.prime_agent.operator.authority_config import (
    PrimeP1OperatorConfigError,
    load_operator_config,
)


VALUES = {
    "ASTERION_PRIME_P1_DOCKER_EXECUTABLE": "/usr/bin/docker",
    "ASTERION_PRIME_P1_DOCKER_SOCKET": "/var/run/docker.sock",
    "ASTERION_PRIME_P1_SECCOMP_PROFILE": "/etc/asterion/seccomp.json",
    "ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256": "c" * 64,
    "ASTERION_PRIME_P1_IMAGE_CONFIG_DIGEST": "sha256:" + "a" * 64,
    "ASTERION_PRIME_P1_MODEL_ID": "deepseek-chat",
    "ASTERION_PRIME_P1_EVIDENCE_ROOT": "/var/lib/asterion/evidence",
    "ASTERION_PRIME_P1_RECEIPT_KEY_ID": "p1-2026",
    "ASTERION_PRIME_P1_RECEIPT_HMAC_KEY": "b" * 64,
    "DEEPSEEK_API_KEY": "SENTINEL_SECRET",
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "linux",
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd64",
    "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "none",
}


class TestPrimeP1OperatorConfig(unittest.TestCase):
    def _text(self, values: dict[str, str] = VALUES) -> bytes:
        return "".join(f"{key}={value}\n" for key, value in values.items()).encode()

    def _open_config(self, root: Path, *, text: bytes | None = None) -> int:
        path = root / "operator.env"
        path.write_bytes(text or self._text())
        path.chmod(0o600)
        return os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)

    def test_consumes_only_an_open_descriptor_and_derives_authority_uid(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            fd = self._open_config(Path(temp))
            config = load_operator_config(fd)
        self.assertEqual(config.model_id, "deepseek-chat")
        with self.assertRaises(OSError):
            os.fstat(fd)
        self.assertNotIn("SENTINEL_SECRET", repr(config))

    def test_config_has_no_ordinary_reflection_or_serialization_export(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            config = load_operator_config(self._open_config(Path(temp)))
        self.assertEqual(config.model_id, "deepseek-chat")
        with self.assertRaises(TypeError):
            vars(config)
        for operation in (
            lambda: pickle.dumps(config),
            lambda: copy.copy(config),
            lambda: copy.deepcopy(config),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(TypeError) as raised:
                    operation()
                self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_rejects_path_and_caller_selected_identity_arguments(self) -> None:
        with self.assertRaises((TypeError, PrimeP1OperatorConfigError)):
            load_operator_config(Path("/not/an/admission/path"))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            load_operator_config(0, authority_uid=os.getuid())  # type: ignore[call-arg]

    def test_normalizes_an_oversized_descriptor(self) -> None:
        with self.assertRaises(PrimeP1OperatorConfigError):
            load_operator_config(10**100)

    def test_rejects_insecure_file_contracts(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            cases: dict[str, tuple[int, bool]] = {
                "not-owner-only": (0o640, False),
                "not-regular": (0o600, True),
                "hard-linked": (0o600, False),
            }
            for label, (mode, directory) in cases.items():
                with self.subTest(label=label):
                    if directory:
                        path = root / label
                        path.mkdir(mode=mode)
                        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                    else:
                        fd = self._open_config(root)
                        os.fchmod(fd, mode)
                        if label == "hard-linked":
                            os.link(root / "operator.env", root / "operator-link.env")
                    with self.assertRaisesRegex(
                        PrimeP1OperatorConfigError, "unavailable"
                    ):
                        load_operator_config(fd)
                    with self.assertRaises(OSError):
                        os.fstat(fd)

    def test_rejects_a_descriptor_not_owned_by_the_live_authority_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            fd = self._open_config(Path(temp))
            import asterion.applications.prime_agent.operator.authority_config as module

            actual_fstat = os.fstat

            def other_owner(target_fd: int) -> os.stat_result:
                result = actual_fstat(target_fd)
                return os.stat_result(
                    (
                        result.st_mode,
                        result.st_ino,
                        result.st_dev,
                        result.st_nlink,
                        result.st_uid + 1,
                        result.st_gid,
                        result.st_size,
                        result.st_atime,
                        result.st_mtime,
                        result.st_ctime,
                    )
                )

            with patch.object(module.os, "fstat", side_effect=other_owner):
                with self.assertRaises(PrimeP1OperatorConfigError):
                    load_operator_config(fd)

    def test_rejects_changed_descriptor_identity_after_read(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            fd = self._open_config(Path(temp))
            import asterion.applications.prime_agent.operator.authority_config as module

            real_fstat = os.fstat
            calls = 0

            def changed_fstat(target_fd: int) -> os.stat_result:
                nonlocal calls
                calls += 1
                result = real_fstat(target_fd)
                if calls == 2:
                    return os.stat_result(
                        tuple(result[:8]) + (result.st_mtime + 1, result.st_ctime)
                    )
                return result

            with patch.object(module.os, "fstat", side_effect=changed_fstat):
                with self.assertRaises(PrimeP1OperatorConfigError):
                    load_operator_config(fd)

    def test_rejects_closed_schema_and_unicode_controls_without_interpolation(
        self,
    ) -> None:
        cases = {
            "duplicate": self._text() + b"DEEPSEEK_API_KEY=other\n",
            "missing": self._text(
                {
                    key: value
                    for key, value in VALUES.items()
                    if key != "DEEPSEEK_API_KEY"
                }
            ),
            "extra": self._text() + b"EXTRA=value\n",
            "empty": self._text({**VALUES, "DEEPSEEK_API_KEY": ""}),
            "blank-entry": self._text() + b"\n",
            "non-utf8": self._text() + b"\xff",
            "nul": self._text({**VALUES, "DEEPSEEK_API_KEY": "bad\x00value"}),
            "c1": self._text({**VALUES, "DEEPSEEK_API_KEY": "bad\u0085value"}),
            "format": self._text({**VALUES, "DEEPSEEK_API_KEY": "bad\u200evalue"}),
            "line-separator": self._text(
                {**VALUES, "DEEPSEEK_API_KEY": "bad\u2028value"}
            ),
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            for label, text in cases.items():
                with self.subTest(label=label):
                    fd = self._open_config(root, text=text)
                    with self.assertRaises(PrimeP1OperatorConfigError):
                        load_operator_config(fd)

    def test_rejects_legacy_or_malformed_image_platform_triples(self) -> None:
        cases = {
            "legacy-nine-key": {
                key: value
                for key, value in VALUES.items()
                if "IMAGE_PLATFORM" not in key
            },
            "missing-os": {
                key: value
                for key, value in VALUES.items()
                if key != "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS"
            },
            "missing-architecture": {
                key: value
                for key, value in VALUES.items()
                if key != "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE"
            },
            "missing-variant": {
                key: value
                for key, value in VALUES.items()
                if key != "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT"
            },
            "extra": {**VALUES, "EXTRA_PLATFORM": "linux"},
            "malformed-os": {
                **VALUES,
                "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "Linux",
            },
            "malformed-architecture": {
                **VALUES,
                "ASTERION_PRIME_P1_IMAGE_PLATFORM_ARCHITECTURE": "amd_64",
            },
            "malformed-variant": {
                **VALUES,
                "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "arm64",
            },
            "non-linux": {
                **VALUES,
                "ASTERION_PRIME_P1_IMAGE_PLATFORM_OS": "darwin",
            },
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            for label, values in cases.items():
                with self.subTest(label=label):
                    fd = self._open_config(root, text=self._text(values))
                    with self.assertRaises(PrimeP1OperatorConfigError):
                        load_operator_config(fd)

    def test_rejects_missing_duplicate_or_malformed_seccomp_profile_digest(self) -> None:
        digest_key = "ASTERION_PRIME_P1_SECCOMP_PROFILE_SHA256"
        cases = {
            "missing": self._text(
                {key: value for key, value in VALUES.items() if key != digest_key}
            ),
            "duplicate": self._text() + f"{digest_key}={'d' * 64}\n".encode(),
            "short": self._text({**VALUES, digest_key: "c" * 63}),
            "long": self._text({**VALUES, digest_key: "c" * 65}),
            "uppercase": self._text({**VALUES, digest_key: "C" * 64}),
            "nonhex": self._text({**VALUES, digest_key: "g" * 64}),
            "control": self._text({**VALUES, digest_key: "c" * 63 + "\u0085"}),
            "multiline": self._text({**VALUES, digest_key: "c" * 63 + "\n"}),
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            for label, text in cases.items():
                with self.subTest(label=label):
                    fd = self._open_config(root, text=text)
                    with self.assertRaises(PrimeP1OperatorConfigError) as raised:
                        load_operator_config(fd)
                    self.assertIsNone(raised.exception.__context__)
                    self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
                    with self.assertRaises(OSError):
                        os.fstat(fd)

    def test_accepts_v8_platform_variant_without_public_platform_getter(self) -> None:
        values = {
            **VALUES,
            "ASTERION_PRIME_P1_IMAGE_PLATFORM_VARIANT": "v8",
        }
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            config = load_operator_config(
                self._open_config(Path(temp), text=self._text(values))
            )
        self.assertEqual(config.model_id, "deepseek-chat")
        self.assertEqual(
            [name for name in dir(config) if not name.startswith("_")], ["model_id"]
        )

    def test_seccomp_digest_is_not_opened_or_hashed_during_config_admission(self) -> None:
        def forbidden(*_: object, **__: object) -> object:
            raise AssertionError("seccomp path access is forbidden")

        import asterion.applications.prime_agent.operator.authority_config as module

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            fd = self._open_config(Path(temp))
            with patch.object(module.os, "open", side_effect=forbidden):
                config = load_operator_config(fd)
        self.assertEqual(config.model_id, "deepseek-chat")
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("hashlib", source)

    def test_load_does_not_probe_host_platform_environment_or_cwd(self) -> None:
        def forbidden(*_: object, **__: object) -> object:
            raise AssertionError("host probing is forbidden")

        class ForbiddenEnvironment(dict[str, str]):
            def __getattribute__(self, _: str) -> object:
                raise AssertionError("environment access is forbidden")

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            root = Path(temp)
            fd = self._open_config(root)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                import asterion.applications.prime_agent.operator.authority_config as module

                with (
                    patch.object(platform, "machine", side_effect=forbidden),
                    patch.object(module.os, "uname", side_effect=forbidden),
                    patch.object(module.os, "getcwd", side_effect=forbidden),
                    patch.object(module.os, "environ", ForbiddenEnvironment()),
                ):
                    config = load_operator_config(fd)
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(config.model_id, "deepseek-chat")

    def test_interpolation_is_literal_and_environment_is_never_merged(self) -> None:
        values = {**VALUES, "DEEPSEEK_API_KEY": "${UNSET_SENTINEL}"}
        with (
            tempfile.TemporaryDirectory(dir=Path.cwd()) as temp,
            patch.dict(os.environ, {"UNSET_SENTINEL": "leaked"}),
        ):
            config = load_operator_config(
                self._open_config(Path(temp), text=self._text(values))
            )
        self.assertNotIn("leaked", repr(config))


if __name__ == "__main__":
    unittest.main()
