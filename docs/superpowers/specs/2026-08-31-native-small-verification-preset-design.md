# Native Small Verification Preset Design

## Goal

Let an operator request one small Native Verified-loop validation without
supplying provider, model, cost, or deadline details, while retaining a finite,
fail-closed execution boundary.

## User contract

The public action is `run small verification`. It has no provider or budget
parameters. Its public result is one of `PASS`, `INCOMPLETE`, or
`External-limited`; it never exposes private configuration, prompts, answers,
credentials, or raw provider output.

## Architecture

An operator-owned preset resolver supplies the exact host, provider/model
identity, one-turn reservation, cost ceiling, and short deadline. The Native
framework receives only the resolved immutable reservation and injected host.
It does not read environment variables, choose a provider, or create a default
host.

Each preset reservation is single-use. Missing preset configuration, a missing
host, duplicate execution, an expired/invalid reservation, an identity
mismatch, an over-budget result, or an incomplete/redaction-unsafe receipt
returns `External-limited` or `INCOMPLETE` without promotion or retry.

## Execution and evidence

The preset runs at most one bounded turn. The host creates a body-free receipt
for `rlm.generated-program` and `operation.autonomous-quality`; the existing
reducer accepts only a complete exact receipt. Provider-free checks remain
provider-free, and Native `Verified-loop` remains Missing unless both evidence
partitions pass on the same candidate.

## Tests

Tests prove that the public preset carries no user-supplied provider/budget
fields, missing preset configuration never invokes a host, one reservation is
consumed exactly once, invalid/over-budget results are rejected, and public
errors and receipts remain redacted.
