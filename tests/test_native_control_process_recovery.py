from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from asterion.control.authority import AuthorityLedger, BudgetUsage
from asterion.control.execution import ActionExecutionReceipt
from asterion.control.host import ControlEvent
from asterion.control.journal import FileCanonicalJournal, JournalCursor, JournalEntry
from asterion.control.manager import ControlHost
from asterion.control.providers.native.capsule import FileNativeCapsuleStore
from asterion.control.providers.native.client import NativeControlPlaneClient
from asterion.control.providers.native.controller import NativeController
from asterion.control.providers.native.controller import NativeControllerError
from asterion.control.providers.native.factory import (
    NATIVE_CHECKPOINT_VERSION,
    NATIVE_CONTROL_PLANE_VERSION,
    native_control_plane_binding,
)
from asterion.control.providers.native.model import NativeEntry, NativeEventDraft
from asterion.control.providers.native.state import reduce_native_entries
from asterion.control.providers.native.store import (
    FileNativeSessionStore,
    NativeRootIdentity,
    NativeSessionDirectory,
)
from asterion.pathlight import MemoryPathlightRecorder
from asterion.runtime.host import CancellationSignal
from tests.test_control_pathlight import _opaque_id
from tests.test_native_control_conformance import (
    AUTHORITY_ID,
    AUTHORITY_REVISION,
    GENERATION,
    SESSION_ID,
    OperationRecorder,
    ScriptedNativeTurnAdapter,
    budget_draft,
    checkpoint_command,
    collect_events,
    complete_drafts,
    create_command,
    draft,
    input_command,
    native_authority,
    proposal_draft,
    remaining_budget,
)
from tests.test_native_control_host import _native_plan


CRASH_POINTS = (
    "command-before-publish",
    "command-after-publish-before-ack",
    "turn-after-start",
    "turn-after-adapter-before-commit",
    "turn-after-commit-before-yield",
    "capsule-after-write-before-checkpoint",
    "checkpoint-after-commit-before-yield",
    "terminal-after-commit-before-host-receipt",
)

_TERMINAL_EVENTS = frozenset(
    {
        "session.budget-limited",
        "session.cancelled",
        "session.completed",
        "session.failed",
    }
)
_OBSERVATION_KEYS = frozenset(
    {
        "crash_point",
        "status",
        "duplicate_commands",
        "duplicate_turns",
        "duplicate_actions",
        "sequence_gaps",
        "terminal_count",
        "owned_processes_after_close",
        "provider_operations",
        "model_operations",
        "credential_reads",
        "network_operations",
        "application_operations",
        "upload_operations",
    }
)


def run_worker(
    root: Path,
    *,
    crash_point: str | None,
    report_point: str | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if crash_point is None:
        env.pop("ASTERION_NATIVE_TEST_CRASH_POINT", None)
    else:
        env["ASTERION_NATIVE_TEST_CRASH_POINT"] = crash_point
    if report_point is None:
        env.pop("ASTERION_NATIVE_TEST_REPORT_POINT", None)
    else:
        env["ASTERION_NATIVE_TEST_REPORT_POINT"] = report_point
    return subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from tests.test_native_control_process_recovery import "
                "_worker_main; _worker_main()"
            ),
            str(root),
        ],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )


def run_native_crash_observations() -> tuple[Mapping[str, object], ...]:
    observations: list[Mapping[str, object]] = []
    for crash_point in CRASH_POINTS:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = run_worker(root, crash_point=crash_point)
            _assert_boundary_crash(root, crash_point, first)
            recovered = run_worker(root, crash_point=None, report_point=crash_point)
            report = _parse_recovered_report(crash_point, recovered)
            _assert_pass_observation(crash_point, report)
            observations.append(report)
    return tuple(observations)


