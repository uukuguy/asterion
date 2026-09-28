# Native P7 model selection from the operator environment

> 2026-09-29. Design record for `e392577`. Scope: the native P7 applications
> (`prime.arc-agi-3-solving`, `prime.arc-agi-3-gameplay`) only.

## Problem

`.env` documented `ASTERION_PRIME_PROVIDER` / `ASTERION_PRIME_MODEL` as "change
these two values to switch the model used by P7", but no Python module read
them. The pair was hardcoded in `p7/operator.py`, mirrored in
`prime/runtime_binding.py`, and pinned again in the two trace-identity tables.
The operator control was inert, and an inert control is worse than an absent
one: it silently produces a different model than the operator asked for.

## Decision

`ASTERION_PRIME_PROVIDER` / `ASTERION_PRIME_MODEL` are the only model controls
for P7. They are read once, in `p7/model_selection.py`, from the operator
environment (`.env` merged with the process environment; the process wins).
Absent values default to `openai-codex` / `gpt-6-sol`.

A selection is usable only when all three hold:

1. the provider exists in the Pi profile's `models-store.json` catalog;
2. the model is listed for that provider;
3. the provider has a credential in the profile's `auth.json`, or one of its
   declared operator environment variables (`DEEPSEEK_API_KEY`,
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, …) is set.

Anything else fails closed at preflight with the body-free
`P7 model host is unavailable`; no environment name leaks into the public
error.

## What follows the selection

- **Runtime options** — `p7_runtime_options` publishes the selected pair.
- **Runtime factories** — `prime/runtime_binding.py` no longer carries the pair
  as a constant. `context.options` must agree exactly with the `--provider` /
  `--model` pair declared by the approved launch command, and each flag must
  appear exactly once. Agreement is the invariant; the value itself is
  operator-owned.
- **Trace identity** — `private_trace.py` / `gameplay_trace.py` build
  `model_id` from the selection. Evidence that recorded `gpt-6-sol` while
  another model ran would be false, and `comparison.py`'s
  `model_identity_equal` would call two different models the same run.
- **Public receipt and private experiment** — both report the configured pair.
- **Prefix reuse** — `solutions._known_trace_identities` accepts the exact
  expected model on the runtime path (the operator passes it), and any
  P7-shaped identity when no model is named, so offline tooling can still read
  runs from another selection. The pre-selectable historical identity
  (`deepseek-v4-flash`) stays reusable.
- **Operator tools** — the five `tools/run_prime_p7_*.py` /
  `recover_prime_p7_trace_race.py` identity guards check "is this a P7 trace"
  (stable application fields + a well-formed model) instead of one literal
  model name.

## Deliberate non-goals

- No provider allowlist beyond the Pi catalog plus a credential: the catalog
  and the operator's own credential store are the allowlist. A provider whose
  credential variable is not declared fails closed rather than starting
  unauthenticated.
- No hot swap: the selection is resolved once per operator invocation.
- The `--thinking high` flag stays fixed; per-model reasoning tuning is a
  separate decision.
- P1–P6 keep their own fixed model path. Only the two P7 option tables in
  `prime/runtime_binding.py` changed.

## Validation

- `tests/test_prime_p7_model_selection.py` — defaults, override, environment-key
  credential, identity derivation, malformed/foreign identity rejection, eight
  fail-closed selection cases, prefix-reuse strictness, and the launch
  declaration matrix.
- `tests/test_prime_p7_native_provider.py` — the runtime factory accepts a
  launch that declares the pair and rejects one that does not.
- Full P7 set: 386 tests. Against the pre-change baseline the same set had
  four failures and nine errors; after the change it has four failures and
  seven errors. The two removed errors are the stale DeepSeek-era
  `test_prime_p7_official_operator` expectations. The eleven remaining ones
  are pre-existing and unrelated to the model selection.
