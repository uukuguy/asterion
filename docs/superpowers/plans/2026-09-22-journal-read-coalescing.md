# Journal Read Coalescing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Remove duplicate full journal parses within common logical operations while retaining full prefix validation on every independent file read.

**Architecture:** Add a private `_append_current(record)` operation that locks, parses, validates, and appends at the current position in one pass. Keep `append(expected_position, record)` as compare-and-append. File-journal convenience methods use `_append_current` only when their optional expected position is omitted. Session context recovery and refresh derive position from a single validated `replay` result.

**Tech Stack:** Python, `unittest`, descriptor-relative JSONL journal.

## Global Constraints

- Every file operation continues to read and validate the entire hash chain and compare the installed prefix; mtime/size never substitutes for content validation.
- Explicit expected positions retain compare-and-swap behavior; stale writers fail.
- Preserve replay, idempotency, fsync, and redacted error behavior.
- Do not commit; root agent integrates the shared worktree.

---

### Task 1: Atomic current-position append

**Files:** `src/asterion/control/journal.py`, `tests/test_control_file_journal.py`.

**Interfaces:** File journal private `_append_current(record: JournalRecord) -> JournalEntry`; public `CanonicalJournal.append(expected_position: int, record: JournalRecord)` remains unchanged.

- [x] Add a failing test that patches `_read_file_entries` around `FileCanonicalJournal.accept_event(_checkpoint())` after `_bind`; assert exactly one full parse. Add a tampered-prefix and truncated-file matrix asserting `accept_event` rejects before append. Existing explicit stale-position tests remain the CAS regression gate.
- [x] Run `uv run python -m unittest -v tests.test_control_file_journal.TestControlFileJournal.test_default_accept_uses_one_validated_read`; expect parse count 2 instead of 1.
- [x] Extract append's existing locked read/validate/write body into a private shared method. Route public explicit `append` through it with the supplied expected position; route `_append_current` through it with an internal sentinel for current position. Update the file journal's six optional-position convenience methods to choose `_append_current` only when `expected_position is None`. Keep the public protocol and memory journal unchanged.
- [x] Run `uv run python -m unittest -q tests.test_control_file_journal tests.test_control_journal`; expect PASS.

### Task 2: Single-read session context refresh

**Files:** `src/asterion/control/session_context_manager.py`, `tests/test_session_context_manager.py`.

**Interfaces:** No public API change. Derive current position from `replay(JournalCursor(old_position))` once; an empty suffix means unchanged position.

- [x] Add a failing file-journal test that appends a non-context record through another handle, patches `_read_file_entries`, invokes `_refresh_position`, and asserts one parse and the updated snapshot position. Existing tamper/recovery tests remain the fail-closed gate.
- [x] Run `uv run python -m unittest -v tests.test_session_context_manager.TestSessionContextManager.test_refresh_position_uses_one_validated_replay`; expect parse count 2 instead of 1.
- [x] Replace the position-then-replay pair in `_refresh_position` with one replay. Replace constructor's position-then-replay pair with one replay of cursor zero and `len(entries)`; require at least two records.
- [x] Run `uv run python -m unittest -q tests.test_session_context_manager`; expect PASS.

### Task 3: Focused review and measurement

**Files:** No further production files.

- [x] Run focused journal, session context, harness, and long-running tests plus targeted Ruff and `git diff --check`.
- [x] Record full parse counts for a default accept and session refresh before and after; report that independent appends still parse the full prefix, so repeated independent append work remains quadratic.
- [x] Inspect the diff for protocol compatibility, explicit CAS behavior, tamper/truncation checks, and touched-file ownership. Report to root without committing.

## Verification evidence

- RED: default accept called `_read_file_entries` twice; session context construction and refresh each called it twice. Both tests expected one call and failed with `2 != 1`.
- GREEN: `uv run python -m unittest -q tests.test_control_file_journal tests.test_control_journal tests.test_session_context_manager tests.test_control_harness tests.test_control_long_running` passed 75 tests. Targeted Ruff and `git diff --check` passed.
- Measured after change: 64 default event accepts made 64 full reads and parsed 2,144 rows. The prior two-read sequence would parse 4,288 rows for the same prefix lengths. Independent appends still reparse the complete prefix.
