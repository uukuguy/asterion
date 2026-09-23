# Phase 10 draft — P1 verification isolation and Pi prompt ownership

Originally drafted 2026-09-19; corrected 2026-09-22 against
[architecture and execution review R1/R6](../../reviews/2026-09-22-architecture-and-execution-review.md).
This remains a design draft. It does not authorize a strategy rollout, a public
receipt change, or additional model execution.

## Verified facts

The earlier D-2026-09-19-03 interpretation of a leading `agent_settled` as an
implicit acknowledgment was incorrect. The local producer reproducer shows
that Asterion returned at `agent_end`, left that prompt's trailing settlement
in the shared queue, then consumed it after sending the next prompt. This
accounts for a false second completion and a subsequent request-ID mismatch.

An exact request-ID response and an operation settlement barrier are both
required. `agent_end` closes an agent cycle; post-run continuation can start
another cycle before `agent_settled`. Settlement is emitted on failure paths
as well and does not establish successful execution, tool effects, or oracle
acceptance.

The kernel already resets `_native_events` for each invoke and uses local
round state. Two kernels sharing one PiRpcSession also share the process,
pipes, queue and Pi transcript. Resetting one kernel's sequence counter while
RPC sequence numbers continue is an identity error, not session isolation.

The 2026-09-22 change adds provider-free regressions for delayed settlement,
consecutive prompts, post-run continuation, acknowledgment errors, failure
and cancellation fencing, and equivalent manual compaction acceptance with
`compact_events=False/True`. The accompanying implementation plan records
these checks. No new live P1 result is established by these tests.

## Current judgment

Repair and verify prompt ownership before choosing a verification strategy.
A shared-session setup/verify flow can be correct when that ownership is
explicit. Whether P1 should use an independent reviewer is a separate research
choice with its own authority and evidence requirements.

A genuinely independent child session needs a distinct session identity,
transcript, prompt ownership, permissions and finite budget attribution. It
may share the Python host process only if those resources are explicitly
separated. A new Pi subprocess supplies process separation, but worker state
transfer and extension authority still require a concrete contract. Neither
choice is implemented or selected as a new default by this draft.

A strategy is selected to satisfy an isolation requirement. It must not act as
an automatic fallback for an unexplained failed verification. Retrying after
uncertain tool effects requires explicit recovery evidence and authority.

## Internal prompt operation contract

```text
ready → dispatched → acknowledged/running → settled → ready
                 └─ lost ownership, cancellation, transport failure → fenced
before dispatch cancellation → cancelled without sending a prompt
```

Native activity can precede the response, so the reducer preserves that
activity while requiring the exact request acknowledgment before returning.
A leading settlement cannot acknowledge a newly sent request. Unknown queued
events fence the session rather than being discarded or assigned to a new
request. A single command owner holds the session through settlement, under
the existing absolute session deadline.

Atomicity here means exclusive ownership, exact event attribution, and one
determined result. It does not mean transactional rollback of IPython effects.
After dispatch, missing evidence leaves effects uncertain; closing the Pi
process cannot undo arbitrary files, external calls or worker changes.
Application completion still requires a valid tool ledger, the required
result and the relevant oracle. Public v1 runtime contracts remain unchanged.

Manual compaction validates response identity, command and result before
canonical projection. Event compression cannot change the validity of the
same producer transcript.

## Historical assumptions withdrawn

- Leading settlement proves the second prompt was accepted.
- A false second completion proves Pi never executed that prompt. Asterion
  could have returned early and closed resources while execution continued.
- Two kernels on one RPC session form an independent subagent session.
- Closing a prompt operation rolls back all state changes.
- Attachment reconstruction against the same live worker/RPC establishes
  restoration into an arbitrary fresh process.
- Existing P2–P7 witnesses prove the P1 live path or every public assembly.

## Unfinished boundaries and next action

First review the prompt ownership implementation and run the named local
regressions. A separately authorized, finite existing P1 preset must then
check setup, verification, worker effects and oracle end to end before the
live P1 path can be described as verified. Current local tests do not prove
that the original P1 failure has no additional cause.

If independent verification is still required, specify child-session
identity, transcript transfer, worker attachment/checkpoint scope, permissions,
budget ownership and cancellation recovery before implementing that strategy.
Any receipt field requires its own canonical hashing and validation change;
this draft adds none.
