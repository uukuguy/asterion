# Prime P4 Diagnostic Session Recovery Design

## Decision

`prime.long-session-continuity/v1` will reproduce one fixed offline diagnostic
recovery workflow.  The root session uses IPython to inspect a fixed diagnostic
fixture, records a local checkpoint artifact, and registers one fixed child
diagnostic artifact.  It detaches, reattaches with the exact cursor, performs
one bounded context compaction, undergoes one supervisor-generation recovery,
restores only durable assets, then continues the same diagnostic to a fixed
oracle.  No uncertain command, tool action, child message, or model request is
replayed.

The existing session-context parity and provider-free continuity receipts
remain useful compatibility evidence, but cannot by themselves issue P4
bounded evidence.

## Closed Contract

The P4 workload fixes the fixture, root task, child artifact role, model
identity, compaction instructions/schema, oracle, maximum turns, one detach,
one attach, one compaction, and one recovery.  Callers cannot supply prompts,
diagnostic text, code, files, paths, child identities, models, budgets,
environment, credentials, recovery cursors, or replay policy.

The model-visible action surface for root and child is exactly `ipython`.
P4 uses existing Prime gateway commands (`session.detach`, `session.attach`,
`session.compact`) as host lifecycle operations, not model tools.  Gateway
recovery uses the pinned session identity, transcript identity, supervisor
generation, and cursor already validated by Prime gateway code; P4 does not
reimplement session persistence or supervisor management.

## Required Causal Trace

The canonical trace requires this partial order:

1. root IPython diagnostic artifact and fixed child artifact registration;
2. durable checkpoint containing root artifact digest, child registry digest,
   oracle/workload/model identities, and exact cursor;
3. one root detach and one reattach with replay contiguous to that cursor;
4. one successful bounded compaction, whose summary is retained only as a
   digest and whose result is on the active context path;
5. one supervisor-generation change producing `recovery-required`, followed
   by validated recovery with the same active/transcript identities and a new
   exact cursor;
6. recovery restores the root artifact and child registry only from durable
   checkpoint records; it fences uncertain effects rather than replaying them;
7. root IPython continues after recovery, emits the fixed diagnostic result,
   and passes the fixed oracle; then the session and child artifact are
   disposed/reaped.

Duplicate/missing lifecycle events, identity/cursor substitutions, a
compaction result outside the active path, recovery without generation change,
continued work before recovery, restored live Python objects, or an uncertain
effect replay all fail closed.

## Evidence

The private completion binds workload, fixture, root pre/post-recovery artifact,
child registry, compaction summary, recovery cursor/generation, diagnostic
result, oracle, exact model/usage summaries, and dispose/reap facts.  It never
contains prompts, diagnostic content, source, artifact text, paths, session or
child identities, provider payloads, or credentials.

Provider-free fakes verify the trace contract, gateway command ordering,
identity/cursor rejection, redaction, and uncertain-effect fencing only.  A
bounded P4 receipt requires separately authorized real Prime session/
IPython execution, exact gateway recovery attestation, durable checkpoint
proof, broker quiescence, and worker destruction.  Docker, model, network, or
benchmark execution is not implied by provider-free tests.

## Delivery Slices

1. Replace the old continuity receipt's promotable surface with a fixed P4
   recovery-trace contract and demote parity reports to compatibility only.
2. Add fixed diagnostic workload, checkpoint schema, canonical trace parser,
   and static gateway protocol fixture.
3. Add a sealed P4 session-recovery adapter over existing gateway commands;
   prove cursor/generation binding, compaction/path validation, and uncertain
   replay fencing with fakes.
4. Add provider-free acceptance and a separately authorized live-evidence
   gate; record exact External-limited status pending a real execution.
