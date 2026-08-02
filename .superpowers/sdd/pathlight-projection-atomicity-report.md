# Pathlight projection atomicity fix

Status: fixed and verified.

## Root cause

`ObservedRuntimeClient` passed identical injected monotonic-clock values to the
runtime projection. The projection recorded its runtime and context starts, then
rejected a terminal timestamp equal to its start timestamp. The optional
projection exception was suppressed, leaving the recorder with unterminated
spans; a later snapshot/export therefore failed validation.

## Change

- Normalize accepted runtime observation timestamps locally to a strictly
  increasing sequence when an injected clock repeats or moves backwards.
- Stage projection events and publish only after the complete projection has
  been built. A projection failure clears the staged events before they reach
  the recorder.
- Add a repeated-clock regression covering unchanged runtime events, a valid
  recorder snapshot, positive terminal durations, and workflow-evidence bundle
  export.

No Pathlight protocol, identity, or redaction surface changed.

## Verification

```text
uv run python -m unittest -v tests.test_workflow_evidence_runtime \
  tests.test_workflow_evidence_storage tests.test_pathlight_protocol \
  tests.test_runner_composed tests.test_asterion_cli
# 74 tests passed

uv run ruff check src/asterion/workflow_evidence/runtime.py \
  tests/test_workflow_evidence_runtime.py
# passed

git diff --check
# passed
```

## Concern

The existing recorder protocol exposes per-event `record()` rather than a
transactional batch API. Staging prevents partial writes for projection
construction failures (including timestamp validation); a recorder that itself
accepts only a prefix and then raises cannot be rolled back through the current
closed protocol.
