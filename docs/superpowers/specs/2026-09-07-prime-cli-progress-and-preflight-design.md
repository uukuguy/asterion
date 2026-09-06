# Prime CLI Progress and Preflight Design

> Status: proposed. Scope: Prime P1-P7 development commands, host progress
> injection, and provider-free application preflight. Protocol impact: none to
> the four closed v1 wire contracts.

## Problem

`make prime-p1-run` through `make prime-p7-run` are human-facing development
commands, but they currently expose only `uv` installation output and the final
application JSON. A failure is reduced to a coarse CLI error, so the operator
cannot tell which task is running or whether failure occurred during resource
preflight, worker startup, bounded model work, validation, or cleanup.

The problem is already observable in two independent defects:

1. W1d moved `python-dotenv` from core dependencies into the `prime` extra,
   while all seven isolated Make recipes initially omitted that extra. Commit
   `b495dd63` corrected the dependency boundary.
2. P2 currently fails after an Orb restart because every Prime host assumes
   Node 22 and a seccomp profile exist under `/tmp`. Those ephemeral paths are
   absent even though the gateway and pinned P2 image are present. The source
   image-inspect argv is already correct and must remain locked by a regression
   test.

The fix must keep prompts, answers, credentials, provider payloads, private
paths, and raw subprocess output off public surfaces.

## Chosen Approach

Use a framework-owned, injected progress reporter carrying only validated,
enumerated metadata. Prime integration emits progress through that reporter.
Make recipes print one static purpose line, prepare the selected scenario's
reproducible development resources, and opt into progress rendering.

This is preferred over direct Python logging because it avoids global logging
state and gives tests an explicit dependency. It is preferred over streaming
new runtime events because progress is host execution metadata, and changing
the closed runtime stream or runner contract is unnecessary for this use case.

## Public-Safe Progress Contract

Add a narrow Python-only host integration API under `asterion.services`. It is
not a manifest field and does not change any JSON schema.

```python
@dataclass(frozen=True)
class HostProgressEvent:
    component: str
    state: str
    current: int | None = None
    total: int | None = None

class HostProgressReporter(Protocol):
    def emit(self, event: HostProgressEvent) -> None: ...
```

`component` is restricted to this framework-owned set:

- `preflight`
- `source`
- `gateway`
- `image`
- `worker`
- `model`
- `tool`
- `validation`
- `cleanup`

`state` is exactly `started`, `succeeded`, or `failed`. `current` and `total`
must either both be absent or satisfy `1 <= current <= total <= 64`. The value
has no free-form message, path, identifier, payload, exception, or mapping.
Construction snapshots immutable values and rejects subclasses or hostile
objects before rendering.

A no-op reporter is the default. Existing application hosts and direct CLI
commands therefore retain their behavior unless progress is explicitly enabled.

## Injection and Rendering

`HostServiceFactoryRegistry.open` accepts an optional reporter and places a
framework-owned failure-contained wrapper in `HostServiceFactoryContext`. The
context field uses a no-op default and `repr=False, compare=False, hash=False`
so existing construction remains source compatible and reporter identity
cannot affect context equality, hashing, or rendering. The wrapper never calls
reporter `repr`, equality, or hashing; hostile `emit` behavior is caught and
permanently disables that reporter without affecting product execution or
cleanup.

The generic `asterion run` parser gains `--progress`. When present, the CLI
creates a text reporter bound to `stderr` and passes it to the host registry.
Rendering uses only framework-owned labels:

```text
[host] preflight: started
[host] preflight: succeeded
[host] worker: started
[host] model 1/2: started
[host] validation: succeeded
[host] cleanup: succeeded
```

The renderer never prints `str(error)`, `repr(error)`, provider data, host
options, event attributes outside the closed value, or arbitrary product text.
Reporter write failure cannot alter execution or cleanup; it disables further
progress output and stays private.

Each Prime Make recipe passes `--progress` and writes one fixed description to
`stderr` before starting `uv`. Final application JSON remains the only Asterion
payload on `stdout`, preserving scripts that capture it.

## Prime Command Descriptions

The seven fixed descriptions are:

