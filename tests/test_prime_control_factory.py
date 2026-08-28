from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from asterion.control.authority import AuthorityEnvelope
from asterion.control.factory import ControlPlaneFactoryContext, ControlPlaneFactoryError
from asterion.control.factory import bind_selected_session_context_client
from asterion.control.host import ControlPlaneManifest
from asterion.control.providers.prime.client import PrimeControlPlaneClient
from asterion.control.ecosystem import (
    EcosystemPrivateResource,
    build_ecosystem_portfolio,
)
from asterion.control.ecosystem_materialization import EcosystemProjection
from asterion.control.providers.prime.factory import (
    PRIME_CONTROL_PLANE_ID,
    PRIME_CONTROL_PLANE_VERSION,
    build_prime_control_plane_client,
    derive_prime_child_control_options,
    prime_control_plane_binding,
)
from asterion.control.providers.prime.ecosystem import PrimeEcosystemService
from tests.test_control_children import _child_envelope
from asterion.control.providers.prime.process import (
    PrimeSidecarProcess,
    PrimeSidecarLaunchOptions,
    PrimeSidecarProcessError,
    _encode_frame,
    build_prime_sidecar_spawn_plan,
)


class FakeResolver:
    def resolve_text(self, reference: str, *, max_bytes: int) -> str:
        del reference, max_bytes
        return "private"

    def resolve_bytes(
        self,
        reference: str,
        *,
        expected_media_type: str,
        expected_sha256: str,
        expected_size: int,
        max_bytes: int,
    ) -> bytes:
        del (
            reference,
            expected_media_type,
            expected_sha256,
            expected_size,
            max_bytes,
        )
        raise KeyError("private attachment is unavailable")


class FakeProcess:
    def __init__(self, options: PrimeSidecarLaunchOptions) -> None:
        self.options = options

    async def request(self, envelope: Mapping[str, object]) -> Mapping[str, object]:
        raise AssertionError(envelope)


class NoRequestProcess:
    def __init__(self, options: PrimeSidecarLaunchOptions) -> None:
        self.options = options


class FakeEcosystemSourceStore:
    def private_resource(self, resource_id: str) -> EcosystemPrivateResource:
        raise KeyError(resource_id)

    def open_file(self, resource_id: str, relative_path: str):
        raise KeyError((resource_id, relative_path))


class FakeEcosystemMaterializer:
    def materialize(self, portfolio, store) -> EcosystemProjection:
        raise AssertionError((portfolio, store))

    def close(self, projection: EcosystemProjection) -> None:
        raise AssertionError(projection)


class FakeMcpCredentialRefresh:
    def refresh(self, lease_id: str, challenge_digest: str) -> str:
        raise AssertionError((lease_id, challenge_digest))


class WorkingEcosystemMaterializer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[tuple[str, str]] = []

    def materialize(self, portfolio, store) -> EcosystemProjection:
        del store
        self.calls.append(("materialize", portfolio.digest))
        return EcosystemProjection(
            projection_id=portfolio.digest,
            portfolio_digest=portfolio.digest,
            root=self.root,
            resource_roots={},
        )

    def close(self, projection: EcosystemProjection) -> None:
        self.calls.append(("close", projection.portfolio_digest))


class EcosystemProcess:
    def __init__(self, options: PrimeSidecarLaunchOptions) -> None:
        self.options = options
        self.requests: list[Mapping[str, object]] = []

    async def request(
        self, envelope: Mapping[str, object]
    ) -> Mapping[str, object]:
        self.requests.append(envelope)
        frame = envelope["frame"]
        assert isinstance(frame, Mapping)
        return {
            "protocol": envelope["protocol"],
            "id": envelope["id"],
            "type": "ecosystem_receipt",
            "receipt": {
                "authorityDigest": frame["authorityDigest"],
                "featureIds": [],
                "lifecycleCount": 0,
                "mcpCount": 0,
                "modelCredentialReads": 0,
                "ownedProcessCount": 0,
                "packageCount": 0,
                "portfolioDigest": frame["portfolioDigest"],
                "providerOperations": 0,
                "registrationCount": 0,
                "resourceCount": 0,
                "status": "succeeded",
            },
        }

    async def close(self) -> None:
        return None

    async def events(self, envelope):
        del envelope
        if False:
            yield {}


