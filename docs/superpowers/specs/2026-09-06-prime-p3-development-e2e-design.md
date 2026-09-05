# Prime P3 Development E2E Design

## Decision

P3 closes only when the installed `prime.recursive-workflow@1.0.0`
application completes a real pinned Prime recursive workflow. The existing
provider-free daemon/shim compatibility witness remains useful evidence, but
it cannot close P3 because it does not execute child models or child IPython
work.

The development route uses:

- scenario `prime.recursive-workflow/v1`;
- runtime `prime.agent`;
- capability `prime.recursive-workflow@1.0.0`;
- injected host service `prime.recursive-workflow-development`;
- fixed input `fixed-small-verification`;
- result scope `p3-development` and promotion `unpromoted`.

Prime owns root and child session semantics. Python owns admission, budgets,
Docker processes, the independent oracle, cleanup, and public trace projection.

## Considered approaches

1. **Real RLM through the root IPython path — selected.** The root model makes
   one IPython call whose restricted RLM RPC invokes pinned
   `runRlmChild`. This reproduces the user-facing recursive capability and
   exercises the integration protocol that must support nested callbacks.
2. **Host calls `runRlmChild` directly.** This proves the SDK API but bypasses
   the root tool path and would leave the important reentrant integration gap
   open.
3. **Retain the provider-free shim as closure evidence.** This remains a
   compatibility check only because it fabricates lifecycle facts without
   model or worker execution.

## Fixed workflow

The workload is a small inclusive-range defect review. The initial source uses
`low <= value <= high` where the contract requires an exclusive upper bound,
and its initial test covers only an interior value.

1. The root model uses IPython exactly once to create the fixed source/test
   workspace and invoke two depth-one RLM children through the restricted RPC.
2. The implementation child uses IPython exactly once, identifies the
   exclusive-upper-bound defect, patches it, and records its canonical result.
3. The review child uses IPython exactly once, identifies the missing upper
   boundary test, and records its canonical review.
4. The retained review child receives one follow-up in the same Prime session,
   uses IPython exactly once, and verifies the fixed boundary cases
   `(5, 1, 5)` plus the interior case.
5. The root aggregates the child results, deletes both children with
   `deleteRlmSubagent`, and requires `listRlmSubagents()` to be empty.

The fixed normal path has two children at depth one, ten model callbacks and
four IPython calls: root 4/1, implementation 2/1, review initial 2/1, review
follow-up 2/1. Pinned Prime schedules the root's normal post-tool continuation
and one terminal-notice cycle for each child, which accounts for the last three
root callbacks. Counts come from actual callbacks and are partitioned by role;
parent usage never re-adds child usage.

## Reentrant gateway protocol

The current development gateway blocks its sole reader while a synchronous
tool callback waits. P3 cannot use that behavior because the root IPython cell
waits for `runRlmChild`, while those children need model and IPython callbacks
over the same gateway.

The Python transport gains two internal operations:

- `request_nested(kind, payload) -> Future` queues one closed P3 nested command;
- `_pump_until(future, absolute_deadline)` keeps the single IO owner reading
  and dispatching frames until that future settles.

Only one thread reads the socket. Callback work runs outside the reader. The IO
owner sends queued commands, dispatches model/tool requests, and resolves
responses by exact request ID. Sequence numbers stay contiguous; duplicate,
unknown, late, or mismatched responses fail closed. Every nested operation uses
the parent absolute deadline and cancellation signal. No second socket reader,
composer, session runner, retry loop, or hidden precedence is introduced.

During a root prompt, the P3 Node bridge accepts only the closed nested RLM
commands needed for spawn, wait, follow-up, list, and delete. It delegates them
to the root session's public `runRlmChild`, `listRlmSubagents`, retained child
session, and `deleteRlmSubagent` APIs.

## Child runtime host

The TypeScript gateway supplies a `SubagentRuntimeHost`. For every SDK-issued
child ID it creates and publishes one real child session using the SDK-provided
model, depth, parent node, tool allowlist, and session directory. Each child
receives only its independently bound IPython worker. The host retains the
review child after initial completion so the follow-up targets the same
session. It never substitutes a third child or opens manually unrelated
sessions.

Child IDs, role IDs, session identities, callback ownership, worker identity,
and artifact paths are exact. Ambiguity, duplicate publication, depth other
than one, extra children, extra tools, or cross-child worker access fails
closed.

## Execution and oracle

The root, implementation child, and review child use separate Docker-backed
IPython kernels. The root worker exposes only a bounded local RLM RPC; child
workers cannot recurse. Docker uses the existing exact image, seccomp, cleared
environment, deadline, output cap, direct invocation, and absence proof
patterns.

The host reads the actual source, tests, implementation result, review result,
follow-up result, and aggregate after execution. It independently verifies the
exclusive bound, all fixed cases, causal order, exact child/depth/callback/tool
counts, deterministic usage accounting, terminal completion, deletion, empty
roster, and container/process absence.

The public artifact is
`prime.p3-development.trace` with media type
`application/vnd.asterion.prime.p3-development-trace+json`. Its value contains
only `scope`, `promotion`, and a trace digest. The digest binds fixed IDs,
workload/image/source digests, role-partitioned usage, observations, oracle
facts, and cleanup. Prompts, source, tests, model content, child IDs, paths,
provider configuration, worker output, and exception bodies never cross the
public boundary.

## Failure and cleanup

Failure, cancellation, timeout, callback limit, oracle mismatch, and protocol
error all stop new callbacks, abort root and child sessions, unregister the
provider, close the RLM RPC, remove every worker, reap Node/provider processes,
and verify absence. A cleanup uncertainty cannot produce success. Public
exceptions are body-free and have no private exception context.

## Development verification

Verification is limited to the normal provider-free contract path and the
important boundaries:

- reentrant nested callback progression without deadlock;
- exact child identity, depth, role, retained follow-up, counts, and usage;
- oracle mismatch and missing follow-up rejection;
- callback/deadline/cancellation cleanup;
- sentinel redaction and public exception isolation;
- P1/P2 gateway regression;
- one real exact-selector CLI run and post-run absence inspection.

Release matrices, production promotion, arbitrary recursion depth, global
registries, and repeated real runs are outside this development closure.
