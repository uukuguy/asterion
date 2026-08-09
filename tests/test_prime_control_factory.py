from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from asterion.control.factory import ControlPlaneFactoryContext, ControlPlaneFactoryError
from asterion.control.providers.prime.client import PrimeControlPlaneClient
from asterion.control.providers.prime.factory import (
    PRIME_CONTROL_PLANE_ID,
    PRIME_CONTROL_PLANE_VERSION,
    build_prime_control_plane_client,
    prime_control_plane_binding,
)
from asterion.control.providers.prime.process import (
    PrimeSidecarProcess,
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcessError,
    build_prime_sidecar_spawn_plan,
)


class FakeResolver:
    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        del reference, max_bytes
        return "private"


class FakeProcess:
    def __init__(self, options: PrimeSidecarLaunchOptions) -> None:
        self.options = options


def make_context(root: Path, **options: str) -> ControlPlaneFactoryContext:
    values = {
        "execution_domain": "trusted-local",
        "node_executable": str(root / "node"),
        "sidecar_entry": str(root / "main.js"),
        "session_id": "session-1",
        "authority_id": "authority-1",
        "generation": "1",
        "gateway_root": str(root / "gateway"),
        "prime_socket_path": str(root / "prime.sock"),
        "workspace": str(root / "workspace"),
        "agent_dir": str(root / "agent"),
        "session_dir": str(root / "sessions"),
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "max_continuations": "3",
        "max_turns": "10",
        "max_controller_tokens": "1000",
        "timeout_ms": "30000",
        "expected_runtime_build_id": "prime-build-locked",
        "prime_source_root": str(root / "prime-source"),
        "artifact_lock_path": str(root / "artifact-lock.json"),
        **options,
    }
    return ControlPlaneFactoryContext(
        system_id="research.system",
        system_version="1.0.0",
        control_plane_id=values.get("control_plane_id", PRIME_CONTROL_PLANE_ID),
        control_plane_version=values.get(
            "control_plane_version",
            PRIME_CONTROL_PLANE_VERSION,
        ),
        private_root=root,
        options=values,
        host_services={"private-content": FakeResolver()},
    )


def prepare_paths(root: Path) -> None:
    for directory in ("gateway", "workspace", "agent", "sessions", "prime-source"):
        (root / directory).mkdir()
    (root / "node").write_text("#!/bin/sh\n")
    (root / "node").chmod(0o700)
    (root / "main.js").write_text("void 0;\n")
    (root / "artifact-lock.json").write_text("{}\n")