class _OneShotProtocolObject:
    protocol_names: frozenset[str] = frozenset()

    def __init__(self) -> None:
        self.accesses: dict[str, int] = {}

    def __getattribute__(self, name: str):
        protocol_names = object.__getattribute__(self, "protocol_names")
        if name in protocol_names:
            accesses = object.__getattribute__(self, "accesses")
            accesses[name] = accesses.get(name, 0) + 1
            if accesses[name] > 1:
                raise RuntimeError("SENTINEL_SECOND_PROTOCOL_ACCESS")
        return object.__getattribute__(self, name)


class OneShotSourceStore(_OneShotProtocolObject):
    protocol_names = frozenset({"private_resource", "open_file"})

    def private_resource(self, resource_id: str) -> EcosystemPrivateResource:
        raise KeyError(resource_id)

    def open_file(self, resource_id: str, relative_path: str):
        raise KeyError((resource_id, relative_path))


class OneShotMaterializer(_OneShotProtocolObject):
    protocol_names = frozenset({"materialize", "close"})

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.calls: list[str] = []

    def materialize(self, portfolio, store) -> EcosystemProjection:
        del store
        self.calls.append("materialize")
        return EcosystemProjection(
            projection_id=portfolio.digest,
            portfolio_digest=portfolio.digest,
            root=self.root,
            resource_roots={},
        )

    def close(self, projection: EcosystemProjection) -> None:
        del projection
        self.calls.append("close")


class OneShotCredentialRefresh(_OneShotProtocolObject):
    protocol_names = frozenset({"refresh"})

    def refresh(self, lease_id: str, challenge_digest: str) -> str:
        del lease_id, challenge_digest
        raise AssertionError


class ExplodingEcosystemService:
    def __getattribute__(self, name: str):
        del name
        raise RuntimeError("SENTINEL_SERVICE_EXCEPTION")