class TestNativeControlProcessRecovery(unittest.TestCase):
    def test_every_named_crash_point_recovers_without_duplicates(self) -> None:
        observations = run_native_crash_observations()
        self.assertEqual(
            tuple(item["crash_point"] for item in observations),
            tuple(CRASH_POINTS),
        )

    def test_observations_are_closed_and_provider_free(self) -> None:
        for observation in run_native_crash_observations():
            with self.subTest(crash_point=observation["crash_point"]):
                _assert_pass_observation(str(observation["crash_point"]), observation)
                for key in (
                    "provider_operations",
                    "model_operations",
                    "credential_reads",
                    "network_operations",
                    "application_operations",
                    "upload_operations",
                ):
                    self.assertEqual(observation[key], 0)

    def test_boundary_crash_requires_exact_code_and_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wrong_code = subprocess.CompletedProcess(
                args=(),
                returncode=1,
                stdout="",
                stderr="",
            )
            with self.assertRaises(AssertionError):
                _assert_boundary_crash(root, CRASH_POINTS[0], wrong_code)

            right_code_missing_marker = subprocess.CompletedProcess(
                args=(),
                returncode=101,
                stdout="",
                stderr="",
            )
            with self.assertRaises(AssertionError):
                _assert_boundary_crash(root, CRASH_POINTS[0], right_code_missing_marker)

            _write_crash_marker(root, CRASH_POINTS[1])
            with self.assertRaises(AssertionError):
                _assert_boundary_crash(root, CRASH_POINTS[0], right_code_missing_marker)

    def test_recovered_report_requires_empty_stderr_and_canonical_stdout(self) -> None:
        report = _pass_report(CRASH_POINTS[0])
        valid_stdout = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
        valid_process = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout=valid_stdout,
            stderr="",
        )
        self.assertEqual(_parse_recovered_report(CRASH_POINTS[0], valid_process), report)

        noisy_stderr = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout=valid_stdout,
            stderr="SENTINEL_SECRET\n",
        )
        with self.assertRaises(AssertionError):
            _parse_recovered_report(CRASH_POINTS[0], noisy_stderr)

        noncanonical_stdout = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout=json.dumps(report, sort_keys=True, indent=2) + "\n",
            stderr="",
        )
        with self.assertRaises(AssertionError):
            _parse_recovered_report(CRASH_POINTS[0], noncanonical_stdout)

        extra_stdout = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout=valid_stdout + valid_stdout,
            stderr="",
        )
        with self.assertRaises(AssertionError):
            _parse_recovered_report(CRASH_POINTS[0], extra_stdout)

    def test_observation_rejects_bool_subclass_and_extra_fields(self) -> None:
        report = _pass_report(CRASH_POINTS[0])
        for key, value in (
            ("duplicate_commands", False),
            ("terminal_count", True),
            ("status", _StrSubclass("PASS")),
            ("crash_point", _StrSubclass(CRASH_POINTS[0])),
        ):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                tampered = dict(report)
                tampered[key] = value
                _assert_pass_observation(CRASH_POINTS[0], tampered)
        with self.assertRaises(AssertionError):
            _assert_pass_observation(CRASH_POINTS[0], {**report, "extra": 0})

    def test_process_registry_counts_live_and_reaped_children(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = _ProcessRegistry(Path(directory) / "processes.json")
            sleeper = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                registry.register(sleeper)
                self.assertEqual(registry.active_count(), 1)
                sleeper.terminate()
                sleeper.wait(timeout=5)
                registry.reap(sleeper)
                self.assertEqual(registry.active_count(), 0)
            finally:
                if sleeper.poll() is None:
                    sleeper.kill()
                    sleeper.wait(timeout=5)

    def test_crash_hook_exceptions_are_redacted_and_controlled(self) -> None:
        async def run_case(
            crash_hook: Callable[[str], None],
            expected_type: type[BaseException],
        ) -> None:
            with tempfile.TemporaryDirectory() as directory:
                controller = _open_native_controller(
                    Path(directory) / "native",
                    OperationRecorder(),
                    crash_hook,
                    scripts={"input:content-ref-step": (budget_draft(1),)},
                )
                try:
                    with self.assertRaises(expected_type) as raised:
                        await controller.accept(create_command())
                    self.assertIsNone(raised.exception.__cause__)
                    self.assertIsNone(raised.exception.__context__)
                    if expected_type is NativeControllerError:
                        self.assertEqual(
                            raised.exception.args,
                            ("native controller is unavailable",),
                        )
                    else:
                        self.assertEqual(raised.exception.args, ())
                    self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
                finally:
                    try:
                        controller.close()
                    except Exception:
                        pass

        for crash_hook, expected_type in (
            (_raising_crash_hook(RuntimeError("SENTINEL_SECRET")), NativeControllerError),
            (_raising_crash_hook(KeyboardInterrupt("SENTINEL_SECRET")), KeyboardInterrupt),
            (_raising_crash_hook(SystemExit("SENTINEL_SECRET")), SystemExit),
            (_raising_crash_hook(GeneratorExit("SENTINEL_SECRET")), GeneratorExit),
            (_raising_crash_hook(_HostileBase("SENTINEL_SECRET")), NativeControllerError),
        ):
            with self.subTest(expected_type=expected_type.__name__):
                asyncio.run(run_case(crash_hook, expected_type))


class _StrSubclass(str):
    pass


class _HostileBase(BaseException):
    pass


def _raising_crash_hook(error: BaseException) -> Callable[[str], None]:
    def hook(_point: str) -> None:
        raise error

    return hook


def _assert_pass_observation(
    crash_point: str, report: Mapping[str, object]
) -> None:
    if frozenset(report) != _OBSERVATION_KEYS:
        raise AssertionError(f"{crash_point} emitted non-closed report")
    if type(report["crash_point"]) is not str or report["crash_point"] != crash_point:
        raise AssertionError(f"{crash_point} emitted invalid crash identity")
    if type(report["status"]) is not str or report["status"] != "PASS":
        raise AssertionError(f"{crash_point} emitted invalid status")
    for key in _OBSERVATION_KEYS - {"crash_point", "status"}:
        value = report[key]
        if type(value) is not int:
            raise AssertionError(f"{crash_point} emitted invalid counter")
    expected = _pass_report(crash_point)
    if dict(report) != expected:
        raise AssertionError(f"{crash_point} failed invariants: {report!r}")


def _pass_report(crash_point: str) -> dict[str, object]:
    return {
        "crash_point": crash_point,
        "status": "PASS",
        "duplicate_commands": 0,
        "duplicate_turns": 0,
        "duplicate_actions": 0,
        "sequence_gaps": 0,
        "terminal_count": 1,
        "owned_processes_after_close": 0,
        "provider_operations": 0,
        "model_operations": 0,
        "credential_reads": 0,
        "network_operations": 0,
        "application_operations": 0,
        "upload_operations": 0,
    }


def _parse_recovered_report(
    crash_point: str, recovered: subprocess.CompletedProcess[str]
) -> Mapping[str, object]:
    if recovered.returncode != 0:
        raise AssertionError(f"{crash_point} recovered child failed")
    if recovered.stderr != "":
        raise AssertionError(f"{crash_point} recovered child emitted stderr")
    try:
        loaded = json.loads(recovered.stdout)
    except json.JSONDecodeError:
        raise AssertionError(f"{crash_point} emitted non-json report") from None
    canonical_stdout = json.dumps(
        loaded,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    if recovered.stdout != canonical_stdout:
        raise AssertionError(f"{crash_point} emitted non-canonical report")
    if not isinstance(loaded, Mapping):
        raise AssertionError(f"{crash_point} emitted non-object report")
    return loaded


def _assert_boundary_crash(
    root: Path, crash_point: str, first: subprocess.CompletedProcess[str]
) -> None:
    if first.returncode != 101:
        raise AssertionError(f"{crash_point} did not exit at the injected boundary")
    if first.stdout != "" or first.stderr != "":
        raise AssertionError(f"{crash_point} emitted non-redacted crash output")
    marker_path = _crash_marker_path(root)
    if not marker_path.exists():
        raise AssertionError(f"{crash_point} did not write a durable crash marker")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker != {"crash_point": crash_point}:
        raise AssertionError(f"{crash_point} crash marker mismatches")
    marker_path.unlink()


def _worker_main() -> None:
    root = Path(sys.argv[1])
    crash_point = os.environ.get("ASTERION_NATIVE_TEST_CRASH_POINT")
    if crash_point is not None and crash_point not in CRASH_POINTS:
        raise SystemExit(2)
    report_point = os.environ.get("ASTERION_NATIVE_TEST_REPORT_POINT", crash_point)
    if report_point is not None and report_point not in CRASH_POINTS:
        raise SystemExit(2)
    if report_point == "terminal-after-commit-before-host-receipt":
        report = asyncio.run(_run_host_worker(root, report_point))
    else:
        report = asyncio.run(_run_controller_worker(root, report_point))
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))