| Command | Description |
|---|---|
| `prime-p1-run` | IPython coding: preserve state across two cells and validate the generated solution |
| `prime-p2-run` | Programmatic long context: use the fixed corpus, execute one cell, and validate the answer |
| `prime-p3-run` | Recursive workflow: coordinate two child roles and validate the combined result |
| `prime-p4-run` | Long session continuity: detach, reattach, and validate the preserved session |
| `prime-p5-run` | Bounded autonomy: diagnose, repair, and validate the fixed clamp task |
| `prime-p6-run` | Continual improvement: evaluate, refine, holdout-test, then activate or roll back |
| `prime-p7-run` | ARC-AGI-3: run one offline episode capped at four actions and replay its score |

These descriptions identify behavior without exposing the fixed prompts,
expected answer bodies, corpus content, or private environment.

## Prime Progress Mapping

Each product host translates its internal control flow into the generic event
set. The expected sequence is concise rather than a trace of every internal
operation:

| Scenario | Required coarse progress |
|---|---|
| P1 | preflight, image, worker, model callbacks, tool calls, validation, cleanup |
| P2 | preflight, image, source, worker, model callbacks, tool, validation, cleanup |
| P3 | preflight, source, gateway, child workers, model callbacks, validation, cleanup |
| P4 | preflight, gateway, worker, model callbacks, validation, cleanup |
| P5 | preflight, worker, model/tool stages, validation, cleanup |
| P6 | preflight, worker, model/tool stages, validation, cleanup |
| P7 | preflight, source, worker, model/tool actions, validation, cleanup |

Repeated bounded work reports `current/total`. The reporter may omit an event
when execution never reaches that component. Once a component emits `failed`,
cleanup progress may continue, but no later work component may claim success.
Cleanup completion is emitted only after the host's existing residue checks.
The wrapper enforces terminal ordering: after any non-cleanup component reports
`failed`, only cleanup events may be accepted. A cleanup failure is terminal.

The progress reporter observes execution; it does not select a provider,
authorize a command, weaken a deadline, change a budget, retry work, persist
evidence, or decide success.

## Reproducible Scenario Preparation

Long-lived development prerequisites must not live under `/tmp`. Add an
idempotent selected-scenario preparation command used by every
`prime-pN-run` recipe before `asterion run`. It stores generated operator assets
under ignored `.asterion-private/prime-development/` and performs no model or
application execution.

Preparation and the subsequent run execute inside the same selected
`PRIME_ORB_MACHINE`, as the same user, from the same working tree, on the same
OS and architecture, and against the same Docker daemon context. The Make
recipe owns that sequence; it cannot prepare on the macOS host and consume the
result from an Orb guest, or prepare against one daemon and run against
another.

For the selected scenario it:

1. resolves the code-owned, integrity-locked Node `22.23.2` artifact into the
   project-local private cache and verifies both its artifact integrity and
   executable content;
2. materializes the reviewed, digest-locked development seccomp profile from a
   packaged Prime application resource;
3. validates the Prime Gateway against the exact locked input aggregate and
   output digest, rebuilding it whenever either identity differs;
4. uses the existing exact Prime source preparation logic for the configured
   local source root;
5. validates the selected scenario image digest and builds that image from its
   reviewed Dockerfile when it is missing; and
6. prepares P7's fixed offline environment only when P7 is selected.

The authoritative preparation lock is a packaged, code-owned resource. It
contains a format version and exact expected identities for:

- supported OS and architecture;
- the Node distribution source, version, archive integrity value, and extracted
  executable SHA-256;
- the packaged seccomp profile SHA-256;
- the aggregate SHA-256 of locked Gateway inputs and the expected Gateway
  output SHA-256;
- the Prime source commit plus module-lock identities used by each scenario;
- every scenario image tag and image digest; and
- the P7 offline-environment lock when P7 is prepared.

Preparation writes a cache receipt under
`.asterion-private/prime-development/`. The receipt also binds the selected Orb
machine, user, working-tree identity, OS, architecture, and Docker daemon
context. It is generated evidence rather than authority. Reuse requires
rehashing every cached artifact and matching both the code-owned lock and the
current execution context. Version output, path existence, timestamps, and the
receipt alone are insufficient. Any mismatch rebuilds the affected artifact or
fails closed.

Preparation stages generated artifacts and the new receipt in sibling temporary
locations, verifies their complete content set, then publishes them with atomic
renames. An interrupted preparation leaves the last fully verified receipt and
artifacts intact; partially staged content is never eligible for reuse.

