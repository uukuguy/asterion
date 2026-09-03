# Prime P7 ARC-AGI-3 Design

## Decision

`prime.arc-agi-3/v1` is the seventh and highest-complexity Prime acceptance
product: a model acts on one game only through an IPython-imported, host-owned
broker that exposes exactly `observe`, `status`, and `act`.  It proves the
distinctive Prime shape—persistent programmatic reasoning over an interactive
environment—without treating a toy game fixture or a trusted-local run as an
ARC-AGI-3 reproduction.

The implementation has two deliberately non-interchangeable paths:

1. a closed public-subset functional gate, which is provider-free and can
   validate causal traces and broker boundaries; and
2. an explicitly authorized full multi-game reducer, which can issue a
   `full-authorized` receipt only from completed restricted-worker evidence.

Neither path starts a Docker worker, reaches a network endpoint, selects a
provider/model, obtains game content, or executes a benchmark.  Those actions
remain operator-owned and separately authorized.

## Closed workload

The P7 workload fixes digests for the public-subset fixture, broker schema,
model selector, score oracle, action encoding, and full-suite definition.  It
also fixes `("ipython",)` as the sole model action surface, a finite maximum
of observations/actions/usage, and exactly one game per worker session.

The public trace contains no board cells, game ID, action payload, score,
prompt, provider content, private path, credential, or raw output.  Instead it
binds canonical SHA-256 projections for initial observation, every action,
terminal status, replayed score, and cleanup.  The full-suite result has a
separate suite digest and an exact expected game count; it is not inferred from
the public subset trace.

## Broker boundary

The broker is an injected host protocol, never an application manifest or a
model capability declaration.  It owns game selection and private state.  The
model-facing side permits only:

- `observe()` → current redacted observation projection;
- `status()` → terminal/liveness projection; and
- `act(action)` → a bounded action receipt.

It rejects unknown methods, malformed action projections, a second game,
calls after terminal state, repeated sequence numbers, and calls over the
closed observation/action ceiling.  It may expose digests and finite counters
only in public evidence.  It never offers game SDK access, engine source,
other-game enumeration, previous run state, networking, host filesystem, or
credentials.

## Causal acceptance trace

A valid public-subset trace has this exact order:

1. a fresh broker/session reports one initial nonterminal observation;
2. Prime uses only IPython and makes a contiguous bounded sequence of broker
   `observe`, `status`, and `act` calls for that same game;
3. the broker reaches one terminal status and refuses further actions;
4. the host score oracle replays the action-projection chain and binds the
   terminal score digest; and
5. the worker, broker state, and session are disposed/reaped.

It fails closed on changed workload/schema/model/oracle, a non-IPython tool,
multiple games, action/result substitutions, skipped or duplicated sequence,
nonterminal cleanup, terminal action, score replay mismatch, exceeded limits,
or any extra trace field.  A provider-free fake may issue only
`provider-free` evidence.

## Full authorization boundary

The live observation admits only a validated trace, a matching
`PrimeWorkerBoundaryReceipt`, and an exact platform lock.  Bounded-sandboxed
subset evidence additionally requires real-IPython, broker-isolation,
score-replay, quiescence, and destroyed-worker attestations.

Full reproduction has an additional closed authorization object.  It must bind
the same platform lock, P7 full-suite digest, expected/completed game count,
and an exact finite budget authorization ID; require `full_reproduction_approved
is True`; and require a full-suite worker result digest distinct from the
subset trace result.  A subset receipt, a global approval, a configuration
file, or prior evidence cannot substitute for this authorization.  The full
reducer does not launch or schedule games, and local tests exercise it only
with fake normalized facts.

## Delivery slices

1. Define one canonical workload and redacted immutable trace, including
   action/observation/score projections and rejection matrix.
2. Add a narrow injected broker adapter plus provider-free acceptance path;
   prove one-game isolation, exact sequence, terminal fencing, replay, and
   cleanup.
3. Add private live admission/revalidation and a separately shaped full-suite
   authorization reducer.  Local tests prove all negative boundaries but do
   not claim a live run.

## Verification

Scoped `unittest`, Ruff, Pyright, and `git diff --check` remain provider-free.
Tests cover success; malformed, duplicate, skipped, and post-terminal broker
calls; immutability; canonical projections; worker/lock/result substitutions;
every false attestation; full-suite count/lock/digest/approval mismatches; and
sentinel redaction.  Real public-subset or full multi-game execution remains
External-limited until the operator separately authorizes it.
