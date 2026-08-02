# Pathlight recorder atomic publication

## Scope

Updated only the public Pathlight recorder API, runtime-evidence publication,
and focused Pathlight/runtime tests. The composed runner retains its existing
single-event lifecycle writes because those legitimate writes form an open
trace prefix until the run finishes.

## Change

- Added `PathlightRecorder.record_many(events)` as the all-or-nothing public
  publication operation, with no-op and in-memory implementations.
- `MemoryPathlightRecorder.record_many()` copies all supplied events, validates
  the complete candidate prefix, and extends its stored events only after that
  validation succeeds. Validation temporarily closes open spans only in a
  throwaway graph, so a runtime projection can still be appended under an open
  composed-run lifecycle without committing synthetic events.
- `_RuntimePathlightProjection` now sends its fully buffered projection through
  one `record_many()` call. Its existing exception boundary still discards
  optional observation failures while preserving the yielded runtime stream and
  workflow evidence record.

## Regression coverage

- A malformed batch with a sequence gap is rejected with memory state unchanged.
- A custom recorder that rejects after inspecting a batch prefix receives one
  batch call, retains no prefix, exposes no trace, and does not change runtime
  completion or workflow-evidence recording.
- The existing open composed-lifecycle projection coverage remains green.

## Verification

```text
uv run python -m unittest -v tests.test_pathlight_recorder \
  tests.test_workflow_evidence_runtime tests.test_runner_composed
# 23 tests passed

uv run ruff check src/asterion/pathlight/recorder.py \
  src/asterion/workflow_evidence/runtime.py tests/test_pathlight_recorder.py \
  tests/test_workflow_evidence_runtime.py tests/test_runner_composed.py
# All checks passed
```

## Compatibility and concerns

No runtime protocol, DCI module, manifest, or persisted Pathlight schema was
changed. `record_many()` is an additive public recorder protocol requirement:
external custom recorders should implement it atomically before being used for
runtime evidence publication. No redaction behavior changed.
