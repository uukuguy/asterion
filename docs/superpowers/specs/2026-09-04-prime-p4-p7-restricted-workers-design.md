# Prime P4–P7 Restricted Workers Design

## Decision

Complete the executable boundary for the four Prime acceptance products that
currently have sealed traces and live evidence reducers but no scenario-owned
restricted-worker lifecycle: P4 long-session continuity, P5 bounded autonomy,
P6 continual improvement, and P7 ARC-AGI-3.

The implementation adds one shared *lifecycle envelope* and four sealed,
scenario-specific adapters.  It does not add a generic task runner, command
surface, manifest command, provider configuration, prompt, or credential path.
P1–P3 remain unchanged.

## Why this shape

Two existing patterns establish the boundary:

- P2 owns a narrow Docker-worker facade, canonical completion parser, and
  restricted-worker receipts.
- P3 adds engine-inspected sandbox facts and a one-use broker alongside the
  same lifecycle proof.

Copying either implementation four times would duplicate cancellation,
cleanup, lease identity, and attestation logic.  Conversely, one generic
worker would let a scenario select its entrypoint, environment, or workload,
which violates the closed workload and host-authority rules.  The shared
envelope therefore owns only mechanics; each adapter owns all executable
meaning.

## Components

### Shared lifecycle envelope

`operator/restricted_scenario_worker.py` accepts an injected operator-owned
engine and a sealed scenario adapter.  It validates an exact
`RestrictedWorkerRequest`, launches the adapter's fixed entrypoint with an
empty environment and exact seccomp name, reads at most that adapter's fixed
completion size, invokes its canonical parser, and issues existing execution,
attestation, cleanup, and `PrimeWorkerBoundaryReceipt` facts.

It must preserve the P2/P3 rules: unique lease identity, cancellation-aware
cleanup, no retained worker after exit, no direct process invocation, and
redacted errors.  The envelope never derives a role, scenario, image, entry
point, workload digest, limits, or evidence level from untrusted input.

### Sealed scenario adapters

Each P4–P7 module exports a private adapter with literal constants and a
canonical completion parser.  The factory selects adapters only from a closed
internal mapping keyed by the application-owned scenario ID:

| Scenario | Fixed worker role | Completion proves |
|---|---|---|
| P4 `prime.long-session-continuity/v1` | `prime.long-session-continuity` | exact detach/attach/compact/recovery completion and disposal |
| P5 `prime.bounded-autonomy/v1` | `prime.bounded-autonomy` | fixed two-gate terminal trace and workspace-change fence |
| P6 `prime.continual-improvement/v1` | `prime.continual-improvement` | task-A/candidate/task-B plus preserved or exact rollback result |
| P7 `prime.arc-agi-3/v1` | `prime.arc-agi-3` | one isolated game, broker action/score replay, and teardown |

Adapters are application code, not manifests.  Every adapter allows only
`ipython` in its canonical completion and binds the result digest consumed by
the existing live reducer.  P7 exposes only the bounded single-game subset;
the full suite remains a distinct authorization level and has no default
launcher.

### Authority and evidence flow

```text
operator-owned restricted engine
  -> sealed adapter launch
  -> exact completion parser + engine attestation + cleanup receipt
  -> verify_prime_worker_boundary
  -> existing P4/P5/P6/P7 live validation reducer
  -> bounded-sandboxed evidence, only with explicit authorization facts
```

The shared envelope cannot issue evidence itself.  Provider-free tests use
fakes and can prove only rejection, identity, cleanup, and redaction paths.
Real execution requires an injected sandbox profile, explicit finite run
authorization, and the existing operator-owned model integration; no module
may read `.env`.

## Error handling and safety

- Missing or inconsistent lease, inspection, completion, broker, or cleanup
  facts fail closed with public-safe errors.
- A cancellation completes revocation/removal before it is surfaced.
- An adapter's output is bounded before parse; parsers reject extra fields,
  wrong digests, non-IPython tools, and noncanonical bytes.
- No environment values, host paths, corpus/game content, prompts, or raw
  model/worker output cross into public receipts.
- The engine, not an adapter assertion, attests isolation, read-only source,
  disposable workspace, absent credentials, and resource limits.

## Verification

Provider-free tests must cover each adapter's successful fake lifecycle,
malformed completion, wrong role/workload/image, duplicate/replayed lease,
cancellation, failed removal, forged inspection, oversized output, and
sentinel redaction.  Cross-product tests must prove an adapter cannot accept
another scenario's request or result digest.  Existing P4–P7 acceptance and
live reducer suites then validate the produced facts.

The implementation is complete only when every P4–P7 product has its own
sealed adapter, an exposed application integration path, and passing
provider-free tests.  A sandboxed claim still requires a separately authorized
finite real run; P7 full-suite reproduction is not part of this implementation
gate.
