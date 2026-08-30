from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import traceback
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import cast
from unittest.mock import patch
from zipfile import ZipFile

from asterion.control.authority import (
    AuthorityEnvelope,
    BudgetLimit,
    BudgetUsage,
    PortfolioGrant,
    RemainingBudget,
)
from asterion.control.factory import (
    ControlPlaneFactoryContext,
    ControlPlaneFactoryError,
)
from asterion.control.host import ControlCommand, ControlEvent, ControlPlaneManifest
from asterion.control.protocol import CONTROL_COMMAND_TYPES, CONTROL_EVENT_TYPES
from asterion.control.providers.native.client import NativeControlPlaneClient
from asterion.control.providers.native.factory import (
    NATIVE_CONTROL_PLANE_ID,
    NATIVE_CONTROL_PLANE_VERSION,
    build_native_control_plane_client,
    native_control_plane_binding,
)
from asterion.control.providers.native.model import (
    MAX_SAFE_JSON_INTEGER,
    NativeTurnRequest,
    NativeTurnResult,
)


PROJECT = Path(__file__).resolve().parents[1]
SESSION_ID = "session-1"
GENERATION = 1


def make_authority(
    *,
    authority_id: str = "authority-1",
    revision: int = 1,
    host_service_grants: tuple[str, ...] = ("native-turn-adapter",),
    cancelled: bool = False,
) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        authority_id=authority_id,
        revision=revision,
        allowed_portfolio=(
            PortfolioGrant(
                provider_id="example.provider",
                application_id="alpha",
                version="1.0.0",
                runtime_id="fake.runtime",
            ),
        ),
        allowed_operations=(),
        budget_limit=BudgetLimit(
            controller_tokens=100,
            application_tokens=0,
            child_tokens=0,
            aggregate_tokens=100,
            cost_micros=10_000,
        ),
        expires_at_ms=2_000_000_000_000,
        max_action_deadline_ms=60_000,
        max_recursion_depth=0,
        max_concurrent_children=0,
        execution_domain="trusted-local",
        host_service_grants=host_service_grants,
        cancelled=cancelled,
    )


def make_options(**overrides: str) -> dict[str, str]:
    values = {
        "session_id": SESSION_ID,
        "generation": str(GENERATION),
        "max_turns_per_poll": "2",
        "max_events_per_poll": "10",
        "max_record_bytes": "65536",
        "max_capsule_bytes": "65536",
        "max_total_private_bytes": "1048576",
    }
    values.update(overrides)
    return values


_DEFAULT_AUTHORITY = object()


def make_context(
    private_root: Path,
    *,
    options: Mapping[str, str] | None = None,
    authority: AuthorityEnvelope | None | object = _DEFAULT_AUTHORITY,
    host_services: Mapping[str, object] | None = None,
    control_plane_id: str = NATIVE_CONTROL_PLANE_ID,
    control_plane_version: str = NATIVE_CONTROL_PLANE_VERSION,
) -> ControlPlaneFactoryContext:
    selected_authority = (
        make_authority() if authority is _DEFAULT_AUTHORITY else authority
    )
    assert selected_authority is None or isinstance(
        selected_authority,
        AuthorityEnvelope,
    )
    return ControlPlaneFactoryContext(
        system_id="research.system",
        system_version="1.0.0",
        control_plane_id=control_plane_id,
        control_plane_version=control_plane_version,
        private_root=private_root,
        options=options or make_options(),
        authority=selected_authority,
        host_services=host_services
        if host_services is not None
        else {"native-turn-adapter": CountingAdapter()},
    )


class CountingAdapter:
    adapter_id = "native.counting-turn/v1"

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        self.calls += 1
        return NativeTurnResult(request.turn_id, (), BudgetUsage.zero())


class HostileAdapter:
    adapter_id = "native.hostile-turn/v1"

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: NativeTurnRequest) -> NativeTurnResult:
        self.calls += 1
        raise AssertionError("SENTINEL_SECRET")

    def __repr__(self) -> str:
        raise AssertionError("SENTINEL_SECRET")

    def __str__(self) -> str:
        raise AssertionError("SENTINEL_SECRET")


class InvalidAdapter:
    adapter_id = "native.invalid-turn/v1"

    def __repr__(self) -> str:
        raise AssertionError("SENTINEL_SECRET")


