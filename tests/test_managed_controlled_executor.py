from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from asterion.services.controlled_executor import ControlledExecutorError
from asterion.services.managed_controlled_executor import (
    ManagedControlledExecutor,
    OperatorExecutorConfig,
    load_operator_executor_config,
)
from asterion.services.controlled_executor_jsonl import TrustedValidationConfig


class FakePipe:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RecordingStderr:
    def __init__(self) -> None:
        self.read_sizes: list[int] = []
        self._chunks = [b"diagnostic", b""]

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._chunks.pop(0)


class FakeProcess:
    def __init__(self, *, returncode: int | None = None, wait_timeout: bool = False) -> None:
        self.returncode = returncode
        self.stdin = FakePipe()
        self.stdout = __import__("asyncio").StreamReader()
        self.stderr = __import__("asyncio").StreamReader()
        self.stderr.feed_eof()
        self.wait_timeout = wait_timeout
        self.terminated = False
        self.killed = False

    async def wait(self) -> int:
        if self.wait_timeout and not self.terminated and not self.killed:
            await __import__("asyncio").sleep(10)
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def validation_payload() -> dict[str, object]:
    return {
        "program_id": "check",
        "argument_prefix": ["--fixed"],
        "cwd": "workspace",
        "deadline_ms": 1000,
        "max_output_bytes": 4096,
    }


class OperatorExecutorConfigTests(unittest.TestCase):
    def test_loads_three_canonical_operator_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "executor"
            policy = root / "policy.json"
            validation = root / "validation.json"
            binary.write_text("fixture")
            policy.write_text(json.dumps({"workspace_root": "workspace"}))
            validation.write_text(json.dumps(validation_payload()))

            config = load_operator_executor_config(binary, policy, validation)

        self.assertIsInstance(config, OperatorExecutorConfig)
        self.assertEqual(config.validation_config.program_id, "check")
        self.assertEqual(config.validation_config.argument_prefix, ("--fixed",))

    def test_rejects_symlink_directory_malformed_or_unsafe_configuration_without_echo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "executor"
            policy = root / "policy.json"
            validation = root / "validation.json"
            binary.write_text("fixture")
            policy.write_text("{}")
            validation.write_text(json.dumps(validation_payload()))
            link = root / "SECRET-link"
            link.symlink_to(binary)
            validation.write_text('{"program_id": "SECRET"}')
            for values in (
                (link, policy, validation),
                (binary, root, validation),
                (binary, policy, validation),
                (binary, policy, root / "missing.json"),
            ):
                with self.subTest(values=values):
                    with self.assertRaises(ControlledExecutorError) as caught:
                        load_operator_executor_config(*values)
                    self.assertNotIn("SECRET", str(caught.exception))


class ManagedControlledExecutorTests(unittest.IsolatedAsyncioTestCase):
    def config(self) -> OperatorExecutorConfig:
        return OperatorExecutorConfig(
            binary_path=Path("/trusted/executor"),
            policy_path=Path("/trusted/policy.json"),
            validation_config=TrustedValidationConfig(
                program_id="check",
                argument_prefix=(),
                cwd="workspace",
                deadline_ms=1000,
                max_output_bytes=1024,
            ),
        )

    async def test_starts_direct_argv_with_minimal_environment_and_closes_child(self) -> None:
        process = FakeProcess()
        with patch(
            "asterion.services.managed_controlled_executor.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ) as create:
            async with ManagedControlledExecutor(self.config()) as client:
                self.assertIsNotNone(client)

        create.assert_awaited_once()
        self.assertEqual(create.await_args.args, ("/trusted/executor", "/trusted/policy.json"))
        self.assertEqual(create.await_args.kwargs["env"], {})
        self.assertTrue(process.stdin.closed)

    async def test_immediate_exit_is_rejected_without_echoing_paths(self) -> None:
        process = FakeProcess(returncode=1)
        with patch(
            "asterion.services.managed_controlled_executor.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            with self.assertRaises(ControlledExecutorError) as caught:
                async with ManagedControlledExecutor(self.config()):
                    pass
        self.assertNotIn("trusted", str(caught.exception))

    async def test_discards_stderr_in_bounded_chunks(self) -> None:
        process = FakeProcess()
        stderr = RecordingStderr()
        process.stderr = stderr  # type: ignore[assignment]
        with patch(
            "asterion.services.managed_controlled_executor.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=process),
        ):
            async with ManagedControlledExecutor(self.config()):
                pass

        self.assertEqual(stderr.read_sizes, [4096, 4096])


if __name__ == "__main__":
    unittest.main()
