from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from asterion.control.host import ControlCommand, ControlEvent
from asterion.control.journal import (
    FileCanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalRecord,
    MemoryCanonicalJournal,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "agent_control" / "v1"


def _fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text())
    assert isinstance(value, dict)
    return value


def _journal() -> MemoryCanonicalJournal:
    journal = MemoryCanonicalJournal("session-1")
    system = journal.append(
        0,
        JournalRecord.system_bound(
            system_id="research.system",
            system_version="1.0.0",
        ),
    )
    journal.append(
        system.position,
        JournalRecord.authority_bound(
            authority_id="authority-1",
            authority_revision=1,
        ),
    )
    return journal


class TestControlJournal(unittest.TestCase):
    def test_compare_append_and_replay_are_contiguous_and_immutable(self) -> None:
        journal = _journal()
        command = ControlCommand.from_mapping(
            _fixture("valid-command-session-create.json")
        )

        accepted = journal.accept_command(command, expected_position=2)
        replay = journal.replay(JournalCursor(0))

        self.assertEqual(accepted.position, 3)
        self.assertEqual(tuple(entry.position for entry in replay), (1, 2, 3))
        self.assertEqual(replay[-1].record.kind, "command.accepted")
        with self.assertRaises(AttributeError):
            replay[-1].position = 9  # type: ignore[misc]
        with self.assertRaises(TypeError):
            replay[-1].record.payload["command"] = {}  # type: ignore[index]

    def test_stale_compare_position_and_cursor_beyond_tail_fail_closed(self) -> None:
        journal = _journal()
        with self.assertRaises(JournalConflictError):
            journal.append(
                0,
                JournalRecord.fault_projected(
                    fault_id="fault-1",
                    code="provider-disconnected",
                    recoverable=True,
                    evidence_ref=None,
                ),
            )
        with self.assertRaises(JournalConflictError):
            journal.replay(JournalCursor(3))

    def test_identical_command_replay_returns_original_entry(self) -> None:
        journal = _journal()
        command = ControlCommand.from_mapping(
            _fixture("valid-command-session-create.json")
        )

        first = journal.accept_command(command, expected_position=2)
        repeated = journal.accept_command(command, expected_position=3)

        self.assertIs(repeated, first)
        self.assertEqual(journal.position, 3)

    def test_divergent_command_and_event_id_replay_fail_closed(self) -> None:
        journal = _journal()
        command_source = _fixture("valid-command-session-create.json")
        command = ControlCommand.from_mapping(command_source)
        journal.accept_command(command, expected_position=2)
        payload = command_source["payload"]
        assert isinstance(payload, dict)
        divergent_command = ControlCommand.from_mapping(
            {**command_source, "payload": {**payload, "goal_ref": "goal-ref-2"}}
        )
        with self.assertRaises(JournalConflictError):
            journal.accept_command(divergent_command, expected_position=3)

        event_source = _fixture("valid-event-action-proposed.json")
        event = ControlEvent.from_mapping(event_source)
        journal.accept_event(event, expected_position=3)
        divergent_event = ControlEvent.from_mapping(
            {**event_source, "emitted_at": "2026-08-09T15:00:01Z"}
        )
        with self.assertRaises(JournalConflictError):
            journal.accept_event(divergent_event, expected_position=4)

    def test_requires_system_authority_prefix_before_session_records(self) -> None:
        journal = MemoryCanonicalJournal("session-1")
        command = ControlCommand.from_mapping(
            _fixture("valid-command-session-create.json")
        )
        with self.assertRaises(JournalConflictError):
            journal.accept_command(command, expected_position=0)
        system = journal.append(
            0,
            JournalRecord.system_bound(
                system_id="research.system",
                system_version="1.0.0",
            ),
        )
        with self.assertRaises(JournalConflictError):
            journal.accept_command(command, expected_position=system.position)

    def test_rejects_private_or_unknown_record_payload_without_leaking_body(self) -> None:
        with self.assertRaises(JournalConflictError) as raised:
            JournalRecord(
                record_id="fault:fault-1",
                kind="fault.projected",
                payload={
                    "fault_id": "fault-1",
                    "code": "provider-disconnected",
                    "recoverable": True,
                    "evidence_ref": None,
                    "provider_payload": "SENTINEL_SECRET",
                },
            )
        self.assertNotIn("SENTINEL_SECRET", str(raised.exception))

    def test_event_replay_is_idempotent_and_session_identity_is_exact(self) -> None:
        journal = _journal()
        event = ControlEvent.from_mapping(_fixture("valid-event-action-proposed.json"))
        first = journal.accept_event(event, expected_position=2)
        self.assertIs(journal.accept_event(event, expected_position=3), first)

        other = ControlEvent.from_mapping(
            {
                **event.to_mapping(),
                "event_id": "event-other",
                "session_id": "session-2",
            }
        )
        with self.assertRaises(JournalConflictError):
            journal.accept_event(other, expected_position=3)

    def test_file_journal_open_at_stays_on_pinned_root_after_ancestor_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            children = root / "children"
            child = children / "child-1"
            child.mkdir(parents=True, mode=0o700)
            child.chmod(0o700)
            child_fd = os.open(
                child,
                os.O_RDONLY
                | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                journal = FileCanonicalJournal.open_at(child_fd, child, "session-1")
                first = journal.append(
                    0,
                    JournalRecord.system_bound(
                        system_id="research.system",
                        system_version="1.0.0",
                    ),
                )
                journal.append(
                    first.position,
                    JournalRecord.authority_bound(
                        authority_id="authority-1",
                        authority_revision=1,
                    ),
                )

                children.rename(root / "children-original")
                replacement_child = root / "children" / "child-1"
                replacement_child.mkdir(parents=True, mode=0o700)
                replacement_child.chmod(0o700)
                journal.append(
                    2,
                    JournalRecord.fault_projected(
                        fault_id="fault-1",
                        code="provider-disconnected",
                        recoverable=True,
                        evidence_ref=None,
                    ),
                )

                self.assertEqual(list(replacement_child.iterdir()), [])
                self.assertEqual(
                    len(list((root / "children-original" / "child-1").glob("journal-*.jsonl"))),
                    1,
                )
                journal.close()
                with self.assertRaises(JournalConflictError):
                    _ = journal.position
            finally:
                os.close(child_fd)


if __name__ == "__main__":
    unittest.main()
