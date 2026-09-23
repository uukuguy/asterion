# Journal File Codec Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Move canonical JSONL row encoding and shape validation out of `control/journal.py` while preserving the public journal and its exact bytes.

**Architecture:** New internal `control/_journal_file_codec.py` owns canonical JSON value conversion, row encoding, and row-shape decoding. `journal.py` continues to own the sole file journal, descriptor access, prefix chain, record validation, replay, and fsync. It re-exports the existing `JOURNAL_FILE_VERSION` and keeps its current public imports; the file codec never imports `journal.py`.

**Tech Stack:** Python, `unittest`, canonical JSONL.

## Global Constraints

- Preserve exact `asterion.control-journal/v1` bytes, record digests, public errors, and journal imports.
- Keep file access, chain validation, and authority in `FileCanonicalJournal`; no reducer or alternate storage path.
- Do not edit `session_context_manager.py`, other agents' files, or docs/status; do not commit.

---

### Task 1: Capture the codec contract with RED test

**Files:** `tests/test_control_file_journal.py`.

- [x] Add a test that obtains a real `JournalEntry`, asserts the new internal codec module exists, encodes exactly the on-disk row bytes, decodes its canonical shape, and rejects a noncanonical row. Assert `JournalRecord` remains importable from `asterion.control.journal`.
- [x] Run `uv run python -m unittest -v tests.test_control_file_journal.TestControlFileJournal.test_internal_codec_preserves_canonical_row_bytes`; expect failure because the internal module does not exist.

### Task 2: Extract the stable row codec

**Files:** `src/asterion/control/_journal_file_codec.py`, `src/asterion/control/journal.py`.

**Interfaces:** Internal `encode_row(position, previous_digest, record_digest, record_id, kind, payload) -> bytes` and `decode_row(raw_line, expected_position, previous_digest) -> dict[str, object]`; public `JOURNAL_FILE_VERSION` stays in `journal.py` as an imported alias.

- [x] Move `_json_value` to the codec as `json_value`; import it privately in `journal.py` for existing record digest and operation digest uses.
- [x] Implement `encode_row` with the current sorted, compact, UTF-8 JSON plus one newline. Implement `decode_row` to require exact fields, canonical bytes, version, position, previous digest, and record shape. Raise a private value error without raw payload text.
- [x] Keep `_encode_file_row` as a journal-local adapter to `encode_row`; change `_read_file_entries` to call `decode_row` before its existing digest, duplicate ID, prefix, and session checks. Preserve existing error projection.
- [x] Run the new test and `uv run python -m unittest -q tests.test_control_file_journal tests.test_control_journal`; expect PASS.

### Task 3: Compatibility review

**Files:** No further production files.

- [x] Run focused session-context, harness, and long-running suites, targeted Ruff, and `git diff --check`.
- [x] Confirm byte equality, corruption rejection, redaction, and unchanged public imports. Report exact commands and compatibility risk to root; do not commit.

## Verification evidence

- RED: `test_internal_codec_preserves_canonical_row_bytes` failed because `asterion.control._journal_file_codec` did not exist.
- GREEN: `uv run python -m unittest -q tests.test_control_file_journal tests.test_control_journal tests.test_session_context_manager tests.test_control_harness tests.test_control_long_running` passed 76 tests. Targeted Ruff and `git diff --check` passed.
- The new codec has no `journal.py` import. `journal.py` still owns descriptor I/O, hash-chain and session validation, fsync, and the sole `FileCanonicalJournal`.
