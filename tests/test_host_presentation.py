from __future__ import annotations

import io
import unittest

from asterion.services.presentation import (
    NOOP_HOST_PRESENTATION_SINK,
    TextHostPresentationSink,
)


class TextHostPresentationSinkTests(unittest.TestCase):
    def test_write_flushes_a_bounded_printable_record(self) -> None:
        class Stream(io.StringIO):
            def __init__(self) -> None:
                super().__init__()
                self.flush_count = 0

            def flush(self) -> None:
                self.flush_count += 1
                super().flush()

        stream = Stream()

        TextHostPresentationSink(stream).write("Public status: ready")

        self.assertEqual(stream.getvalue(), "Public status: ready\n")
        self.assertEqual(stream.flush_count, 1)

    def test_write_rejects_non_printable_or_oversized_records(self) -> None:
        sink = TextHostPresentationSink(io.StringIO())

        for value in ("contains\nnewline", "contains\tindent", "x" * 1025):
            with self.subTest(value_length=len(value)):
                with self.assertRaises(ValueError):
                    sink.write(value)

    def test_representations_do_not_reveal_stream_or_written_text(self) -> None:
        class SecretStream(io.StringIO):
            def __repr__(self) -> str:
                return "<SECRET-PRESENTATION-STREAM>"

        stream = SecretStream()
        sink = TextHostPresentationSink(stream)
        sink.write("Public status: ready")

        self.assertNotIn("SECRET-PRESENTATION-STREAM", repr(sink))
        self.assertNotIn("Public status: ready", repr(sink))
        self.assertNotIn("Public status: ready", repr(NOOP_HOST_PRESENTATION_SINK))


if __name__ == "__main__":
    unittest.main()