class TestPrimeControlFactory(unittest.TestCase):
    def test_binding_declares_exact_prime_identity_and_compatibility(self) -> None:
        binding = prime_control_plane_binding()
        manifest = binding.manifest

        self.assertEqual(binding.control_plane_id, "prime.gateway")
        self.assertEqual(binding.version, "0.1.0")
        self.assertEqual(manifest.checkpoint_version, "1.0.0")
        self.assertEqual(
            manifest.compatibility_ids,
            (
                "asterion.agent-control/v1",
                "prime-agent.daemon/v7",
                "prime-agent.schema/v14",
            ),
        )

    def test_factory_requires_trusted_local_authorization_and_exact_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)

            for overrides in (
                {"execution_domain": "restricted"},
                {"execution_domain": ""},
                {"control_plane_id": "fake.control"},
                {"control_plane_version": "9.0.0"},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(
                    ControlPlaneFactoryError,
                ):
                    build_prime_control_plane_client(
                        make_context(root, **overrides),
                        process_factory=FakeProcess,
                    )

            context = make_context(root)
            context = ControlPlaneFactoryContext(
                system_id=context.system_id,
                system_version=context.system_version,
                control_plane_id=context.control_plane_id,
                control_plane_version=context.control_plane_version,
                private_root=context.private_root,
                options=context.options,
                host_services={},
            )
            with self.assertRaises(ControlPlaneFactoryError):
                build_prime_control_plane_client(
                    context,
                    process_factory=FakeProcess,
                )

    def test_factory_builds_client_without_rendering_private_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            context = make_context(root, provider="SENTINEL_SECRET")
            seen: list[PrimeSidecarLaunchOptions] = []

            def process_factory(options: PrimeSidecarLaunchOptions) -> FakeProcess:
                seen.append(options)
                return FakeProcess(options)

            client = build_prime_control_plane_client(
                context,
                process_factory=process_factory,
            )

            self.assertIsInstance(client, PrimeControlPlaneClient)
            self.assertEqual(seen[0].argv, (str((root / "node").resolve()), str((root / "main.js").resolve())))
            self.assertNotIn("SENTINEL_SECRET", repr(seen[0]))

    def test_process_preflight_uses_direct_argv_no_shell_and_fixed_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            options = PrimeSidecarLaunchOptions(
                node_executable=root / "node",
                sidecar_entry=root / "main.js",
                private_descriptor={"provider": "SENTINEL_SECRET"},
                environ={
                    "PATH": "/bin",
                    "HOME": str(root),
                    "OPENAI_API_KEY": "SENTINEL_SECRET",
                    "ASTERION_PRIVATE": "SENTINEL_SECRET",
                },
            )

            plan = build_prime_sidecar_spawn_plan(options, private_descriptor_fd=7)

            self.assertEqual(plan.argv, (str((root / "node").resolve()), str((root / "main.js").resolve())))
            self.assertFalse(plan.shell)
            self.assertEqual(plan.pass_fds, (7,))
            self.assertEqual(plan.env["PATH"], "/bin")
            self.assertEqual(plan.env["ASTERION_PRIME_PRIVATE_FD"], "7")
            self.assertNotIn("OPENAI_API_KEY", plan.env)
            self.assertNotIn("SENTINEL_SECRET", repr(plan))

    def test_process_preflight_rejects_missing_executable_or_source_before_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath("node").write_text("#!/bin/sh\n")
            root.joinpath("node").chmod(0o700)

            with self.assertRaises(PrimeSidecarProcessError):
                build_prime_sidecar_spawn_plan(
                    PrimeSidecarLaunchOptions(
                        node_executable=root / "node",
                        sidecar_entry=root / "missing.js",
                        private_descriptor={},
                    ),
                )


class TestPrimeSidecarProcess(unittest.IsolatedAsyncioTestCase):
    async def test_sidecar_eof_before_ack_fails_closed_and_close_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "eof.py"
            script.write_text(
                "import sys, time\n"
                "sys.stdin.readline()\n"
                "time.sleep(60)\n",
            )
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(sys.executable),
                    sidecar_entry=script,
                    private_descriptor={"provider": "SENTINEL_SECRET"},
                    environ={"PATH": os.environ.get("PATH", "")},
                    close_timeout=0.05,
                    request_timeout=0.05,
                )
            )

            with self.assertRaises(PrimeSidecarProcessError) as raised:
                await process.request(
                    {
                        "protocol": "asterion.prime-gateway-ipc/v1",
                        "id": "request-1",
                        "type": "command.accept",
                        "command": create_context_command(),
                        "private": {},
                    }
                )

            self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
            await process.close()
            self.assertIsNotNone(process.returncode)

    async def test_sidecar_invalid_json_ack_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "invalid.py"
            script.write_text(
                "import sys\n"
                "sys.stdin.readline()\n"
                "sys.stdout.write('not-json\\\\n')\n"
                "sys.stdout.flush()\n",
            )
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(sys.executable),
                    sidecar_entry=script,
                    private_descriptor={},
                    environ={"PATH": os.environ.get("PATH", "")},
                    close_timeout=0.2,
                )
            )
            try:
                with self.assertRaises(PrimeSidecarProcessError):
                    await process.request(
                        {
                            "protocol": "asterion.prime-gateway-ipc/v1",
                            "id": "request-1",
                            "type": "events.stream",
                            "cursor": None,
                        }
                    )
            finally:
                await process.close()

    async def test_sidecar_receives_private_descriptor_only_on_inherited_fd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "descriptor.py"
            script.write_text(
                "import json, os, sys\n"
                "fd = int(os.environ['ASTERION_PRIME_PRIVATE_FD'])\n"
                "descriptor = json.loads(os.read(fd, 65536).decode())\n"
                "request = json.loads(sys.stdin.readline())\n"
                "leaked = 'SENTINEL_SECRET' in json.dumps(sys.argv + list(os.environ.values()))\n"
                "ok = descriptor.get('provider') == 'SENTINEL_SECRET' and not leaked\n"
                "response_type = 'command.accepted' if ok else 'error'\n"
                "sys.stdout.write(json.dumps({\n"
                "    'protocol': 'asterion.prime-gateway-ipc/v1',\n"
                "    'id': request['id'],\n"
                "    'type': response_type,\n"
                "}) + '\\n')\n"
                "sys.stdout.flush()\n",
            )
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(sys.executable),
                    sidecar_entry=script,
                    private_descriptor={"provider": "SENTINEL_SECRET"},
                    environ={"PATH": os.environ.get("PATH", "")},
                    request_timeout=0.2,
                )
            )
            try:
                response = await process.request(
                    {
                        "protocol": "asterion.prime-gateway-ipc/v1",
                        "id": "request-1",
                        "type": "command.accept",
                        "command": create_context_command(),
                        "private": {},
                    }
                )
            finally:
                await process.close()

            self.assertEqual(response["type"], "command.accepted")


def create_context_command() -> dict[str, object]:
    return {
        "protocol": "asterion.agent-control/v1",
        "command_id": "command-1",
        "session_id": "session-1",
        "authority_revision": 1,
        "type": "session.create",
        "payload": {
            "system_id": "research.system",
            "system_version": "1.0.0",
            "goal_id": "goal-1",
            "goal_ref": "goal-ref-1",
        },
    }


if __name__ == "__main__":
    unittest.main()
