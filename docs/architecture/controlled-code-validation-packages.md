# Controlled Code Validation Packages

## Second independent graph

The controlled-code reference graph challenges `dci.package/v1` with a shape
that is independent of DCI research:

```text
policy.controlled-code-check
  → workflow.code-quality
      → evaluation.code-quality
      → observability.execution-audit
```

The graph exercises the `workflow` package kind and links policy, capabilities,
events, and artifacts. It proves the package contract can describe code-quality
validation without adding a scheduler.

## Static composition, not code execution

The composer validates manifests, rejects missing edges, and returns a stable
package order and normalized output summary. It does not execute commands, start
the Rust sidecar, inspect source code, schedule workflow steps, or repair files.

The existing Rust executor remains a separate policy-enforcing process boundary.
Resolving this graph neither authorizes a concrete execute request nor changes
the executor's trusted startup policy.

## Package roles

- `policy.controlled-code-check` supplies the required policy identity.
- `workflow.code-quality` consumes source input and portable host capabilities,
  then declares a code-quality report and completion event.
- `evaluation.code-quality` consumes the report and declares a verdict artifact.
- `observability.execution-audit` consumes the report plus portable lifecycle
  events and declares an execution-audit artifact.

The workflow manifest is a closed portable declaration:

```json
{
  "protocol": "dci.package/v1",
  "package_id": "workflow.code-quality",
  "version": "1.0.0",
  "kind": "workflow",
  "provides_capabilities": ["workflow.code-quality"],
  "requires_capabilities": ["executor.controlled", "filesystem.read"],
  "requires_policies": ["policy.controlled-code-check"],
  "emits_events": ["workflow.code-quality.completed"],
  "consumes_events": ["run.started", "tool.result"],
  "produces_artifacts": ["application/vnd.dci.code-quality+json"],
  "consumes_artifacts": ["text/x-source"]
}
```

## Shared host service boundary

Pi and Claude Code normalize their native read capability to `filesystem.read`.
The host adds `executor.controlled` from the same shared host service; neither
runtime claims the executor capability natively:

```python
from dci.framework.adapters.pi import map_pi_capabilities
from dci.framework.packages import compose_packages

runtime_capabilities = set(map_pi_capabilities("read"))
host_capabilities = runtime_capabilities | {"executor.controlled"}
composition = compose_packages(
    manifests,
    host_capabilities=host_capabilities,
    host_events={"run.started", "tool.result"},
    host_artifacts={"text/x-source"},
)
print(composition.package_ids)
```

This capability injection does not make Pi or Claude Code a sandbox. The local
Rust service enforces its documented process policy, but it is not operating-
system isolation and the package graph does not strengthen that claim.

## Rejection boundaries

Composition fails closed when either host capability is absent, the policy
package is missing, `tool.result` is unavailable, source input is unavailable,
or the workflow stops declaring the completion event or report artifact. Input
permutation does not change a successful result.

Manifests must not contain commands, executable paths, argument vectors,
environment values, workspace paths, prompts, credentials, providers, mutable
state, or adapter-private types.

## Architectural conclusion

The second graph is expressible and validated without modifying the Python
composer. It therefore does not trigger a workflow engine under D-022. A future
execution proposal needs new evidence that independently useful graphs cannot be
represented or safely validated by the static contract.

## Executable Asterion application

AF-140 adds that execution as a separate layer without changing the portable
manifests or composer. The `controlled-code` installed provider binds exact
workflow, evaluation, and observability implementations; the policy remains
declarative. The workflow submits one logical relative target to an explicitly
injected `executor.controlled` service. Trusted host configuration—not agent
input—owns the program, arguments, workspace, deadline, and output limits.

The JSONL client connects only to caller-owned streams for an already running
Rust sidecar. It never starts a process and discards stdout/stderr bodies after
deriving bounded metadata. The focused host composition lives at
`examples/applications/controlled_code.py`.

For the installed CLI, AF-150 makes lifecycle ownership explicit. A
`controlled-code` run requires the complete `--executor-binary`,
`--executor-policy`, and `--executor-validation-config` set (or their
`ASTERION_EXECUTOR_*` environment equivalents). After provider, assembly,
binding, and configuration preflight, the CLI starts exactly one direct-argv
stdio sidecar, injects it, then closes and reaps it. This is process ownership,
not automatic service discovery or a sandbox claim.

## Verification

Run these checks from the standalone repository root:

```bash
uv run python -m unittest -v tests.test_controlled_code_application
make test-typescript
make check-rust
```
