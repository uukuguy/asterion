# Prime Climb Adapter Design

## Goal

Drive the approved Prime long-running-equivalence work as a durable, autonomous
verification loop.  The loop must never promote a capability without evidence,
must not reveal private model configuration, and must not leave daemon processes
behind.

## Scope

The adapter tracks progress toward three ordered closure gates:

1. provider-free native RLM lifecycle, recovery, redaction, and teardown;
2. a bounded real-model RLM receipt, including child creation, messaging,
   terminal state, and deletion;
3. the remaining mandatory Prime ledger domains and the separately pluggable
   native Asterion core.

It does not change the default framework runtime, authorize a provider call,
or treat a local test as external-provider evidence.

## Architecture

`docs/status/climb/` is the tracked, append-only experiment state.  It contains
the ranked closure hypotheses, completed cycle records, a machine-readable
session cursor, and a generated `research-tree.md` resume summary.

`tools/climb/` owns a foreground-only cycle runner.  Each cycle selects one
hypothesis, runs its declared provider-free verification first, then records
one of `passed`, `falsified`, `external-limited`, or `blocked-by-code`.  A
bounded-model cycle is invoked only through the existing explicitly named
operator command; configuration remains in `.env` and only its digest-safe
result enters climb state.

The generated tree and `docs/status/JOURNAL.md` are updated after every cycle.
No cycle starts a detached daemon or relies on a background PID.

## Initial Hypotheses

- H-001: extend the real Prime provider-free harness with lifecycle and
  teardown observations.
- H-002: prove exact recovery fencing and durable RLM replay across restart.
- H-003: execute and classify the bounded real-model RLM receipt.
- H-004: expand the verified provider-free RLM evidence into the parity ledger.
- H-005: advance the next mandatory Prime ledger domain after RLM closure.

## Verification and Failure Handling

Every cycle runs a named command and stores only command identity, stable
outcome, commit, and safe aggregate counts.  Test or transport failures are
classified and generate the next repair hypothesis; they never become a global
stop condition.  A real-model run interrupted by the interactive execution
limit remains `external-limited`, while its protocol cleanup is independently
checked for process residue.

The only terminal condition is that all mandatory ledger capabilities have
appropriate provider-free or bounded evidence and the native-core successor
plan is implemented and verified.  Until then the cycle cursor advances.

## Compatibility and Security

The adapter is outside `src/asterion/` and has no runtime import path.  It
contains no model identifiers, credentials, prompts, provider payloads, raw
outputs, or private filesystem paths.  It records only stable capability IDs,
test command IDs, and redacted outcome classifications.