class FakeDirectory:
    closes: list[str]

    def __init__(self) -> None:
        self.budget = object()
        self.closes = []

    @classmethod
    def open(
        cls,
        private_root: Path,
        session_id: str,
        max_total_private_bytes: int,
    ) -> FakeDirectory:
        return cls()

    def require_open(self) -> None:
        return None

    def operation(self) -> object:
        raise AssertionError("not used")

    def close(self) -> None:
        self.closes.append("owner.close")
        cleanup_events.append("owner.close")


class FakeSessionStore:
    def __init__(self, owner: FakeDirectory, *, max_record_bytes: int) -> None:
        self.owner = owner
        cleanup_events.append("journal.open")

    def replay(self, position: int = 0) -> tuple[object, ...]:
        return ()

    def append(self, expected_position: int, record: object) -> object:
        raise AssertionError("not used")

    def close(self) -> None:
        cleanup_events.append("journal.close")


class FakeCapsuleStore:
    def __init__(self, owner: FakeDirectory, *, max_capsule_bytes: int) -> None:
        self.owner = owner
        cleanup_events.append("capsule.open")

    def seal(self, **kwargs: object) -> object:
        raise AssertionError("not used")

    def verify(self, metadata: object) -> None:
        raise AssertionError("not used")

    def close(self) -> None:
        cleanup_events.append("capsule.close")


cleanup_events: list[str] = []