def _crash_hook_from_env() -> Callable[[str], None]:
    target = os.environ.get("ASTERION_NATIVE_TEST_CRASH_POINT")

    def hook(point: str) -> None:
        if point == target:
            _write_crash_marker(Path(sys.argv[1]), point)
            os._exit(101)

    return hook


def _write_crash_marker(root: Path, crash_point: str) -> None:
    marker_path = _crash_marker_path(root)
    marker_path.write_text(
        json.dumps({"crash_point": crash_point}, sort_keys=True),
        encoding="utf-8",
    )


def _crash_marker_path(root: Path) -> Path:
    return root / "crash-marker.json"


async def _run_controller_worker(
    root: Path, crash_point: str | None
) -> Mapping[str, object]:
    recorder = OperationRecorder()
    client = _open_native_client(
        root / "native",
        recorder,
        _crash_hook_from_env(),
        scripts={
            "input:content-ref-step": (budget_draft(1),),
            "input:content-ref-complete": _complete_drafts(),
        },
    )
    try:
        await client.send(create_command())
        await client.sync_authority_snapshot(remaining_budget())
        await client.send(checkpoint_command())
        await client.send(
            input_command(
                "command-step",
                "content-ref-step",
                input_id="input-step",
            )
        )
        await collect_events(client)
        await client.send(
            input_command(
                "command-complete",
                "content-ref-complete",
                input_id="input-complete",
            )
        )
        await collect_events(client)
    finally:
        await client.close()
    return _build_report(root, crash_point, recorder)


