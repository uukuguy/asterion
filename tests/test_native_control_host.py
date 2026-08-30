from __future__ import annotations

import asyncio
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from asterion.control.authority import (
    AuthorityLedger,
    AuthorityEnvelope,
    BudgetLimit,
    BudgetUsage,
    PortfolioGrant,
)
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.factory import ControlPlaneFactoryRegistry
from asterion.control.journal import JournalCursor, MemoryCanonicalJournal
from asterion.control.manager import ControlHost
from asterion.control.providers.native.factory import native_control_plane_binding
from asterion.control.providers.native.model import NativeEventDraft
from asterion.control.system import resolve_agent_system
from asterion.pathlight import MemoryPathlightRecorder
from asterion.runtime.host import CancellationSignal
from tests.test_control_pathlight import _opaque_id
from tests.test_control_system import _manifest, _provider
from tests.test_native_control_conformance import (
    OperationRecorder,
    complete_drafts,
    input_command,
    make_native_client,
    native_authority,
    proposal_draft,
)


class RecordingExecutor:
    def __init__(
        self,
        recorder: OperationRecorder,
        *,
        receipt_ref: str = "receipt-1",
    ) -> None:
        self._recorder = recorder
        self._receipt_ref = receipt_ref
        self.action_ids: list[str] = []

    async def execute(
        self,
        proposal: object,
        signal: CancellationSignal,
    ) -> ActionExecutionReceipt:
        del signal
        action_id = str(cast(Mapping[str, object], cast(object, proposal).payload)["action_id"])  # type: ignore[attr-defined]
        self.action_ids.append(action_id)
        self._recorder.executor_calls += 1
        return ActionExecutionReceipt(
            action_id=action_id,
            receipt_ref=self._receipt_ref,
            usage=BudgetUsage(0, 10, 0, 10, 500),
            artifact_ids=("artifact-1",),
            media_types=("application/json",),
        )


class MutableSignal:
    def __init__(self, cancelled: bool = False) -> None:
        self.cancelled = cancelled


def _native_plan(root: Path):
    manifest = dict(_manifest())
    manifest["control_plane"] = {
        "control_plane_id": "asterion.native",
        "version": "0.1.0",
    }
    return resolve_agent_system(
        manifest,
        application_providers=(_provider(root),),
        control_factories=ControlPlaneFactoryRegistry((native_control_plane_binding(),)),
        host_capabilities=("clock.monotonic", "storage.private"),
    )


def make_host_with_native(
    scripts: Mapping[str, tuple[NativeEventDraft, ...] | BaseException],
    *,
    authority_kwargs: Mapping[str, object] | None = None,
    signal: MutableSignal | None = None,
    journal: MemoryCanonicalJournal | None = None,
    pathlight: MemoryPathlightRecorder | None = None,
    private_root: Path | None = None,
    directory: tempfile.TemporaryDirectory[str] | None = None,
) -> tuple[ControlHost, object, RecordingExecutor]:
    authority = _authority_from_kwargs(authority_kwargs)
    native = make_native_client(
        scripts,
        authority=authority,
        private_root=private_root,
        directory=directory,
    )
    application_root = native.private_root / "applications"
    application_root.mkdir(exist_ok=True)
    plan = _native_plan(application_root)
    executor = RecordingExecutor(native.recorder)
    host = ControlHost(
        session_id="session-1",
        generation=1,
        plan=plan,
        authority=AuthorityLedger(authority),
        journal=journal or MemoryCanonicalJournal("session-1"),
        client=native.client,  # type: ignore[arg-type]
        action_executor=executor,
        clock_ms=lambda: 1_000,
        cancellation_signal=signal,
        pathlight=pathlight if pathlight is not None else MemoryPathlightRecorder(_opaque_id(700)),
    )
    host._task8_native = native  # type: ignore[attr-defined]
    return host, native.client, executor


def _authority_from_kwargs(
    authority_kwargs: Mapping[str, object] | None,
) -> AuthorityEnvelope:
    values = authority_kwargs or {}
    return native_authority(
        budget_limit=cast(BudgetLimit | None, values.get("budget_limit")),
        allowed_portfolio=cast(
            tuple[PortfolioGrant, ...] | None,
            values.get("allowed_portfolio"),
        ),
        allowed_operations=cast(
            tuple[str, ...],
            values.get("allowed_operations", ("application.invoke", "child.spawn")),
        ),
        cancelled=cast(bool, values.get("cancelled", False)),
    )


async def close_host(host: ControlHost) -> None:
    native = cast(object, getattr(host, "_task8_native"))
    await host.close()
    directory = cast(object, native).directory  # type: ignore[attr-defined]
    if directory is not None:
        directory.cleanup()  # type: ignore[attr-defined]


def one_action_script(
    *,
    application_id: str = "alpha",
) -> Mapping[str, tuple[NativeEventDraft, ...]]:
    return {
        "input:content-ref-action": (proposal_draft(application_id=application_id),),
        "action:action-1:succeeded": complete_drafts(1),
    }


