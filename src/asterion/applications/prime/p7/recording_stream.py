"""Incremental legacy SDK JSONL reader; animation bodies enter their own arena.

The SDK wire format is unchanged. A complete line, observation, or recording is
never materialized. Only one row and small non-animation fields are resident.
"""
from __future__ import annotations

import json
from pathlib import Path
from .dynamic_evidence import AnimationFrames, EvidenceProcessingError


class _Reader:
    def __init__(self, source, include_frames=True):
        self.source, self.buffer, self.position, self.eof = source, '', 0, False
        self.include_frames = include_frames
        self.metadata_bytes = 0
        self.in_record = False

    def peek(self):
        if self.position == len(self.buffer) and not self.eof:
            self.buffer = self.source.read(64 * 1024)
            self.position = 0
            self.eof = not self.buffer
        return '' if self.eof else self.buffer[self.position]

    def take(self):
        value = self.peek()
        if not value:
            raise ValueError('recording unavailable')
        self.position += 1
        return value

    def whitespace(self):
        while self.peek() and self.peek() in ' \t\r\n':
            if self.in_record and self.peek() in '\r\n':
                raise ValueError('recording row incomplete')
            self.take()

    def expect(self, expected):
        self.whitespace()
        if self.take() != expected:
            raise ValueError('recording unavailable')

    def value(self, path=(), *, animation=False):
        self.whitespace()
        if len(path) > 32:
            raise ValueError('recording unavailable')
        char = self.peek()
        if path in {('data', 'frame'), ('payload', 'observation', 'frame')}:
            if self.include_frames:
                return AnimationFrames.capture(self.frames())
            for frame in self.frames():
                for row in frame:
                    for _cell in row:
                        pass
            return None
        if char == '{':
            self.take()
            result = {}
            self.whitespace()
            if self.peek() != '}':
                while True:
                    key = self.value((*path, '<key>'), animation=animation)
                    if type(key) is not str or key in result:
                        raise ValueError('recording unavailable')
                    self.expect(':')
                    result[key] = self.value((*path, key), animation=animation)
                    self.whitespace()
                    if self.peek() != ',':
                        break
                    self.take()
            self.expect('}')
            return result
        if char == '[':
            self.take()
            result = []
            self.whitespace()
            if self.peek() != ']':
                while True:
                    result.append(self.value((*path, '[]'), animation=animation))
                    self.whitespace()
                    if self.peek() != ',':
                        break
                    self.take()
            self.expect(']')
            return result
        token, escaped = [], False
        if char == '"':
            token.append(self.take())
            while True:
                char = self.take()
                token.append(char)
                if len(token) > 64 * 1024:
                    raise ValueError('recording field unavailable')
                if char == '"' and not escaped:
                    break
                escaped = char == '\\' and not escaped
        else:
            while self.peek() and self.peek() not in ' \t\r\n,]}':
                token.append(self.take())
                if len(token) > 1024:
                    raise ValueError('recording field unavailable')
        if not animation:
            self.metadata_bytes += len(token)
            if self.metadata_bytes > 1024 * 1024:
                raise ValueError('recording metadata unavailable')
        return json.loads(''.join(token))

    def frames(self):
        self.expect('[')
        self.whitespace()
        if self.peek() != ']':
            while True:
                yield self.rows()
                self.whitespace()
                if self.peek() != ',':
                    break
                self.take()
        self.expect(']')

    def rows(self):
        self.expect('[')
        self.whitespace()
        if self.peek() != ']':
            while True:
                yield self.cells()
                self.whitespace()
                if self.peek() != ',':
                    break
                self.take()
        self.expect(']')


    def cells(self):
        self.expect('[')
        pending = ''
        needs_cell = False
        while True:
            if not self.peek():
                raise ValueError('recording row incomplete')
            segment = self.buffer[self.position:]
            end = segment.find(']')
            boundary = end if end >= 0 else segment.rfind(',')
            if boundary >= 0:
                token = pending + segment[:boundary]
                if '\n' in token or '\r' in token:
                    raise ValueError('recording row incomplete')
                if end >= 0 and needs_cell and not token.strip():
                    raise ValueError('recording cell unavailable')
                values = json.loads('[' + token + ']')
                for value in values:
                    if type(value) is not int or not 0 <= value <= 255:
                        raise ValueError('recording cell unavailable')
                    yield value
                if end >= 0:
                    self.position += boundary + 1
                    return
                pending = segment[boundary + 1:]
                needs_cell = True
            else:
                pending += segment
            # A uint8 token is tiny. Whitespace is streamed without becoming
            # an aggregate animation limit or an unbounded pending token.
            if len(pending) > 1024:
                pending = ' ' + pending.strip() + ' '
                if len(pending) > 1024:
                    raise ValueError('recording cell unavailable')
            self.position = len(self.buffer)


def recording_rows(path: Path, *, include_frames=True, recover_invalid=False):
    """Yield old wire records with a readonly handle in data.frame."""
    try:
        with path.open(encoding='utf-8') as source:
            reader = _Reader(source, include_frames)
            while True:
                reader.whitespace()
                if not reader.peek():
                    break
                reader.metadata_bytes = 0
                reader.in_record = True
                try:
                    value = reader.value()
                    if type(value) is not dict:
                        raise ValueError('recording unavailable')
                    yield value
                except (ValueError, EvidenceProcessingError):
                    if not recover_invalid:
                        raise
                    # JSONL line boundaries remain authoritative; do not let
                    # a truncated object consume the next valid observation.
                    while reader.peek() and reader.peek() not in '\r\n':
                        reader.take()
                    yield None
                finally:
                    reader.in_record = False
    except OSError:
        raise EvidenceProcessingError('evidence-read-failed', stage='derived-failed', durable=True) from None