Preparation uses fixed versions, roots, deadlines, and output caps. It never
reads `.env`, provider credentials, or model configuration. Network and disk
effects are allowed only for exact dependency/source/image preparation and are
announced before they begin. A failed preparation reports a fixed component and
an actionable Make target without rendering a private path.

Prime CLI hosts derive canonical fixed paths under the repository's
`.asterion-private/prime-development/` root and validate the preparation lock
before opening Node or seccomp resources. They no longer hardcode `/tmp` paths.
No path is added to a manifest or closed protocol, and callers cannot override
the cache location through a public command option.

P2 retains an exact image-inspect argv assertion matching:

```text
/usr/bin/docker --host unix:///var/run/docker.sock image inspect
  --format {{.Id}} asterion-p2-development:20260906
```

The existing pinned image digest comparison remains unchanged. After resource
preparation, P2 provider-free preflight must pass before one formal bounded P2
run is made.

## Provider-Free Seven-Application Preflight

Add `make prime-apps-preflight`. In the same selected Orb execution context, it
first runs preparation for all seven scenarios. It then resolves the installed
Prime provider and opens then closes each exact host-service context without
invoking a runtime, model callback, tool call, or worker workload. Preparation
failure produces that application's public FAIL row and prevents its context
from opening; other rows continue so the command always accounts for all seven
applications. It reports one public PASS/FAIL row per application and uses the
same progress renderer.

The check must verify exact entry-point loading, application/assembly identity,
host capability selection, and application-owned resource preflight. It must
close every acquired descriptor or transport before returning. Current host
preflight may read required credential presence for readiness, but it must not
render, transmit, persist, or use credential values. P7's bounded isolated
local-interpreter readiness probe is allowed. A failed row does not authorize
execution and must not reveal a path or configuration value.

Individual `prime-p*-run` commands retain their own preflight so state cannot
change between the aggregate check and actual execution without detection.

## Failure Behavior

- Entry-point import or binding failure renders `host-service-factory-load`.
- Host resource preflight failure renders the last safe component and
  `host-service unavailable`.
- Execution failure renders the last started component as failed, then reports
  cleanup if cleanup ran.
- Unknown or hostile exceptions keep the generic `asterion: command failed`.
- The command exits nonzero after cleanup settles.
- Successful commands retain the current immutable final JSON result.

## Implementation Boundaries

- Framework: progress value, no-op/text reporter, context injection, CLI flag,
  validation, and redaction tests.
- Prime integration: static descriptions, P1-P7 coarse stage emission,
  reproducible selected-scenario preparation, application-host preflight, and
  P2 image-inspect argv regression coverage.
- Runtime protocol, capability manifests, application assemblies, runners,
  authorization, budgets, prompts, and result schemas remain unchanged.

## Verification

Use focused development checks only:

1. Progress value validation, immutability, reporter write containment, and
   sentinel redaction tests.
2. Host registry context injection and no-op compatibility tests.
3. CLI tests proving progress uses `stderr` while final JSON stays on `stdout`.
4. A seven-row Make recipe matrix proving descriptions, `--extra prime`,
   `--progress`, exact application selectors, and fixed input.
5. One focused progress-sequence test per Prime scenario, including cleanup
   after a failure at a representative boundary.
6. Selected-scenario preparation tests for idempotence, exact locks, stale
   `/tmp` independence, bounded failure, and no credential access.
7. P2 exact Docker image-inspect argv test.
8. `make prime-apps-preflight`, requiring seven provider-free PASS rows. Its
   preparation phase may perform the locked downloads, builds, and Docker image
   operations defined above, but it performs zero provider, model, tool,
   worker-workload, or application-container operations; readiness credential
   values are never rendered, transmitted, or persisted.
9. `PRIME_RUN_ID=prime-p2-20260907-fixed make prime-p2-run`, followed by a zero
   residue inspection.
10. Focused Ruff, documentation, and diff checks. Full `make check` and
   `promotion-check` remain outside this development fix.

## Acceptance

The work is complete when P1-P7 each state their purpose before execution,
render actual safe progress while running, keep final JSON machine-readable,
identify the safe failure component, pass aggregate provider-free preflight,
and P2 completes through the exact Make command with zero residue.