class TestNativeControlHost(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        return None

    async def test_host_admits_and_executes_native_proposal_exactly_once(self) -> None:
        host, _, executor = make_host_with_native(one_action_script())
        try:
            await host.dispatch(host.client_command(
                command_id="create-1",
                command_type="session.create",
                payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
            ))
            await host.dispatch(input_command("input-1", "content-ref-action", input_id="input-1"))
            await asyncio.wait_for(host.pump(until_terminal=True), timeout=3)

            self.assertEqual(executor.action_ids, ["action-1"])
            self.assertEqual(host.snapshot().state.session_status, "completed")
            command_resolutions = [
                cast(Mapping[str, object], entry.record.payload["command"])["payload"]
                for entry in host._journal.replay(JournalCursor(0))  # type: ignore[attr-defined]
                if entry.record.kind == "command.accepted"
                and cast(Mapping[str, object], entry.record.payload["command"])["type"]
                == "action.resolve"
            ]
            self.assertEqual(
                tuple(cast(Mapping[str, object], payload)["resolution"] for payload in command_resolutions),
                ("admitted", "succeeded"),
            )
        finally:
            await close_host(host)

    async def test_rejected_native_proposal_never_contacts_executor(self) -> None:
        host, _, executor = make_host_with_native(
            one_action_script(application_id="zeta"),
            authority_kwargs={
                "allowed_portfolio": (
                    PortfolioGrant(
                        provider_id="example.provider",
                        application_id="alpha",
                        version="1.0.0",
                        runtime_id="fake.runtime",
                    ),
                )
            },
        )
        try:
            await host.dispatch(host.client_command(
                command_id="create-1",
                command_type="session.create",
                payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
            ))
            await host.dispatch(input_command("input-1", "content-ref-action", input_id="input-1"))
            await asyncio.wait_for(host.pump(), timeout=3)

            self.assertEqual(executor.action_ids, [])
            self.assertEqual(host.snapshot().state.actions["action-1"].status, "rejected")
        finally:
            await close_host(host)

    async def test_cancelled_native_proposal_never_contacts_executor(self) -> None:
        signal = MutableSignal(cancelled=True)
        host, _, executor = make_host_with_native(
            {
                "input:content-ref-action": (proposal_draft(),),
                "action:action-1:cancelled": complete_drafts(0),
            },
            signal=signal,
        )
        try:
            await host.dispatch(host.client_command(
                command_id="create-1",
                command_type="session.create",
                payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
            ))
            await host.dispatch(input_command("input-1", "content-ref-action", input_id="input-1"))
            await asyncio.wait_for(host.pump(until_terminal=True), timeout=3)

            self.assertEqual(executor.action_ids, [])
            self.assertEqual(host.snapshot().state.actions["action-1"].status, "cancelled")
        finally:
            await close_host(host)

    async def test_budget_rejected_native_proposal_never_contacts_executor(self) -> None:
        host, _, executor = make_host_with_native(
            {"input:content-ref-action": (proposal_draft(),)},
            authority_kwargs={
                "budget_limit": BudgetLimit(100, 0, 100, 100, 100_000),
            },
        )
        try:
            await host.dispatch(host.client_command(
                command_id="create-1",
                command_type="session.create",
                payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
            ))
            await host.dispatch(input_command("input-1", "content-ref-action", input_id="input-1"))
            await asyncio.wait_for(host.pump(), timeout=3)

            self.assertEqual(executor.action_ids, [])
            self.assertEqual(host.snapshot().state.actions["action-1"].status, "rejected")
        finally:
            await close_host(host)

    async def test_authority_retry_and_terminal_recovery_do_not_reexecute(self) -> None:
        journal = MemoryCanonicalJournal("session-1")
        host, _, executor = make_host_with_native(one_action_script(), journal=journal)
        native = cast(object, getattr(host, "_task8_native"))
        try:
            await host.dispatch(host.client_command(
                command_id="create-1",
                command_type="session.create",
                payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
            ))
            await host.dispatch(input_command("input-1", "content-ref-action", input_id="input-1"))
            await asyncio.wait_for(host.pump(until_terminal=True), timeout=3)
            self.assertEqual(executor.action_ids, ["action-1"])
        finally:
            await host.close()

        resumed, _, resumed_executor = make_host_with_native(
            one_action_script(),
            journal=journal,
            private_root=cast(Path, native.private_root),  # type: ignore[attr-defined]
            directory=cast(tempfile.TemporaryDirectory[str], native.directory),  # type: ignore[attr-defined]
        )
        try:
            await asyncio.wait_for(resumed.pump(), timeout=3)
            self.assertEqual(resumed_executor.action_ids, [])
            self.assertEqual(resumed.snapshot().state.session_status, "completed")
        finally:
            await close_host(resumed)

    async def test_pathlight_and_public_journal_redact_native_private_paths(self) -> None:
        recorder = MemoryPathlightRecorder(_opaque_id(701))
        host, _, _ = make_host_with_native(
            {
                "input:content-ref-action": (proposal_draft(),),
                "action:action-1:succeeded": complete_drafts(1),
            },
            pathlight=recorder,
        )
        try:
            await host.dispatch(host.client_command(
                command_id="create-1",
                command_type="session.create",
                payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
            ))
            await host.dispatch(input_command("input-1", "content-ref-action", input_id="input-1"))
            await asyncio.wait_for(host.pump(until_terminal=True), timeout=3)
            graph = recorder.snapshot()
            self.assertIsNotNone(graph)
            rendered = repr((graph, host._journal.replay(JournalCursor(0)), host.snapshot()))  # type: ignore[attr-defined]
            self.assertNotIn("SENTINEL_SECRET", rendered)
            self.assertNotIn(str(Path.cwd()), rendered)
        finally:
            await close_host(host)


if __name__ == "__main__":
    unittest.main()
