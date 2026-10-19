"""Accepted research-note epoch over immutable documents.

Applications commit the epoch. This module stores text and opaque evidence
references. It does not interpret domain observations, grant execution
authority, or treat a saved but uncommitted document as history.
"""
from __future__ import annotations

from .memory import ResearchMemoryStore, _MAX_HISTORY


class ResearchNotes:
    """Readable history is the committed revision and its ancestors.

    ``save`` writes a child of the current epoch and leaves the epoch in place.
    The application persists the returned revision before constructing the next
    epoch. An exact archive read of an uncommitted document stays on
    ``ResearchMemoryStore`` and is not a second epoch.
    """

    def __init__(self, store: ResearchMemoryStore, *, accepted_revision: str | None = None):
        if type(store) is not ResearchMemoryStore:
            raise ValueError('research notes store invalid')
        if accepted_revision is not None and type(accepted_revision) is not str:
            raise ValueError('research notes revision invalid')
        self._store = store
        self._accepted = accepted_revision

    def __repr__(self) -> str:
        return '<ResearchNotes redacted>'

    @property
    def accepted_revision(self) -> str | None:
        return self._accepted

    def save(self, text, *, evidence_refs=()):
        """Write an immutable child. The accepted revision does not move."""
        return self._store.save(
            text, parent_revision=self._accepted, evidence_refs=evidence_refs)

    def read(self, revision=None):
        """Return the epoch head, or one ancestor. Orphans are unavailable."""
        current = self._accepted
        if revision is None:
            if current is None:
                return None
            return self._store.read(current)
        seen = set()
        while current is not None:
            if current in seen or len(seen) >= _MAX_HISTORY:
                raise ValueError('research notes ancestry invalid')
            seen.add(current)
            record = self._store.read(current)
            if current == revision:
                return record
            current = record['parent_revision']
        raise ValueError('research notes unavailable')

    def history(self, *, start=0, limit=16):
        """Page from the committed revision. An empty epoch has no rows."""
        return self._store.history(self._accepted, start=start, limit=limit)
