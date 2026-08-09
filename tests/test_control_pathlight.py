from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from asterion.control.authority import AuthorityLedger, PortfolioGrant
from asterion.control.journal import MemoryCanonicalJournal
from asterion.control.manager import ControlHost
from asterion.control.system import resolve_agent_system
from asterion.control.testing import FakeControlPlaneClient
from asterion.pathlight import MemoryPathlightRecorder, PathlightError
from tests.test_control_authority import _envelope
from tests.test_control_host import SpyExecutor, _create_command
from tests.test_control_system import _control_factories, _manifest, _provider


def _opaque_id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


class FailingRecorder:
    def __init__(self) -> None:
        self.trace_id = _opaque_id(100)
        self.next_sequence = 1
        self.active_span_id = None

    def record(self, event: object) -> None:
        del event
        raise PathlightError("SENTINEL_SECRET recorder body")

    def record_many(self, events: object) -> None:
        del events
        raise PathlightError("SENTINEL_SECRET recorder body")

    def snapshot(self) -> None:
        return None


class FailingSequenceRecorder(FailingRecorder):
    def __init__(self) -> None:
        self.trace_id = _opaque_id(101)
        self.active_span_id = None

    @property
    def next_sequence(self) -> int:
        raise PathlightError("SENTINEL_SECRET recorder sequence body")


class TestControlPathlight(unittest.IsolatedAsyncioTestCase):
    async def test_control_host_projects_complete_safe_causal_chain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(root),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = FakeControlPlaneClient()
            recorder = MemoryPathlightRecorder(_opaque_id(1))
            authority = AuthorityLedger(
                _envelope(
                    allowed_portfolio=(
                        PortfolioGrant(
                            provider_id="example.provider",
                            application_id="zeta",
                            version="2.0.0",
                            runtime_id="fake.runtime",
                        ),
                    )
                )
            )
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=authority,
                journal=MemoryCanonicalJournal("session-1"),
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                pathlight=recorder,
            )
            await host.dispatch(_create_command())
            client.emit_application_proposal()
            client.emit_goal_status("completed")
            client.emit_session_status("completed", reason_code="goal-accepted")

            await host.pump(until_terminal=True)

            snapshot = host.snapshot()
            graph = recorder.snapshot()
            assert graph is not None
            kinds = tuple(event["kind"] for event in graph["events"])
            self.assertEqual(kinds[0:2], ("system", "session"))
            self.assertIn("action", kinds)
            self.assertIn("admission", kinds)
            self.assertIn("goal", kinds)
            self.assertEqual(kinds[-2:], ("session", "system"))
            self.assertEqual(snapshot.state.session_status, "completed")
            self.assertEqual(snapshot.state.actions["action-1"].status, "rejected")
            self.assertEqual(snapshot.evidence_gaps, ())
            rendered = repr(graph)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("goal-ref-1", rendered)
            self.assertNotIn("SENTINEL_SECRET", rendered)

    async def test_recorder_failure_does_not_change_control_result_and_records_gap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = FakeControlPlaneClient()
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=MemoryCanonicalJournal("session-1"),
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                pathlight=FailingRecorder(),
            )
            await host.dispatch(_create_command())
            client.emit_goal_status("completed")
            client.emit_session_status("completed", reason_code="goal-accepted")

            await host.pump(until_terminal=True)

            snapshot = host.snapshot()
            self.assertEqual(snapshot.state.session_status, "completed")
            self.assertEqual(snapshot.evidence_gaps, ("control-pathlight-recording",))
            self.assertNotIn("SENTINEL_SECRET", repr(snapshot))

    async def test_recorder_metadata_failure_is_also_observation_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = resolve_agent_system(
                _manifest(),
                application_providers=(_provider(Path(directory)),),
                control_factories=_control_factories([]),
                host_capabilities=("clock.monotonic", "storage.private"),
            )
            client = FakeControlPlaneClient()
            host = ControlHost(
                session_id="session-1",
                generation=1,
                plan=plan,
                authority=AuthorityLedger(_envelope()),
                journal=MemoryCanonicalJournal("session-1"),
                client=client,
                action_executor=SpyExecutor(),
                clock_ms=lambda: 1_000,
                pathlight=FailingSequenceRecorder(),
            )
            await host.dispatch(_create_command())
            client.emit_goal_status("completed")
            client.emit_session_status("completed", reason_code="goal-accepted")

            await host.pump(until_terminal=True)

            snapshot = host.snapshot()
            self.assertEqual(snapshot.state.session_status, "completed")
            self.assertEqual(snapshot.evidence_gaps, ("control-pathlight-recording",))
            self.assertNotIn("SENTINEL_SECRET", repr(snapshot))


if __name__ == "__main__":
    unittest.main()