async def _run_host_worker(root: Path, crash_point: str | None) -> Mapping[str, object]:
    recorder = OperationRecorder()
    private_root = root / "native"
    journal_root = root / "journal"
    application_root = root / "applications"
    application_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    executor = _DurableReceiptExecutor(root / "executor-calls.json", recorder)
    client = _open_native_client(private_root, recorder, _crash_hook_from_env())
    journal = FileCanonicalJournal.open(journal_root, SESSION_ID)
    host = ControlHost(
        session_id=SESSION_ID,
        generation=GENERATION,
        plan=_native_plan(application_root),
        authority=AuthorityLedger(native_authority()),
        journal=journal,
        client=client,
        action_executor=executor,
        clock_ms=lambda: 1_000,
        cancellation_signal=None,
        pathlight=MemoryPathlightRecorder(_opaque_id(900)),
    )
    try:
        command_ids = _host_command_ids(journal_root)
        if "create-1" not in command_ids:
            await host.dispatch(
                host.client_command(
                    command_id="create-1",
                    command_type="session.create",
                    payload={"goal_id": "goal-1", "goal_ref": "goal-ref-1"},
                )
            )
        if "input-1" not in command_ids:
            await host.dispatch(
                host.client_command(
                    command_id="input-1",
                    command_type="input.submit",
                    payload={
                        "input_id": "input-1",
                        "delivery": "direct",
                        "content_ref": "content-ref-action",
                    },
                )
            )
        if host.snapshot().state.terminal_event_id is None:
            await asyncio.wait_for(host.pump(until_terminal=True), timeout=5)
    finally:
        await host.close()
    return _build_report(root, crash_point, recorder)


def _open_native_client(
    private_root: Path,
    recorder: OperationRecorder,
    crash_hook: Callable[[str], None],
    *,
    scripts: Mapping[str, tuple[NativeEventDraft, ...] | BaseException] | None = None,
) -> NativeControlPlaneClient:
    controller = _open_native_controller(
        private_root,
        recorder,
        crash_hook,
        scripts=scripts,
    )
    return NativeControlPlaneClient(
        manifest=native_control_plane_binding().manifest,
        controller=controller,
        max_turns_per_poll=10,
        max_events_per_poll=50,
    )


