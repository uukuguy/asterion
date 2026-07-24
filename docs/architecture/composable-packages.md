# Composable Framework Packages

## Static composition, not execution

`dci.package/v1` describes portable package dependencies and outputs. The Python
reference composer validates a set of manifests, resolves their dependency DAG,
and returns a deterministic summary. It does not execute a workflow, select a
runtime, invoke tools, schedule work, or persist state.

Python owns the reference composer. The TypeScript host validates the same
canonical schema and fixtures, but does not implement a second composer. A future
execution layer may consume a resolved graph; it must preserve the package IDs,
declared policy requirements, and protocol boundaries established here.

## Manifest contract

Every manifest is a closed JSON object. Its edge arrays contain non-empty strings
in sorted, duplicate-free order. For example, a research capability can declare:

```json
{
  "protocol": "dci.package/v1",
  "package_id": "dci.research",
  "version": "1.0.0",
  "kind": "capability",
  "provides_capabilities": ["research.local-corpus"],
  "requires_capabilities": ["filesystem.read", "shell"],
  "requires_policies": ["policy.local-corpus"],
  "emits_events": ["artifact.created", "tool.result"],
  "consumes_events": ["run.started"],
  "produces_artifacts": ["application/vnd.dci.research+json"],
  "consumes_artifacts": ["text/plain"]
}
```

The canonical definition is
`schemas/packages/v1/package-manifest.schema.json`; shared positive and negative
fixtures live in `tests/fixtures/packages/v1/`. The reference manifests under
`src/asterion/capabilities/dci_research/manifests/` form the policy → research → evaluation → observability
DCI graph.

## Resolving a graph

Load manifests as JSON mappings and pass only portable host edges to the pure
resolver:

```python
from dci.framework.packages import compose_packages

composition = compose_packages(
    manifests,
    host_capabilities={"filesystem.read", "shell"},
    host_events={"artifact.created", "run.completed", "run.started", "tool.result"},
    host_artifacts={"text/plain"},
)
print(composition.package_ids)
```

The resolver rejects duplicate IDs, ambiguous capability providers, missing
capability/policy/event/artifact edges, and cycles. Input order does not change
the resulting `composition.package_ids` or normalized edge summary.

## Adding a package

1. Choose one portable kind: `capability`, `workflow`, `policy`, `memory`,
   `observability`, or `evaluation`.
2. Add a closed manifest with a stable ID and semantic version.
3. Declare only portable capability, policy, event, and artifact edges.
4. Add positive/negative fixtures or composition tests for any new edge pattern.
5. Verify the graph against every intended host's normalized capabilities.

Create one runtime-neutral manifest, not adapter-specific variants. Runtime
adapters translate native capabilities into protocol IDs before composition;
package identity and dependency semantics remain unchanged.

Manifests must never contain prompts, credentials, executable paths, commands,
environment variables, mutable state, provider configuration, or adapter-private
types. Those values belong behind runtime, policy, or controlled-executor
boundaries. Package composition is not an authorization substitute: execution
still requires the applicable runtime and executor policy checks.

## Verification

Run these checks from the standalone repository root:

```bash
uv run python -m unittest -v tests.test_package_execution
make test-typescript
```