def make_context(
    root: Path,
    *,
    authority: AuthorityEnvelope | None = None,
    **options: str,
) -> ControlPlaneFactoryContext:
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
        authority=authority if authority is not None else _child_envelope(),
        host_services={
            "ecosystem-materializer": FakeEcosystemMaterializer(),
            "ecosystem-source-store": FakeEcosystemSourceStore(),
            "mcp-credential-refresh": FakeMcpCredentialRefresh(),
            "private-attachments": FakeResolver(),
            "private-content": FakeResolver(),
        },
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
                "asterion.session-context/v1",
                "prime-agent.daemon/v7",
                "prime-agent.schema/v14",
            ),
        )
        self.assertIn("session.context-v1", manifest.capabilities)
        self.assertIn("ecosystem.portfolio", manifest.capabilities)
        self.assertIn("client-observations-v1", manifest.capabilities)
        self.assertIn("operations-v1", manifest.capabilities)

    def test_factory_requires_ecosystem_services_before_process_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            base = make_context(root)
            service_names = (
                "ecosystem-source-store",
                "ecosystem-materializer",
                "mcp-credential-refresh",
            )
            for service_name in service_names:
                services = dict(base.host_services)
                services.pop(service_name)
                context = ControlPlaneFactoryContext(
                    system_id=base.system_id,
                    system_version=base.system_version,
                    control_plane_id=base.control_plane_id,
                    control_plane_version=base.control_plane_version,
                    private_root=base.private_root,
                    options=base.options,
                    authority=base.authority,
                    host_services=services,
                )
                calls: list[object] = []

                with self.subTest(service_name=service_name), self.assertRaisesRegex(
                    ControlPlaneFactoryError, "host service is unavailable"
                ):
                    build_prime_control_plane_client(
                        context,
                        process_factory=lambda options: calls.append(options),
                    )
                self.assertEqual(calls, [])

    def test_factory_rejects_wrong_ecosystem_protocol_objects_before_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            base = make_context(root)
            for service_name in (
                "ecosystem-source-store",
                "ecosystem-materializer",
                "mcp-credential-refresh",
            ):
                services = dict(base.host_services)
                services[service_name] = object()
                context = ControlPlaneFactoryContext(
                    system_id=base.system_id,
                    system_version=base.system_version,
                    control_plane_id=base.control_plane_id,
                    control_plane_version=base.control_plane_version,
                    private_root=base.private_root,
                    options=base.options,
                    authority=base.authority,
                    host_services=services,
                )
                calls: list[object] = []

                with self.subTest(service_name=service_name), self.assertRaisesRegex(
                    ControlPlaneFactoryError, "host service is unavailable"
                ):
                    build_prime_control_plane_client(
                        context,
                        process_factory=lambda options: calls.append(options),
                    )
                self.assertEqual(calls, [])

    def test_factory_redacts_ecosystem_service_validation_exception(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            base = make_context(root)
            services = dict(base.host_services)
            services["ecosystem-source-store"] = ExplodingEcosystemService()
            context = ControlPlaneFactoryContext(
                system_id=base.system_id,
                system_version=base.system_version,
                control_plane_id=base.control_plane_id,
                control_plane_version=base.control_plane_version,
                private_root=base.private_root,
                options=base.options,
                authority=base.authority,
                host_services=services,
            )
            calls: list[object] = []

            with self.assertRaises(ControlPlaneFactoryError) as raised:
                build_prime_control_plane_client(
                    context,
                    process_factory=lambda options: calls.append(options),
                )

            self.assertEqual(calls, [])
            self.assertNotIn("SENTINEL_SERVICE_EXCEPTION", str(raised.exception))

    def test_packaged_manifest_matches_exact_factory_binding(self) -> None:
        manifest_path = (
            Path(__file__).resolve().parents[1]
            / "src/asterion/control/providers/prime/resources/control-plane.json"
        )
        packaged = json.loads(manifest_path.read_text())
        binding_mapping = dict(prime_control_plane_binding().manifest.to_mapping())

        self.assertEqual(packaged, binding_mapping)
        for mutation in ("extra", "missing", "version"):
            candidate = dict(packaged)
            if mutation == "extra":
                candidate["provider_payload"] = "SENTINEL_SECRET"
            elif mutation == "missing":
                candidate.pop("checkpoint_version")
            else:
                candidate["version"] = "0.2.0"
            if mutation == "version":
                self.assertNotEqual(
                    ControlPlaneManifest.from_mapping(candidate),
                    prime_control_plane_binding().manifest,
                )
                continue
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                ControlPlaneManifest.from_mapping(candidate)

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
                        make_context(root, authority=None, **overrides),
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
                authority=context.authority,
                host_services={},
            )
            with self.assertRaises(ControlPlaneFactoryError):
                build_prime_control_plane_client(
                    context,
                    process_factory=FakeProcess,
                )

            for services in (
                {"private-content": FakeResolver()},
                {"private-attachments": FakeResolver()},
            ):
                incomplete = ControlPlaneFactoryContext(
                    system_id=context.system_id,
                    system_version=context.system_version,
                    control_plane_id=context.control_plane_id,
                    control_plane_version=context.control_plane_version,
                    private_root=context.private_root,
                    options=context.options,
                    authority=context.authority,
                    host_services=services,
                )
                with self.subTest(services=tuple(services)), self.assertRaises(
                    ControlPlaneFactoryError
                ):
                    build_prime_control_plane_client(
                        incomplete,
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

            client = cast(
                PrimeControlPlaneClient,
                build_prime_control_plane_client(
                    context,
                    process_factory=process_factory,
                ),
            )

            self.assertIsInstance(client, PrimeControlPlaneClient)
            self.assertIs(bind_selected_session_context_client(client), client)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0].argv, (str((root / "node").resolve()), str((root / "main.js").resolve())))
            self.assertFalse(seen[0].private_descriptor["probeReady"])
            self.assertEqual(seen[0].private_descriptor["rlmMaxChildren"], 0)
            self.assertNotIn("SENTINEL_SECRET", repr(seen[0]))

    def test_factory_rejects_operations_v1_sidecar_without_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)

            with self.assertRaisesRegex(
                ControlPlaneFactoryError, "^Prime control plane is unavailable$"
            ):
                build_prime_control_plane_client(
                    make_context(root),
                    process_factory=NoRequestProcess,
                )

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


class TestPrimeEcosystemFactoryIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_factory_wires_awaitable_activation_through_concrete_client(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            base = make_context(root)
            materializer = WorkingEcosystemMaterializer(root / "projection")
            services = dict(base.host_services)
            services["ecosystem-materializer"] = materializer
            context = ControlPlaneFactoryContext(
                system_id=base.system_id,
                system_version=base.system_version,
                control_plane_id=base.control_plane_id,
                control_plane_version=base.control_plane_version,
                private_root=base.private_root,
                options=base.options,
                authority=base.authority,
                host_services=services,
            )
            processes: list[EcosystemProcess] = []

            def process_factory(options: PrimeSidecarLaunchOptions) -> EcosystemProcess:
                process = EcosystemProcess(options)
                processes.append(process)
                return process

            client = cast(
                PrimeControlPlaneClient,
                build_prime_control_plane_client(
                    context,
                    process_factory=process_factory,
                ),
            )
            portfolio = build_ecosystem_portfolio(
                portfolio_id="portfolio-1",
                authority_id="authority-1",
                authority_revision=1,
                resources=(),
                registrations=(),
            )

            self.assertIsInstance(client.ecosystem_service, PrimeEcosystemService)
            receipt = await client.activate_ecosystem_portfolio(portfolio)

            self.assertEqual(receipt.status, "succeeded")
            self.assertEqual(
                materializer.calls,
                [
                    ("materialize", portfolio.digest),
                    ("close", portfolio.digest),
                ],
            )
            self.assertEqual(len(processes), 1)
            self.assertEqual(len(processes[0].requests), 1)
            self.assertEqual(processes[0].requests[0]["type"], "ecosystem_activate")

    async def test_factory_snapshots_one_shot_protocols_before_process_creation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            base = make_context(root)
            source_store = OneShotSourceStore()
            materializer = OneShotMaterializer(root / "projection")
            credential_refresh = OneShotCredentialRefresh()
            services = dict(base.host_services)
            services.update(
                {
                    "ecosystem-source-store": source_store,
                    "ecosystem-materializer": materializer,
                    "mcp-credential-refresh": credential_refresh,
                }
            )
            context = ControlPlaneFactoryContext(
                system_id=base.system_id,
                system_version=base.system_version,
                control_plane_id=base.control_plane_id,
                control_plane_version=base.control_plane_version,
                private_root=base.private_root,
                options=base.options,
                authority=base.authority,
                host_services=services,
            )
            processes: list[EcosystemProcess] = []
            accesses_at_process_creation: list[tuple[dict[str, int], ...]] = []

            def process_factory(options: PrimeSidecarLaunchOptions) -> EcosystemProcess:
                accesses_at_process_creation.append(
                    (
                        dict(source_store.accesses),
                        dict(materializer.accesses),
                        dict(credential_refresh.accesses),
                    )
                )
                process = EcosystemProcess(options)
                processes.append(process)
                return process

            client = cast(
                PrimeControlPlaneClient,
                build_prime_control_plane_client(
                    context,
                    process_factory=process_factory,
                ),
            )
            portfolio = build_ecosystem_portfolio(
                portfolio_id="portfolio-1",
                authority_id="authority-1",
                authority_revision=1,
                resources=(),
                registrations=(),
            )

            receipt = await client.activate_ecosystem_portfolio(portfolio)

            self.assertEqual(receipt.status, "succeeded")
            self.assertEqual(len(processes), 1)
            self.assertEqual(
                accesses_at_process_creation,
                [
                    (
                        {"private_resource": 1, "open_file": 1},
                        {"materialize": 1, "close": 1},
                        {"refresh": 1},
                    )
                ],
            )
            self.assertEqual(materializer.calls, ["materialize", "close"])
            self.assertEqual(
                source_store.accesses,
                {"private_resource": 1, "open_file": 1},
            )
            self.assertEqual(
                materializer.accesses,
                {"materialize": 1, "close": 1},
            )
            self.assertEqual(credential_refresh.accesses, {"refresh": 1})

    async def test_binding_failure_is_fixed_and_precedes_process_creation(
        self,
    ) -> None:
        from unittest import mock as task3_mock

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_paths(root)
            context = make_context(root)
            processes: list[object] = []

            with task3_mock.patch.object(
                PrimeControlPlaneClient,
                "bind_ecosystem_service",
                side_effect=RuntimeError("SENTINEL_BINDING_EXCEPTION"),
            ), self.assertRaises(ControlPlaneFactoryError) as raised:
                build_prime_control_plane_client(
                    context,
                    process_factory=lambda options: processes.append(options),
                )

            self.assertEqual(processes, [])
            self.assertNotIn("SENTINEL_BINDING_EXCEPTION", str(raised.exception))


class TestPrimeSidecarProcess(unittest.IsolatedAsyncioTestCase):
    async def test_sidecar_creates_private_files_with_owner_only_permissions(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "session.jsonl"
            script = root / "write_private.py"
            script.write_text(
                "import json, os, pathlib, sys\n"
                "d=json.loads(os.read(int(os.environ['ASTERION_PRIME_PRIVATE_FD']),65536))\n"
                "pathlib.Path(d['output']).write_text('private')\n"
                "r=json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'protocol':'asterion.prime-gateway-ipc/v1','id':r['id'],'type':'command.accepted'}),flush=True)\n"
            )
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(sys.executable),
                    sidecar_entry=script,
                    private_descriptor={"output": str(output)},
                    environ={"PATH": os.environ.get("PATH", "")},
                )
            )
            try:
                await process.request(
                    {
                        "protocol": "asterion.prime-gateway-ipc/v1",
                        "id": "write-private",
                        "type": "command.accept",
                        "command": {},
                        "private": {},
                    }
                )
            finally:
                await process.close()

            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    async def test_attachment_execute_has_a_bounded_private_frame_exception(
        self,
    ) -> None:
        body = b"x" * (8 * 1024 * 1024)
        envelope = {
            "protocol": "asterion.prime-gateway-ipc/v1",
            "id": "attachment-request",
            "type": "session-context.execute",
            "command": {"operation": "session.attachment.bind"},
            "private": {"body_base64": base64.b64encode(body).decode("ascii")},
        }

        encoded = _encode_frame(envelope)

        self.assertGreater(len(encoded), 1024 * 1024)
        self.assertLessEqual(len(encoded), 12 * 1024 * 1024)
        with self.assertRaises(PrimeSidecarProcessError):
            _encode_frame({**envelope, "type": "command.accept"})

    async def test_cancelled_waiter_drains_stale_execute_before_cancel_ack(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "stale_then_cancel.py"
            script.write_text(
                "import json, sys\n"
                "execute = json.loads(sys.stdin.readline())\n"
                "cancel = json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'protocol':'asterion.prime-gateway-ipc/v1','id':execute['id'],'type':'session-context.receipt','receipt':{'protocol':'asterion.session-context/v1','receipt_id':'context-receipt-stale','command_id':'context-command-1','session_id':'session-1','generation':1,'operation':'session.tree.read','status':'succeeded','reason_code':'session-context-succeeded','payload':{'evidence_ref':None,'result':{'continuation_id':'continuation-1','nodes':[],'leaf_id':None}}}}), flush=True)\n"
                "print(json.dumps({'protocol':'asterion.prime-gateway-ipc/v1','id':cancel['id'],'type':'session-context.cancel.accepted'}), flush=True)\n"
            )
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(sys.executable),
                    sidecar_entry=script,
                    private_descriptor={},
                    environ={"PATH": os.environ.get("PATH", "")},
                    request_timeout=0.5,
                )
            )
            execute = asyncio.create_task(
                process.request(
                    {
                        "protocol": "asterion.prime-gateway-ipc/v1",
                        "id": "execute-stale",
                        "type": "session-context.execute",
                        "command": {},
                        "private": {},
                    }
                )
            )
            await asyncio.sleep(0.01)
            execute.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await execute
            try:
                cancel = await process.request(
                    {
                        "protocol": "asterion.prime-gateway-ipc/v1",
                        "id": "cancel-after-stale",
                        "type": "session-context.cancel",
                        "command_id": "context-command-1",
                    }
                )
            finally:
                await process.close()

            self.assertEqual(cancel["id"], "cancel-after-stale")
            self.assertEqual(cancel["type"], "session-context.cancel.accepted")

    async def test_context_execute_and_cancel_route_out_of_order_by_request_id(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "out_of_order.py"
            script.write_text(
                "import json, sys\n"
                "first = json.loads(sys.stdin.readline())\n"
                "second = json.loads(sys.stdin.readline())\n"
                "requests = {first['type']: first, second['type']: second}\n"
                "cancel = requests['session-context.cancel']\n"
                "execute = requests['session-context.execute']\n"
                "print(json.dumps({'protocol':'asterion.prime-gateway-ipc/v1','id':cancel['id'],'type':'session-context.cancel.accepted'}), flush=True)\n"
                "print(json.dumps({'protocol':'asterion.prime-gateway-ipc/v1','id':execute['id'],'type':'session-context.receipt','receipt':{'protocol':'asterion.session-context/v1','receipt_id':'context-receipt-1','command_id':'context-command-1','session_id':'session-1','generation':1,'operation':'session.tree.read','status':'succeeded','reason_code':'session-context-succeeded','payload':{'evidence_ref':None,'result':{'continuation_id':'continuation-1','nodes':[],'leaf_id':None}}}}), flush=True)\n"
            )
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(sys.executable),
                    sidecar_entry=script,
                    private_descriptor={},
                    environ={"PATH": os.environ.get("PATH", "")},
                    request_timeout=0.5,
                )
            )
            execute = asyncio.create_task(
                process.request(
                    {
                        "protocol": "asterion.prime-gateway-ipc/v1",
                        "id": "execute-request",
                        "type": "session-context.execute",
                        "command": {},
                        "private": {},
                    }
                )
            )
            cancel = asyncio.create_task(
                process.request(
                    {
                        "protocol": "asterion.prime-gateway-ipc/v1",
                        "id": "cancel-request",
                        "type": "session-context.cancel",
                        "command_id": "context-command-1",
                    }
                )
            )
            try:
                execute_response, cancel_response = await asyncio.gather(
                    execute,
                    cancel,
                )
            finally:
                await process.close()

            self.assertEqual(execute_response["type"], "session-context.receipt")
            self.assertEqual(cancel_response["type"], "session-context.cancel.accepted")
            self.assertEqual(execute_response["id"], "execute-request")
            self.assertEqual(cancel_response["id"], "cancel-request")

    async def test_child_descriptor_connects_operator_parent_socket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent_socket = root / "operator.sock"
            connected = asyncio.Event()

            async def on_connect(reader, writer):
                await reader.readexactly(1)
                connected.set()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_unix_server(on_connect, path=str(parent_socket))
            child_root = root / "children" / "child-1"
            child_root.mkdir(parents=True)
            options = derive_prime_child_control_options(
                {"max_controller_tokens": "100", "timeout_ms": "1000", "prime_socket_path": str(parent_socket)},
                child_root=child_root, child_session_id="child-session-child-1",
                child_authority=_child_envelope(authority_id="child:child-1"), generation=1,
            )
            script = root / "connect.py"
            script.write_text(
                "import json, os, socket, sys\n"
                "d=json.loads(os.read(int(os.environ['ASTERION_PRIME_PRIVATE_FD']),65536))\n"
                "s=socket.socket(socket.AF_UNIX);s.connect(d['prime_socket_path']);s.send(b'x');s.close()\n"
                "r=json.loads(sys.stdin.readline());print(json.dumps({'protocol':'asterion.prime-gateway-ipc/v1','id':r['id'],'type':'command.accepted'}),flush=True)\n"
            )
            process = await PrimeSidecarProcess.start(PrimeSidecarLaunchOptions(
                node_executable=Path(sys.executable), sidecar_entry=script,
                private_descriptor=dict(options), environ={"PATH": os.environ.get("PATH", "")},
            ))
            try:
                self.assertIsInstance(process.pid, int)
                self.assertGreater(process.pid or 0, 0)
                await asyncio.wait_for(connected.wait(), timeout=1)
            finally:
                await process.close()
                server.close()
                await server.wait_closed()
            self.assertFalse((child_root / "prime.sock").exists())
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

    async def test_sidecar_error_response_fails_closed_with_fixed_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "error.py"
            script.write_text(
                "import json, sys\n"
                "request = json.loads(sys.stdin.readline())\n"
                "sys.stdout.write(json.dumps({\n"
                "    'protocol': 'asterion.prime-gateway-ipc/v1',\n"
                "    'id': request['id'],\n"
                "    'type': 'error',\n"
                "    'code': 'prime-gateway-sidecar-failed',\n"
                "}) + '\\n')\n"
                "sys.stdout.flush()\n",
            )
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(sys.executable),
                    sidecar_entry=script,
                    private_descriptor={},
                    environ={"PATH": os.environ.get("PATH", "")},
                    close_timeout=0.2,
                    request_timeout=0.2,
                )
            )
            try:
                with self.assertRaises(PrimeSidecarProcessError) as raised:
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

            self.assertEqual(str(raised.exception), "Prime sidecar process failed")

    async def test_sidecar_malformed_error_response_fails_closed(self) -> None:
        process = PrimeSidecarProcess(
            PrimeSidecarLaunchOptions(
                node_executable=Path(sys.executable),
                sidecar_entry=Path(__file__),
                private_descriptor={},
            )
        )
        fake = FakeSubprocess(
            stdout=[
                {
                    "protocol": "asterion.prime-gateway-ipc/v1",
                    "id": "request-1",
                    "type": "error",
                    "code": "wrong",
                    "detail": "SENTINEL_SECRET",
                }
            ]
        )
        process._process = fake  # type: ignore[attr-defined]

        with self.assertRaises(PrimeSidecarProcessError) as raised:
            await process.request(
                {
                    "protocol": "asterion.prime-gateway-ipc/v1",
                    "id": "request-1",
                    "type": "events.stream",
                    "cursor": None,
                }
            )

        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    async def test_close_bounds_blocking_stdin_shutdown(self) -> None:
        process = PrimeSidecarProcess(
            PrimeSidecarLaunchOptions(
                node_executable=Path(sys.executable),
                sidecar_entry=Path(__file__),
                private_descriptor={},
                close_timeout=0.01,
            )
        )
        fake = FakeSubprocess(stdin=FakeStdin(block_wait_closed=True))
        process._process = fake  # type: ignore[attr-defined]

        await process.close()

        self.assertTrue(process.closed)
        self.assertTrue(fake.terminated)

    async def test_close_kills_when_terminate_is_ignored(self) -> None:
        process = PrimeSidecarProcess(
            PrimeSidecarLaunchOptions(
                node_executable=Path(sys.executable),
                sidecar_entry=Path(__file__),
                private_descriptor={},
                close_timeout=0.01,
            )
        )
        fake = FakeSubprocess(ignore_terminate=True)
        process._process = fake  # type: ignore[attr-defined]

        await process.close()

        self.assertTrue(fake.terminated)
        self.assertTrue(fake.killed)
        self.assertEqual(fake.returncode, -9)

    async def test_close_failure_after_kill_remains_retryable(self) -> None:
        process = PrimeSidecarProcess(
            PrimeSidecarLaunchOptions(
                node_executable=Path(sys.executable),
                sidecar_entry=Path(__file__),
                private_descriptor={},
                close_timeout=0.01,
            )
        )
        fake = FakeSubprocess(ignore_terminate=True, ignore_kill=True)
        process._process = fake  # type: ignore[attr-defined]

        with self.assertRaises(PrimeSidecarProcessError):
            await process.close()
        self.assertFalse(process.closed)

        fake.ignore_kill = False
        await process.close()
        self.assertTrue(process.closed)

    async def test_close_during_request_is_bounded_and_retryable(self) -> None:
        process = PrimeSidecarProcess(
            PrimeSidecarLaunchOptions(
                node_executable=Path(sys.executable),
                sidecar_entry=Path(__file__),
                private_descriptor={},
                close_timeout=0.01,
            )
        )
        fake = FakeSubprocess()
        process._process = fake  # type: ignore[attr-defined]
        await process._lock.acquire()  # type: ignore[attr-defined]
        try:
            with self.assertRaises(PrimeSidecarProcessError):
                await process.close()
            self.assertFalse(process.closed)
        finally:
            process._lock.release()  # type: ignore[attr-defined]

        await process.close()
        self.assertTrue(process.closed)

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

    async def test_sidecar_private_value_response_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "private_value.py"
            script.write_text(
                "import json, sys\n"
                "request = json.loads(sys.stdin.readline())\n"
                "sys.stdout.write(json.dumps({\n"
                "    'protocol': 'asterion.prime-gateway-ipc/v1',\n"
                "    'id': request['id'],\n"
                "    'type': 'private.value',\n"
                "    'text': 'SENTINEL_PRIVATE_TEXT',\n"
                "}) + '\\n')\n"
                "sys.stdout.flush()\n",
            )
            process = await PrimeSidecarProcess.start(
                PrimeSidecarLaunchOptions(
                    node_executable=Path(sys.executable),
                    sidecar_entry=script,
                    private_descriptor={},
                    environ={"PATH": os.environ.get("PATH", "")},
                    request_timeout=0.2,
                )
            )
            try:
                response = await process.request(
                    {
                        "protocol": "asterion.prime-gateway-ipc/v1",
                        "id": "request-private",
                        "type": "private.read",
                        "reference": "private:input-1",
                    }
                )
            finally:
                await process.close()

            self.assertEqual(response["type"], "private.value")
            self.assertEqual(response["text"], "SENTINEL_PRIVATE_TEXT")


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


