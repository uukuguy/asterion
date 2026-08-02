from __future__ import annotations

import unittest

from asterion.pathlight import PathlightError, TraceEvent, validate_trace_graph
from asterion.pathlight.recorder import MemoryPathlightRecorder, NoopPathlightRecorder


def opaque_id(number: int) -> str:
    return f"00000000-0000-4000-8000-{number:012x}"


TRACE_ID = opaque_id(1)
OTHER_TRACE_ID = opaque_id(2)
ROOT_SPAN_ID = opaque_id(3)
CHILD_SPAN_ID = opaque_id(4)


class PathlightRecorderTests(unittest.TestCase):
    def test_memory_recorder_rejects_an_invalid_trace_identity(self) -> None:
        with self.assertRaises(PathlightError):
            MemoryPathlightRecorder("trace-1")

    def test_memory_recorder_returns_valid_immutable_snapshot(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)
        recorder.record(TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"))
        recorder.record(TraceEvent.complete(TRACE_ID, ROOT_SPAN_ID, 2))

        snapshot = recorder.snapshot()

        validate_trace_graph(snapshot)
        with self.assertRaises(TypeError):
            snapshot["trace_id"] = OTHER_TRACE_ID  # type: ignore[index]
        with self.assertRaises(TypeError):
            snapshot["events"].append({})  # type: ignore[union-attr]
        with self.assertRaises(TypeError):
            snapshot["events"][0]["attributes"]["content_length"] = 1  # type: ignore[index]

    def test_memory_recorder_rejects_an_event_for_another_trace(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)

        with self.assertRaises(PathlightError):
            recorder.record(
                TraceEvent.start(OTHER_TRACE_ID, ROOT_SPAN_ID, None, 1, "task")
            )

    def test_memory_recorder_record_many_validates_the_complete_candidate_before_commit(
        self,
    ) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)

        with self.assertRaises(PathlightError):
            recorder.record_many(
                (
                    TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"),
                    TraceEvent.start(
                        TRACE_ID,
                        CHILD_SPAN_ID,
                        ROOT_SPAN_ID,
                        3,
                        "task",
                    ),
                )
            )

        self.assertEqual(recorder.event_count, 0)

    def test_memory_recorder_fails_closed_for_an_incomplete_graph(self) -> None:
        recorder = MemoryPathlightRecorder(TRACE_ID)
        recorder.record(TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"))

        with self.assertRaises(PathlightError):
            recorder.snapshot()

    def test_noop_recorder_retains_no_events(self) -> None:
        recorder = NoopPathlightRecorder()
        recorder.record(TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"))
        recorder.record_many(
            (TraceEvent.start(TRACE_ID, ROOT_SPAN_ID, None, 1, "task"),)
        )

        self.assertIsNone(recorder.snapshot())


if __name__ == "__main__":
    unittest.main()
