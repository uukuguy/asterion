from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from asterion.control.authority import BudgetUsage
from asterion.control.host import ControlEvent
from asterion.control.journal import (
    FileCanonicalJournal,
    JournalConflictError,
    JournalCursor,
    JournalRecord,
)


def _checkpoint() -> ControlEvent:
    return ControlEvent(
        event_id="event-checkpoint",
        session_id="session-1",
        generation=1,
        sequence=1,
        emitted_at="2026-08-10T00:00:00Z",
        type="checkpoint.created",
        payload={
            "checkpoint_id": "checkpoint-1",
            "capsule_id": "capsule-1",
            "capsule_digest": "a" * 64,
            "control_plane_id": "prime",
            "control_plane_version": "1.0.0",
            "checkpoint_version": "1.0.0",
            "covered_sequence": 1,
            "storage_ref": "storage-1",
        },
    )


def _bind(journal: FileCanonicalJournal) -> None:
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


def _journal_file(root: Path) -> Path:
    matches = tuple(root.glob("*.jsonl"))
    if len(matches) != 1:
        raise AssertionError("expected one journal file")
    return matches[0]


class TestControlFileJournal(unittest.TestCase):
    def test_append_fsyncs_canonical_chain_and_reopens_exact_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "journal"
            journal = FileCanonicalJournal.open(root, "session-1")
            with patch("asterion.control.journal.os.fsync", wraps=os.fsync) as fsync:
                _bind(journal)

            reopened = FileCanonicalJournal.open(root, "session-1")
            entries = reopened.replay(JournalCursor(0))
            lines = _journal_file(root).read_bytes().splitlines()

            self.assertEqual(tuple(entry.position for entry in entries), (1, 2))
            self.assertGreaterEqual(fsync.call_count, 2)
            self.assertEqual(os.stat(root).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(_journal_file(root)).st_mode & 0o777, 0o600)
            for raw in lines:
                value = json.loads(raw)
                self.assertEqual(
                    raw,
                    json.dumps(
                        value,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode(),
                )
            self.assertIs(
                reopened.append(2, entries[-1].record),
                reopened.replay(JournalCursor(1))[0],
            )
            self.assertEqual(reopened.position, 2)

    def test_two_open_writers_fail_closed_on_a_stale_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "journal"
            first = FileCanonicalJournal.open(root, "session-1")
            second = FileCanonicalJournal.open(root, "session-1")
            _bind(first)

            with self.assertRaises(JournalConflictError):
                second.append(
                    0,
                    JournalRecord.fault_projected(
                        fault_id="fault-1",
                        code="provider-disconnected",
                        recoverable=True,
                        evidence_ref=None,
                    ),
                )
            self.assertEqual(second.position, 2)

    def test_open_rejects_truncation_corruption_reordering_and_noncanonical_rows(self) -> None:
        mutations = {
            "truncated-tail": lambda lines: lines[:-1] + [lines[-1][:-1]],
            "middle-corrupt": lambda lines: [lines[0].replace(b"research", b"researcx"), *lines[1:]],
            "forged-digest": lambda lines: [lines[0].replace(b'"record_digest":"', b'"record_digest":"0'), *lines[1:]],
            "reordered": lambda lines: [lines[1], lines[0]],
            "missing-position": lambda lines: [lines[1]],
            "duplicate-position": lambda lines: [lines[0], lines[0]],
            "noncanonical": lambda lines: [b" " + lines[0], *lines[1:]],
            "extra-field": lambda lines: [lines[0][:-1] + b',"secret":"SENTINEL_SECRET"}', *lines[1:]],
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "journal"
                journal = FileCanonicalJournal.open(root, "session-1")
                _bind(journal)
                target = _journal_file(root)
                original = target.read_bytes()
                had_newline = original.endswith(b"\n")
                lines = original.rstrip(b"\n").split(b"\n")
                changed = b"\n".join(mutate(lines)) + (b"\n" if had_newline and name != "truncated-tail" else b"")
                target.write_bytes(changed)
                os.chmod(target, 0o600)

                with self.assertRaises(JournalConflictError) as raised:
                    FileCanonicalJournal.open(root, "session-1")
                self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
                self.assertNotIn(str(root), str(raised.exception))

    def test_open_rejects_symlinks_non_regular_files_modes_and_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            real = parent / "real"
            real.mkdir(mode=0o700)
            linked = parent / "linked"
            linked.symlink_to(real, target_is_directory=True)
            with self.assertRaises(JournalConflictError):
                FileCanonicalJournal.open(linked, "session-1")
            with self.assertRaises(JournalConflictError):
                FileCanonicalJournal.open(parent / ".." / parent.name, "session-1")

            root = parent / "journal"
            FileCanonicalJournal.open(root, "session-1")
            target = _journal_file(root)
            target.unlink()
            target.mkdir(mode=0o700)
            with self.assertRaises(JournalConflictError):
                FileCanonicalJournal.open(root, "session-1")

        for target_kind in ("root-mode", "file-mode", "file-symlink"):
            with self.subTest(target_kind=target_kind), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                root = parent / "journal"
                FileCanonicalJournal.open(root, "session-1")
                target = _journal_file(root)
                if target_kind == "root-mode":
                    os.chmod(root, 0o755)
                elif target_kind == "file-mode":
                    os.chmod(target, 0o644)
                else:
                    target.unlink()
                    victim = parent / "victim"
                    victim.write_text("SENTINEL_SECRET")
                    target.symlink_to(victim)
                try:
                    with self.assertRaises(JournalConflictError) as raised:
                        FileCanonicalJournal.open(root, "session-1")
                    self.assertNotIn(str(root), str(raised.exception))
                    self.assertNotIn("SENTINEL_SECRET", str(raised.exception))
                finally:
                    if root.exists() and not root.is_symlink():
                        os.chmod(root, 0o700)

    def test_receipt_and_checkpoint_constructors_store_only_public_fields(self) -> None:
        receipt = JournalRecord.action_receipted(
            action_id="action-1",
            receipt_ref="receipt-1",
            usage=BudgetUsage(0, 80, 0, 80, 4_000),
        )
        checkpoint = JournalRecord.checkpoint_sealed(checkpoint_event=_checkpoint())

        self.assertEqual(set(receipt.payload), {"action_id", "receipt_ref", "usage"})
        self.assertEqual(set(checkpoint.payload), {"checkpoint_event"})
        self.assertNotIn("SENTINEL_SECRET", repr((receipt, checkpoint)))

        private = JournalRecord(
            record_id="command:private",
            kind="command.accepted",
            payload={
                "command": {
                    "protocol": "asterion.agent-control/v1",
                    "command_id": "private",
                    "session_id": "session-1",
                    "authority_revision": 1,
                    "type": "session.create",
                    "payload": {
                        "system_id": "research.system",
                        "system_version": "1.0.0",
                        "goal_id": "goal-1",
                        "goal_ref": "SENTINEL_SECRET",
                    },
                }
            },
        )
        self.assertNotIn("SENTINEL_SECRET", repr(private))


if __name__ == "__main__":
    unittest.main()