class TestNativeControlFactory(unittest.TestCase):
    def test_binding_declares_only_phase31_capabilities(self) -> None:
        manifest = native_control_plane_binding().manifest

        self.assertEqual(manifest.control_plane_id, "asterion.native")
        self.assertEqual(manifest.version, "0.1.0")
        self.assertEqual(manifest.commands, tuple(sorted(CONTROL_COMMAND_TYPES)))
        self.assertEqual(manifest.events, tuple(sorted(CONTROL_EVENT_TYPES)))
        self.assertEqual(
            manifest.capabilities,
            (
                "action-proposals",
                "checkpointing",
                "event-replay",
                "session-lifecycle",
            ),
        )
        self.assertEqual(
            manifest.continuation_media_type,
            "application/vnd.asterion.native-capsule",
        )
        self.assertEqual(manifest.checkpoint_version, "1.0.0")
        self.assertEqual(
            manifest.compatibility_ids,
            ("asterion.agent-control/v1", "asterion.native-controller/v1"),
        )
        self.assertNotIn("session.context-v1", manifest.capabilities)
        self.assertNotIn("operations-v1", manifest.capabilities)
        self.assertNotIn("ecosystem.portfolio", manifest.capabilities)

    def test_packaged_resource_matches_binding_and_python_validator(self) -> None:
        resource = (
            PROJECT
            / "src/asterion/control/providers/native/resources/control-plane.json"
        )
        document = json.loads(resource.read_text())
        manifest = ControlPlaneManifest.from_mapping(document)

        self.assertEqual(manifest, native_control_plane_binding().manifest)
        self.assertEqual(dict(manifest.to_mapping()), document)

    def test_package_exports_only_requested_surface(self) -> None:
        import asterion.control.providers.native as native

        self.assertEqual(
            native.__all__,
            (
                "NATIVE_CONTROL_PLANE_ID",
                "NATIVE_CONTROL_PLANE_VERSION",
                "NativeControlError",
                "NativeControlPlaneClient",
                "NativeTurnAdapter",
                "build_native_control_plane_client",
                "native_control_plane_binding",
            ),
        )

    def test_factory_rejects_missing_adapter_before_opening_private_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o700)
            context = make_context(private_root, host_services={})

            with self.assertRaisesRegex(
                ControlPlaneFactoryError, "Native turn adapter is unavailable"
            ):
                build_native_control_plane_client(context)

            self.assertEqual(tuple(context.private_root.iterdir()), ())

    def test_factory_rejects_exact_identity_and_authority_before_opening_state(
        self,
    ) -> None:
        def wrong_id(root: Path) -> ControlPlaneFactoryContext:
            return make_context(root, control_plane_id="prime.gateway")

        def wrong_version(root: Path) -> ControlPlaneFactoryContext:
            return make_context(root, control_plane_version="0.2.0")

        def missing_authority(root: Path) -> ControlPlaneFactoryContext:
            return make_context(root, authority=None)

        def missing_grant(root: Path) -> ControlPlaneFactoryContext:
            return make_context(root, authority=make_authority(host_service_grants=()))

        def cancelled_authority(root: Path) -> ControlPlaneFactoryContext:
            return make_context(root, authority=make_authority(cancelled=True))

        cases = (
            wrong_id,
            wrong_version,
            missing_authority,
            missing_grant,
            cancelled_authority,
        )
        for factory in cases:
            with (
                self.subTest(case=factory.__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                private_root = Path(temporary)
                os.chmod(private_root, 0o700)
                context = factory(private_root)

                with self.assertRaises(ControlPlaneFactoryError):
                    build_native_control_plane_client(context)

                self.assertEqual(tuple(private_root.iterdir()), ())

    def test_factory_rejects_missing_unknown_or_hostile_options_before_state(
        self,
    ) -> None:
        invalid_options = []
        for missing in make_options():
            options = make_options()
            del options[missing]
            invalid_options.append((f"missing {missing}", options))
        invalid_options.extend(
            (
                ("unknown", make_options(extra="1")),
                ("invalid session", make_options(session_id="../secret")),
                ("zero generation", make_options(generation="0")),
                ("bool generation", make_options(generation="true")),
                ("float generation", make_options(generation="1.5")),
                ("negative limit", make_options(max_record_bytes="-1")),
                ("too large limit", make_options(max_capsule_bytes=str(MAX_SAFE_JSON_INTEGER + 1))),
            )
        )
        for label, options in invalid_options:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                private_root = Path(temporary)
                os.chmod(private_root, 0o700)
                context = make_context(private_root, options=options)

                with self.assertRaisesRegex(
                    ControlPlaneFactoryError, "Native control plane options are invalid"
                ):
                    build_native_control_plane_client(context)

                self.assertEqual(tuple(private_root.iterdir()), ())

    def test_factory_rejects_insecure_private_root_before_session_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o755)
            context = make_context(private_root)

            with self.assertRaisesRegex(
                ControlPlaneFactoryError, "Native private root is unavailable"
            ):
                build_native_control_plane_client(context)

            self.assertEqual(tuple(private_root.iterdir()), ())

    def test_factory_snapshots_adapter_without_executing_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o700)
            adapter = HostileAdapter()
            context = make_context(
                private_root,
                host_services={"native-turn-adapter": adapter},
            )

            client = cast(NativeControlPlaneClient, build_native_control_plane_client(context))
            self.addCleanup(lambda: asyncio.run(client.close()))

            self.assertIsInstance(client, NativeControlPlaneClient)
            self.assertEqual(adapter.calls, 0)

    def test_invalid_adapter_failure_is_redacted_and_side_effect_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o700)
            context = make_context(
                private_root,
                host_services={"native-turn-adapter": InvalidAdapter()},
            )

            try:
                build_native_control_plane_client(context)
            except ControlPlaneFactoryError as error:
                rendered = "".join(traceback.format_exception(error))
                self.assertIn("Native turn adapter is unavailable", str(error))
                self.assertNotIn("SENTINEL_SECRET", rendered)
                self.assertNotIn(str(private_root), rendered)
                self.assertEqual(tuple(private_root.iterdir()), ())
            else:
                self.fail("factory accepted invalid adapter")

    def test_factory_cleans_up_opened_resources_in_stage_order_on_late_failure(
        self,
    ) -> None:
        cleanup_events.clear()

        class FailingController:
            def __init__(self, **kwargs: object) -> None:
                cleanup_events.append("controller.open")
                raise RuntimeError("SENTINEL_SECRET")

        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o700)
            context = make_context(private_root)
            with (
                patch(
                    "asterion.control.providers.native.factory.NativeSessionDirectory",
                    FakeDirectory,
                ),
                patch(
                    "asterion.control.providers.native.factory.FileNativeSessionStore",
                    FakeSessionStore,
                ),
                patch(
                    "asterion.control.providers.native.factory.FileNativeCapsuleStore",
                    FakeCapsuleStore,
                ),
                patch(
                    "asterion.control.providers.native.factory.NativeController",
                    FailingController,
                ),
            ):
                with self.assertRaises(ControlPlaneFactoryError):
                    build_native_control_plane_client(context)

        self.assertEqual(
            cleanup_events,
            (
                ["journal.open", "capsule.open", "controller.open"]
                + ["capsule.close", "journal.close", "owner.close"]
            ),
        )

    def test_factory_transfers_close_ownership_to_client_only_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o700)
            context = make_context(private_root)
            client = cast(
                NativeControlPlaneClient,
                build_native_control_plane_client(context),
            )

            session_children = tuple(private_root.iterdir())
            self.assertEqual(len(session_children), 1)
            with self.assertRaises(ControlPlaneFactoryError):
                build_native_control_plane_client(context)

            asyncio.run(client.close())
            reopened = cast(
                NativeControlPlaneClient,
                build_native_control_plane_client(context),
            )
            asyncio.run(reopened.close())

    def test_factory_reopens_existing_state_with_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o700)
            context = make_context(private_root)
            client = cast(
                NativeControlPlaneClient,
                build_native_control_plane_client(context),
            )

            async def create_and_reopen() -> tuple[ControlEvent, ...]:
                await client.send(
                    ControlCommand(
                        command_id="command-create",
                        session_id=SESSION_ID,
                        authority_revision=1,
                        type="session.create",
                        payload={
                            "system_id": "research.system",
                            "system_version": "1.0.0",
                            "goal_id": "goal-1",
                            "goal_ref": "goal-ref-1",
                        },
                    )
                )
                await client.sync_authority_snapshot(
                    RemainingBudget(100, 0, 0, 100, 10_000, 60_000)
                )
                await client.close()
                reopened = cast(
                    NativeControlPlaneClient,
                    build_native_control_plane_client(context),
                )
                try:
                    result = []
                    async for event in reopened.events():
                        result.append(event)
                    return tuple(result)
                finally:
                    await reopened.close()

            events = asyncio.run(create_and_reopen())

            self.assertEqual(
                tuple(event.type for event in events),
                ("session.created", "session.running"),
            )

    def test_existing_state_rejects_wrong_system_session_generation_or_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_root = Path(temporary)
            os.chmod(private_root, 0o700)
            context = make_context(private_root)

            async def create() -> None:
                client = cast(
                    NativeControlPlaneClient,
                    build_native_control_plane_client(context),
                )
                try:
                    await client.send(
                        ControlCommand(
                            command_id="command-create",
                            session_id=SESSION_ID,
                            authority_revision=1,
                            type="session.create",
                            payload={
                                "system_id": "research.system",
                                "system_version": "1.0.0",
                                "goal_id": "goal-1",
                                "goal_ref": "goal-ref-1",
                            },
                        )
                    )
                finally:
                    await client.close()

            asyncio.run(create())
            cases = (
                make_context(private_root, options=make_options(generation="2")),
                make_context(private_root, authority=make_authority(authority_id="authority-2")),
                ControlPlaneFactoryContext(
                    system_id="other.system",
                    system_version="1.0.0",
                    control_plane_id=NATIVE_CONTROL_PLANE_ID,
                    control_plane_version=NATIVE_CONTROL_PLANE_VERSION,
                    private_root=private_root,
                    options=make_options(),
                    authority=make_authority(),
                    host_services={"native-turn-adapter": CountingAdapter()},
                ),
            )
            for bad_context in cases:
                with self.subTest(context=repr(bad_context)):
                    with self.assertRaises(ControlPlaneFactoryError):
                        build_native_control_plane_client(bad_context)

    def test_wheel_contains_native_resource_and_imports_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            subprocess.run(
                ("uv", "build", "--wheel", "--out-dir", str(destination), "."),
                cwd=PROJECT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            wheel = next(destination.glob("*.whl"))
            with ZipFile(wheel) as archive:
                members = frozenset(archive.namelist())
                packaged = (
                    "asterion/control/providers/native/resources/control-plane.json"
                )
                self.assertIn(packaged, members)
                self.assertEqual(
                    json.loads(archive.read(packaged)),
                    native_control_plane_binding().manifest.to_mapping(),
                )
                archive.extractall(destination / "installed")

            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(destination / "installed")
            completed = subprocess.run(
                (
                    sys.executable,
                    "-c",
                    "import json; "
                    "from importlib import resources; "
                    "from asterion.control.providers.native.factory import "
                    "native_control_plane_binding; "
                    "body = resources.files('asterion.control.providers.native')"
                    ".joinpath('resources/control-plane.json').read_text(); "
                    "print(json.dumps({"
                    "'resource': json.loads(body), "
                    "'binding': native_control_plane_binding().manifest.to_mapping()"
                    "}, sort_keys=True, separators=(',', ':')))",
                ),
                cwd=destination,
                env=environment,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            result = json.loads(completed.stdout)
            self.assertEqual(result["resource"], result["binding"])
            self.assertNotIn(str(PROJECT), completed.stdout)


if __name__ == "__main__":
    unittest.main()