def _open_native_controller(
    private_root: Path,
    recorder: OperationRecorder,
    crash_hook: Callable[[str], None],
    *,
    scripts: Mapping[str, tuple[NativeEventDraft, ...] | BaseException] | None = None,
) -> NativeController:
    private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_root.chmod(0o700)
    next_event_ordinal = _next_event_ordinal(private_root)
    owner = NativeSessionDirectory.open(
        private_root,
        SESSION_ID,
        1_048_576,
        expected_root_identity=_root_identity(private_root),
    )
    store = FileNativeSessionStore(owner, max_record_bytes=65_536)
    capsules = FileNativeCapsuleStore(owner, max_capsule_bytes=65_536)
    adapter = ScriptedNativeTurnAdapter(
        scripts
        or {
            "input:content-ref-action": (proposal_draft(),),
            "action:action-1:succeeded": complete_drafts(1),
        },
        recorder,
    )
    return NativeController(
        owner=owner,
        session_store=store,
        capsule_store=capsules,
        turn_adapter=adapter,
        provider_id="native",
        provider_version=NATIVE_CONTROL_PLANE_VERSION,
        system_id="research.system",
        system_version="1.0.0",
        session_id=SESSION_ID,
        generation=GENERATION,
        checkpoint_version=NATIVE_CHECKPOINT_VERSION,
        authority_id=AUTHORITY_ID,
        authority_revision=AUTHORITY_REVISION,
        event_id_factory=_DeterministicIdFactory("event", next_event_ordinal),
        turn_id_factory=_DeterministicIdFactory("turn"),
        capsule_id_factory=_DeterministicIdFactory("capsule"),
        clock=lambda: "2026-08-30T00:00:00Z",
        crash_hook=crash_hook,
    )


def _complete_drafts() -> tuple[NativeEventDraft, ...]:
    return (
        budget_draft(1),
        draft("goal.updated", {"goal_id": "goal-1", "status": "completed"}),
        draft("session.completed", {"reason_code": "goal-accepted"}),
    )


def _root_identity(path: Path) -> NativeRootIdentity:
    result = path.stat(follow_symlinks=False)
    return NativeRootIdentity(result.st_dev, result.st_ino)


def _next_event_ordinal(root: Path) -> int:
    return len(_native_events(_native_entries(root)))


@dataclass
class _DeterministicIdFactory:
    prefix: str
    value: int = 0

    def __call__(self) -> str:
        self.value += 1
        return f"{self.prefix}-{self.value}"


class _DurableReceiptExecutor:
    def __init__(self, path: Path, recorder: OperationRecorder) -> None:
        self._path = path
        self._recorder = recorder

    async def execute(
        self, proposal: ControlEvent, signal: CancellationSignal
    ) -> ActionExecutionReceipt:
        del signal
        action_id = str(cast(Mapping[str, object], proposal.payload)["action_id"])
        calls = _read_json_list(self._path)
        calls.append(action_id)
        self._path.write_text(json.dumps(calls, sort_keys=True), encoding="utf-8")
        self._recorder.executor_calls += 1
        return ActionExecutionReceipt(
            action_id=action_id,
            receipt_ref="receipt-1",
            usage=BudgetUsage(0, 10, 0, 10, 500),
            artifact_ids=("artifact-1",),
            media_types=("application/json",),
        )


def _build_report(
    root: Path,
    crash_point: str | None,
    recorder: OperationRecorder,
) -> Mapping[str, object]:
    native_entries = _native_entries(root / "native")
    host_entries = _host_entries(root / "journal")
    events = _native_events(native_entries)
    host_commands = [
        cast(Mapping[str, object], entry.record.payload["command"])
        for entry in host_entries
        if entry.record.kind == "command.accepted"
    ]
    native_command_ids = [
        str(cast(Mapping[str, object], entry.record.payload["command"])["command_id"])
        for entry in native_entries
        if entry.record.kind == "command.committed"
    ]
    host_command_ids = [str(command["command_id"]) for command in host_commands]
    turn_ids = [
        str(cast(Mapping[str, object], entry.record.payload["request"])["turn_id"])
        for entry in native_entries
        if entry.record.kind == "turn.started"
    ]
    native_action_ids = [
        str(cast(Mapping[str, object], event.payload)["action_id"])
        for event in events
        if event.type == "action.proposed"
    ]
    host_receipt_action_ids = [
        str(entry.record.payload["action_id"])
        for entry in host_entries
        if entry.record.kind == "action.receipted"
    ]
    executor_calls = _read_json_list(root / "executor-calls.json")
    return {
        "crash_point": crash_point,
        "status": "PASS",
        "duplicate_commands": _duplicates(native_command_ids)
        + _duplicates(host_command_ids),
        "duplicate_turns": _duplicates(turn_ids),
        "duplicate_actions": _duplicates(native_action_ids)
        + _duplicates(host_receipt_action_ids)
        + max(0, len(executor_calls) - 1),
        "sequence_gaps": _sequence_gaps(events, host_entries),
        "terminal_count": sum(1 for event in events if event.type in _TERMINAL_EVENTS),
        "owned_processes_after_close": _ProcessRegistry(
            root / "processes.json"
        ).active_count(),
        **recorder.closed_counts(),
    }


