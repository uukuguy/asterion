from __future__ import annotations

import io
import unittest
from dataclasses import FrozenInstanceError

from asterion.services.progress import (
    HOST_PROGRESS_COMPONENTS,
    HOST_PROGRESS_STATES,
    ContainedHostProgressReporter,
    HostProgressEvent,
    TextHostProgressReporter,
)


class _HostileStream:
    def __init__(self) -> None:
        self.writes = 0

    def write(self, value: str) -> int:
        del value
        self.writes += 1
        raise RuntimeError("SECRET-PROGRESS-STREAM-FAILURE")


class HostProgressEventTests(unittest.TestCase):
    def test_accepts_closed_values_and_bounded_counters(self) -> None:
        for component in HOST_PROGRESS_COMPONENTS:
            for state in HOST_PROGRESS_STATES:
                with self.subTest(component=component, state=state):
                    self.assertEqual(
                        HostProgressEvent(component, state, 1, 64),
                        HostProgressEvent(component, state, 1, 64),
                    )

    def test_rejects_values_outside_the_closed_contract(self) -> None:
        class StringSubclass(str):
            pass

        cases = (
            (StringSubclass("worker"), "started", None, None),
            ("worker", StringSubclass("started"), None, None),
            ("unknown", "started", None, None),
            ("worker", "unknown", None, None),
            ("worker", "started", 1, None),
            ("worker", "started", None, 1),
            ("worker", "started", 0, 1),
            ("worker", "started", 1, 65),
            ("worker", "started", 2, 1),
            ("worker", "started", True, 1),
        )
        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    HostProgressEvent(*values)

    def test_event_is_frozen(self) -> None:
        event = HostProgressEvent("worker", "started")
        with self.assertRaises(FrozenInstanceError):
            event.component = "tool"


class TextHostProgressReporterTests(unittest.TestCase):
    def test_renders_only_framework_owned_labels(self) -> None:
        stream = io.StringIO()
        reporter = TextHostProgressReporter(stream)

        reporter.emit(HostProgressEvent("model", "started", 1, 2))

        self.assertEqual(stream.getvalue(), "[host] model 1/2: started\n")

    def test_hostile_stream_failure_is_contained(self) -> None:
        stream = _HostileStream()
        reporter = TextHostProgressReporter(stream)

        reporter.emit(HostProgressEvent("worker", "started"))
        reporter.emit(HostProgressEvent("cleanup", "succeeded"))

        self.assertEqual(stream.writes, 1)


class ContainedHostProgressReporterTests(unittest.TestCase):
    def test_hostile_reporter_failure_disables_all_further_events(self) -> None:
        class HostileReporter:
            def __init__(self) -> None:
                self.events: list[HostProgressEvent] = []

            def emit(self, event: HostProgressEvent) -> None:
                self.events.append(event)
                raise RuntimeError("SECRET-HOST-PROGRESS-FAILURE")

        hostile = HostileReporter()
        reporter = ContainedHostProgressReporter(hostile)

        reporter.emit(HostProgressEvent("worker", "started"))
        reporter.emit(HostProgressEvent("cleanup", "succeeded"))

        self.assertEqual(hostile.events, [HostProgressEvent("worker", "started")])

    def test_rejects_non_cleanup_work_after_a_failed_event(self) -> None:
        stream = io.StringIO()
        reporter = ContainedHostProgressReporter(TextHostProgressReporter(stream))

        reporter.emit(HostProgressEvent("worker", "failed"))
        reporter.emit(HostProgressEvent("model", "started"))
        reporter.emit(HostProgressEvent("cleanup", "succeeded"))

        self.assertEqual(
            stream.getvalue(),
            "[host] worker: failed\n[host] cleanup: succeeded\n",
        )
