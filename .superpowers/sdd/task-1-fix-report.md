# H-035 Task 1 Fix Report — Agent Client Validation Gaps

## Scope

Closed every finding in the independent review without changing provider,
model, upload, agent-control, or agent-runtime authority. The pre-existing
`docs/status/JOURNAL.md` entry remains deliberately uncommitted.

## Root cause and changes

1. **Calendar timestamps:** The event schema had only a lexical UTC pattern;
   TypeScript therefore accepted JavaScript-normalized dates such as
   `2026-02-30T15:00:00Z`. The schema now declares `format: date-time` and
   TypeScript registers one strict calendar-aware format validator used by AJV
   and the public semantic validator. It compares every parsed UTC component,
   rejects year zero (matching Python `datetime`), and preserves the closed UTC
   syntax. Python already used `datetime.fromisoformat` after its syntax check.

2. **Numeric bounds:** Every agent-client integer in both JSON schemas now has
   `maximum: 9007199254740991`. Python centralizes the same limit in
   `_MAX_SAFE_INTEGER`, shared by both positive and non-negative checks,
   including `ClientCursor`. TypeScript receives the boundary through the
   compiled schemas.

3. **Tool lifecycle:** Stream validators now retain `seen_calls` in addition
   to active calls. A call ID is consumed by its first `tool.started` and can
   never be started again after completion.

4. **Public dataclass construction:** Intent and event field validation now
   normalizes `payload` through `_mapping` before traversing it. Non-mapping
   direct-constructor payloads now raise the fixed/redacted
   `ClientProtocolError("client payload is invalid")`, not `AttributeError`.

5. **Static types:** Mapping-to-dataclass reconstruction now uses typed
   `_integer` extraction, and public validators re-enter their typed mapping
   constructors rather than expanding `Mapping[str, object]` into dataclass
   keyword arguments. This removes all 18 reported Pyright errors without
   widening accepted inputs.

## Test-first evidence

### RED

Added the Python and TypeScript regressions before production changes, then
ran:

```text
uv run python -m unittest -v tests.test_agent_client_protocol
npm --prefix packages/typescript/asterion-runtime test
```

The Python RED run showed 12 unsafe-integer failures, accepted
start/complete/start/complete reuse, and direct construction escaping as raw
`AttributeError`. Python already rejected the impossible February date, which
isolated the cross-language discrepancy to the schema/TypeScript path.

The TypeScript RED run failed with `Missing expected exception
(ProtocolValidationError)` for `2026-02-30T15:00:00Z`. After adding strict
calendar testing, the follow-up RED run also failed for `0000-01-01T00:00:00Z`;
the minimal alignment change rejects it.

The pre-fix static audit was:

```text
uv run pyright src/asterion/client/protocol.py tests/test_agent_client_protocol.py
# 18 errors, 0 warnings, 0 informations
```

### GREEN / verification

```text
uv run python -m unittest -v tests.test_agent_client_protocol tests.test_distribution
# Ran 10 tests — OK

npm --prefix packages/typescript/asterion-runtime test
# 23 tests, 23 pass, 0 fail

uv run pyright src/asterion/client/protocol.py tests/test_agent_client_protocol.py
# 0 errors, 0 warnings, 0 informations

make lint
# compileall and ruff check passed

git diff --check
# exit 0
```

Additionally, a targeted schema audit found no agent-client `type: integer`
without an explicit maximum:

```text
rg -n -P '"type"\s*:\s*"integer"(?![^\n]*"maximum")' schemas/agent-client/v1/*.json
# no output
```

## Self-review

- Schema, Python, and TypeScript reject impossible dates and unsafe numbers;
  the TypeScript test validates the copied canonical schemas through AJV.
- All numeric Python validation paths share the safe-integer guard; all schema
  integer declarations carry the identical limit.
- Reused call IDs are rejected while normal start/complete pairing, terminal
  sequencing, recursive immutability, and redaction continue to pass.
- The changes only touch Task 1 protocol schemas, validators, and regression
  tests. No external authority or executable configuration was introduced.
