# Prime P3 Real RLM Code-Review Workflow Design

## Decision

`prime.recursive-workflow/v1` will reproduce one concrete, bounded Prime RLM
workflow: offline review and aggregation for a fixed small code change.  A root
agent uses its sole model action surface, IPython, to inspect the fixed change
and to aggregate results.  It creates two independent real Prime RLM child
sessions: one reviews implementation correctness and the other reviews tests
and boundary conditions.  After their first replies, the root keeps one child
alive, asks one fixed follow-up question, receives its second reply, produces a
fixed structured review, and deletes both children.  A fixed oracle verifies
only the final structured review.

This replaces the existing direct host-shim witness as P3 evidence.  That
witness may remain as a separately named bridge-compatibility diagnostic but
can never issue a receipt for `prime.recursive-workflow/v1`.

## Scope and Non-goals

The product has exactly one root, exactly two children, depth one, one retained
child follow-up, and fixed role-specific review tasks.  It demonstrates a
common RLM collaboration pattern without becoming a generic recursive executor
or a second coding product.

It does not claim arbitrary recursion depth, child model selection, arbitrary
goals, arbitrary messages, patch application, concurrent writable workspaces,
or sandbox proof.  P3 provider-free tests may verify contracts and rejection
paths only.  A bounded P3 PASS requires a separately authorized real model and
sealed worker execution; no fake fixture or static test can be promoted to it.

## Sealed Runtime Contract

P3 receives a code-owned workload identity containing the fixed repository
fixture, two fixed review roles, one exact inherited model identity, a depth
limit of one, finite per-root and per-child budgets, a fixed follow-up target,
and a fixed oracle/result schema.  Requesters cannot select a child count,
goal, prompt, code, model, command, path, environment, credential, timeout,
or budget.

P3 has a dedicated image, entrypoint, seccomp identity, workload digest,
result schema, Docker facade, and acceptance reducer.  It does not parameterize
the P1 coding or P2 long-context worker.  All root and child model tools are
exactly `("ipython",)`.  `rlm`, `agent_message`, and child deletion are only
IPython-imported APIs; they are not additional model-visible tool surfaces.

The P3 launcher owns fixed fixture content and private review instructions.  A
host broker may authenticate, bound, relay, revoke, and observe; it must not
create children, fabricate lifecycle events, supply a response as an action,
or claim that a child executed IPython.  The launcher rejects P1/P2 workload,
image, role, schema, and entrypoint identities before execution.

## Required Causal Trace

The signed trace uses logical roles and causal predecessors, never completion
arrival order.  It requires:

1. root self-check and a root IPython local-review artifact before either child
   result;
2. two independently admitted depth-one child sessions, each bound to its
   exact role, inherited model identity, budget, and worker challenge;
3. a root-to-child message, at least one child IPython action, and one explicit
   child-to-root result for each child;
4. root local continuation after both first results;
5. one fixed follow-up sent to the designated retained, idle child and one
   second explicit result from that same child;
6. root IPython aggregation, fixed-oracle PASS, and durable per-session usage
   attribution;
7. root-driven deletion of both idle children, then broker revoke/quiescence,
   worker destruction, and absence/cleanup evidence.

No child can spawn a grandchild.  Duplicate, missing, reordered, unbound,
cross-role, cross-run, cross-challenge, post-terminal, post-deletion, or
noncanonical events fail closed.  Host compensating cleanup is required after
failure but cannot satisfy the PASS requirement for root-driven child deletion.

## Completion and Evidence

The private canonical completion binds the P3 workload digest; root artifact
digest; role-normalized first and follow-up result digests; aggregation and
oracle digests; exact model digest; root and child usage summaries; child
lifecycle/deletion facts; and broker/worker cleanup identities.  It contains no
goal text, review text, child/native identities, paths, prompts, model payloads,
credentials, or raw output.

The P3 bounded reducer accepts only this completion plus the exact P3 worker
boundary and revoked/quiescent broker receipts.  It requires durable usage
attribution before reducing.  Public reports expose only fixed scenario/status,
hashes, counts, booleans, and a bounded evidence level.  `External-limited`,
provider-free bridge compatibility, a missing follow-up, or a child lifecycle
declared by a shim cannot issue a P3 receipt.

## Verification Plan

Provider-free tests first establish all fixed identities, trace ordering,
cross-product rejection, redaction, canonicality, count/depth/budget limits,
and non-promotion of the old bridge witness.  Fake services may exercise the
entire closed reducer but must be reported as provider-free only.

The later, separately authorized live validation runs the sealed P3 image with
the exact pinned Prime RLM API and bounded broker.  It verifies real
`await rlm(...)` child creation, real child session/IPython activity, explicit
messages and follow-up, usage durability, root-driven deletion, oracle PASS,
broker revocation, and destruction.  Each executed platform receives its own
explicit image lock; the recipe remains platform-neutral and has no host
platform fallback.

## Delivery Slices

1. Replace the old P3 receipt contract with a deny-by-default real-RLM trace
   contract; demote the old shim witness.
2. Add the sealed P3 workload, canonical trace/completion parser, fixed image
   locks, and static protocol tests.
3. Add the dedicated P3 broker/worker facade with causal lifecycle, usage, and
   cancellation/cleanup tests.
4. Add fake full-chain acceptance proving only provider-free mechanics; bind
   bounded issuance to a real-execution observation type that fakes cannot
   construct.
5. After explicit external-execution authorization, validate the pinned Prime
   RLM/IPython scenario and record the precise platform-specific result.