class FakeStdin:
    def __init__(self, *, block_wait_closed: bool = False) -> None:
        self.block_wait_closed = block_wait_closed
        self._closing = False

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True

    async def wait_closed(self) -> None:
        if self.block_wait_closed:
            await asyncio.sleep(60)

    def write(self, value: bytes) -> None:
        del value

    async def drain(self) -> None:
        return None


class FakeStdout:
    def __init__(self, values: list[Mapping[str, object]]) -> None:
        self.values = list(values)

    async def readline(self) -> bytes:
        if not self.values:
            return b""
        return json.dumps(self.values.pop(0)).encode("utf-8") + b"\n"


class FakeSubprocess:
    def __init__(
        self,
        *,
        stdin: FakeStdin | None = None,
        stdout: list[Mapping[str, object]] | None = None,
        ignore_terminate: bool = False,
        ignore_kill: bool = False,
    ) -> None:
        self.stdin = stdin or FakeStdin()
        self.stdout = FakeStdout(stdout or [])
        self.returncode: int | None = None
        self.terminated = False
        self.killed = False
        self.ignore_terminate = ignore_terminate
        self.ignore_kill = ignore_kill

    def terminate(self) -> None:
        self.terminated = True
        if not self.ignore_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        if not self.ignore_kill:
            self.returncode = -9

    async def wait(self) -> int:
        while self.returncode is None:
            await asyncio.sleep(60)
        return self.returncode


if __name__ == "__main__":
    unittest.main()
