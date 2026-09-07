"""Closed text-only presentation channel for injected host services."""

from __future__ import annotations

from typing import Protocol, TextIO


_MAX_RECORD_LENGTH = 1024


class HostPresentationSink(Protocol):
    """Render one bounded public-safe text record."""

    def write(self, text: str) -> None: ...


class _NoopHostPresentationSink:
    def write(self, text: str) -> None:
        del text

    def __repr__(self) -> str:
        return "NOOP_HOST_PRESENTATION_SINK"


NOOP_HOST_PRESENTATION_SINK: HostPresentationSink = _NoopHostPresentationSink()


class TextHostPresentationSink:
    """Write bounded printable presentation records to one supplied stream."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> None:
        if (
            type(text) is not str
            or not text
            or len(text) > _MAX_RECORD_LENGTH
            or any(not (" " <= character <= "~") for character in text)
        ):
            raise ValueError("host presentation record is invalid")
        self._stream.write(text + "\n")
        self._stream.flush()

    def __repr__(self) -> str:
        return "TextHostPresentationSink(<redacted>)"