def _native_entries(root: Path) -> tuple[NativeEntry, ...]:
    if not root.exists():
        return ()
    owner = NativeSessionDirectory.open(
        root,
        SESSION_ID,
        1_048_576,
        expected_root_identity=_root_identity(root),
    )
    try:
        store = FileNativeSessionStore(owner, max_record_bytes=65_536)
        try:
            return store.replay()
        finally:
            store.close()
    finally:
        owner.close()


def _host_entries(root: Path) -> tuple[JournalEntry, ...]:
    if not root.exists():
        return ()
    journal = FileCanonicalJournal.open(root, SESSION_ID)
    try:
        return journal.replay(JournalCursor(0))
    finally:
        journal.close()


def _host_command_ids(root: Path) -> frozenset[str]:
    return frozenset(
        str(cast(Mapping[str, object], entry.record.payload["command"])["command_id"])
        for entry in _host_entries(root)
        if entry.record.kind == "command.accepted"
    )


def _native_events(entries: tuple[NativeEntry, ...]) -> tuple[ControlEvent, ...]:
    return reduce_native_entries(entries).events


def _sequence_gaps(
    events: tuple[ControlEvent, ...], host_entries: tuple[JournalEntry, ...]
) -> int:
    gaps = _event_sequence_gaps(events)
    host_sequences = [
        int(cast(Mapping[str, object], entry.record.payload["event"])["sequence"])  # type: ignore[attr-defined]
        for entry in host_entries
        if entry.record.kind == "event.accepted"  # type: ignore[attr-defined]
    ]
    if host_sequences:
        gaps += _sequence_gaps_for_numbers(tuple(host_sequences))
    return gaps


def _event_sequence_gaps(events: tuple[ControlEvent, ...]) -> int:
    return _sequence_gaps_for_numbers(tuple(event.sequence for event in events))


def _sequence_gaps_for_numbers(sequences: tuple[int, ...]) -> int:
    if not sequences:
        return 0
    expected = tuple(range(1, max(sequences) + 1))
    return 0 if sequences == expected else 1


def _duplicates(values: list[str]) -> int:
    return sum(count - 1 for count in Counter(values).values() if count > 1)


def _read_json_list(path: Path) -> list[str]:
    if not path.exists():
        return []
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise AssertionError("durable executor call report is invalid")
    return loaded


class _ProcessRegistry:
    def __init__(self, path: Path) -> None:
        self._path = path

    def register(self, process: subprocess.Popen[bytes]) -> None:
        self._write(tuple(sorted((*self._read(), process.pid))))

    def reap(self, process: subprocess.Popen[bytes]) -> None:
        self._write(tuple(pid for pid in self._read() if pid != process.pid))

    def active_count(self) -> int:
        live: list[int] = []
        for pid in self._read():
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            live.append(pid)
        self._write(tuple(live))
        return len(live)

    def _read(self) -> tuple[int, ...]:
        if not self._path.exists():
            return ()
        loaded = json.loads(self._path.read_text(encoding="utf-8"))
        if (
            not isinstance(loaded, list)
            or any(type(item) is not int or item < 1 for item in loaded)
        ):
            raise AssertionError("process registry is invalid")
        return tuple(loaded)

    def _write(self, pids: tuple[int, ...]) -> None:
        self._path.write_text(json.dumps(list(pids), sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
