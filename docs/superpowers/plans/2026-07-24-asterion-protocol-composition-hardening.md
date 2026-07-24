# Asterion Protocol and Composition Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the three v1 contracts canonical, immutable, deterministic, and fail-closed across Python, TypeScript, package composition, and application execution.

**Architecture:** Canonical schemas remain the shared wire authority; Python and TypeScript add semantic validation that JSON Schema cannot express, using the same fixtures. The composer rejects every provider ambiguity, catalogs retain deep immutable snapshots, and the runner transports only real immutable upstream/host evidence.

**Tech Stack:** Python 3.10+, `unittest`, JSON Schema 2020-12, TypeScript 6, AJV 8, Node.js 22.19+, immutable mappings and tuples.

## Global Constraints

- Preserve `CLI/host → provider → assembly → catalog/composer → exact implementations → runner → runtime/host services`.
- `dci.agent-runtime/v1`, `dci.package/v1`, and `dci.assembly/v1` remain closed contracts.
- Update canonical schema, Python validation, TypeScript validation, and shared valid/invalid fixtures together.
- IDs are canonical; contract arrays are sorted and unique.
- Composition fails closed on ambiguity, missing edges, and cycles.
- Do not add prompts, credentials, commands, executable paths, environment values, provider configuration, or mutable state to manifests.
- Use `unittest`, `TestCase` subclasses, `test_<behavior>` methods, and `subTest` matrices.
- Provider-free commands must remain provider-free.

---

## File Structure

- `schemas/agent-runtime/v1/*.schema.json` — canonical runtime wire shape.
- `src/asterion/runtime/protocol.py` — Python runtime semantic validation.
- `packages/typescript/asterion-runtime/src/validation.ts` — TypeScript semantic validation and immutable return values.
- `tests/fixtures/agent_runtime/v1/` — shared cross-language runtime examples.
- `tests/test_runtime_protocol.py` — Python shared-fixture and lifecycle tests.
- `src/asterion/packages/composition.py` — fail-closed provider graph.
- `tests/test_package_composition.py` — direct graph ambiguity and ordering matrix.
- `src/asterion/packages/catalog.py` — deep immutable discovered manifests.
- `tests/test_package_catalog.py` — snapshot, root, and exact-selection behavior.
- `src/asterion/packages/execution.py` — invocation/result output semantics.
- `src/asterion/runner/composed.py` — real upstream/host evidence transport and global artifact identity.
- `src/asterion/assembly/protocol.py` — resolved host event/artifact declarations.
- `tests/test_package_execution.py` — result and composed-runner behavior.
- `src/asterion/capabilities/dci_research/manifests/*.json` and
  `src/asterion/applications/dci_agent_lite/assemblies/*.json` — remove fictional
  runtime-internal edges.

### Task 1: Canonical runtime identities and arrays

**Files:**
- Modify: `schemas/agent-runtime/v1/runtime-manifest.schema.json`
- Modify: `schemas/agent-runtime/v1/run-request.schema.json`
- Modify: `schemas/agent-runtime/v1/event.schema.json`
- Modify: `src/asterion/runtime/protocol.py`
- Modify: `packages/typescript/asterion-runtime/src/validation.ts`
- Create: `tests/fixtures/agent_runtime/v1/invalid-noncanonical-runtime-id.json`
- Create: `tests/fixtures/agent_runtime/v1/invalid-unsorted-runtime-capabilities.json`
- Create: `tests/fixtures/agent_runtime/v1/invalid-unsorted-request-capabilities.json`
- Create: `tests/fixtures/agent_runtime/v1/invalid-unsorted-started-capabilities.jsonl`
- Create: `tests/test_runtime_protocol.py`
- Modify: `packages/typescript/asterion-runtime/test/runtime.test.mjs`

**Interfaces:**
- Consumes: `dci.agent-runtime/v1` JSON values.
- Produces: Python and TypeScript validators that accept the same canonical values and reject the same invalid fixtures.

- [ ] **Step 1: Add shared invalid fixtures**

Use this exact runtime ID in `invalid-noncanonical-runtime-id.json`:

```json
{
  "protocol": "dci.agent-runtime/v1",
  "runtime_id": "../runtime",
  "capabilities": ["filesystem.read"]
}
```

Use `["z.capability", "a.capability"]` as the unsorted capability array in the
other three fixtures. The request fixture must otherwise be a valid request;
the JSONL fixture must contain a valid `run.started` followed by a valid
`run.completed` with contiguous sequences.

- [ ] **Step 2: Write Python fixture tests and verify failure**

Create `tests/test_runtime_protocol.py` with loaders for `.json` and `.jsonl`,
then add:

```python
class TestRuntimeProtocol(unittest.TestCase):
    def test_rejects_shared_invalid_runtime_manifests(self) -> None:
        for name in (
            "invalid-runtime-manifest.json",
            "invalid-noncanonical-runtime-id.json",
            "invalid-unsorted-runtime-capabilities.json",
        ):
            with self.subTest(name=name), self.assertRaises(ProtocolError):
                validate_runtime_manifest(_json(name))

    def test_rejects_unsorted_request_capabilities(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_run_request(_json("invalid-unsorted-request-capabilities.json"))

    def test_rejects_unsorted_started_capabilities(self) -> None:
        with self.assertRaises(ProtocolError):
            validate_event_stream(_jsonl("invalid-unsorted-started-capabilities.jsonl"))
```

Run:

```bash
uv run python -m unittest -v tests.test_runtime_protocol
```

Expected: the four new fixture cases fail because runtime validation currently
checks uniqueness but not canonical grammar or sorting.

- [ ] **Step 3: Implement Python canonical validation**

In `src/asterion/runtime/protocol.py`, add:

```python
IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")

def _require_identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ProtocolError(f"{label} is invalid")
    return value

def _validate_string_list(value: object, label: str) -> None:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or IDENTIFIER.fullmatch(item) is None for item in value)
        or value != sorted(set(value))
    ):
        raise ProtocolError(f"{label} must be a sorted unique identifier array")
```

Use `_require_identifier()` for `runtime_id` and retain the stronger helper for
runtime capabilities, requested capabilities, and `run.started` capabilities.
Do not apply identifier grammar to free-form `run_id`, tool names, artifact
IDs, messages, URIs, or media types.

- [ ] **Step 4: Tighten the runtime manifest schema**

Change `runtime_id` in
`schemas/agent-runtime/v1/runtime-manifest.schema.json` to:

```json
{
  "type": "string",
  "pattern": "^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$"
}
```

Give all three capability-array item schemas the same pattern. Keep
`uniqueItems: true`; sorting stays a semantic-validator requirement because
JSON Schema does not define lexical array order.

- [ ] **Step 5: Add TypeScript sorted-array validation**

In `validation.ts`, add:

```typescript
function requireSortedUnique(
  label: string,
  values: readonly string[],
): void {
  if (values.some((value, index) => index > 0 && values[index - 1]! >= value)) {
    throw new ProtocolValidationError(label, null);
  }
}
```

Call it for runtime manifest capabilities, optional request capabilities, and
`run.started` capabilities after AJV validation. Extend
`runtime.test.mjs` to load and reject the same four fixtures.

- [ ] **Step 6: Run both protocol suites**

```bash
uv run python -m unittest -v tests.test_runtime_protocol
npm --prefix packages/typescript/asterion-runtime test
```

Expected: all tests pass and both languages reject the same fixtures.

- [ ] **Step 7: Commit**

```bash
git add schemas/agent-runtime/v1 src/asterion/runtime/protocol.py \
  packages/typescript/asterion-runtime/src/validation.ts \
  packages/typescript/asterion-runtime/test/runtime.test.mjs \
  tests/fixtures/agent_runtime/v1 tests/test_runtime_protocol.py
git commit -m "fix: enforce canonical runtime protocol values"
```

### Task 2: Complete runtime lifecycle matching

**Files:**
- Modify: `src/asterion/runtime/protocol.py`
- Modify: `packages/typescript/asterion-runtime/src/validation.ts`
- Create: `tests/fixtures/agent_runtime/v1/invalid-unmatched-tool-call-at-terminal.jsonl`
- Modify: `tests/test_runtime_protocol.py`
- Modify: `packages/typescript/asterion-runtime/test/runtime.test.mjs`

**Interfaces:**
- Consumes: complete runtime event streams.
- Produces: one-to-one tool call/result validation before terminal completion.

- [ ] **Step 1: Add the unmatched-call fixture**

Create a three-event stream:

```json
{"protocol":"dci.agent-runtime/v1","run_id":"unmatched-call","sequence":1,"type":"run.started","payload":{"capabilities":["filesystem.read"]}}
{"protocol":"dci.agent-runtime/v1","run_id":"unmatched-call","sequence":2,"type":"tool.call","payload":{"call_id":"call-1","name":"read","arguments":{"path":"doc.txt"}}}
{"protocol":"dci.agent-runtime/v1","run_id":"unmatched-call","sequence":3,"type":"run.completed","payload":{"status":"completed"}}
```

- [ ] **Step 2: Add Python and TypeScript failing assertions**

Add the fixture to each language's invalid stream matrix. Run both suites and
expect this fixture to be accepted before the implementation change.

- [ ] **Step 3: Enforce complete matching**

At the end of both stream validators, after checking the terminal event, add
the equivalent of:

```python
if calls != results:
    raise ProtocolError("every tool.call must have exactly one tool.result")
```

```typescript
if (calls.size !== results.size) {
  throw new ProtocolValidationError("event stream unmatched tool.call", null);
}
```

Existing checks already reject results without calls and duplicate calls or
results, so set equality completes the invariant.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v tests.test_runtime_protocol
npm --prefix packages/typescript/asterion-runtime test
git add src/asterion/runtime/protocol.py \
  packages/typescript/asterion-runtime/src/validation.ts \
  packages/typescript/asterion-runtime/test/runtime.test.mjs \
  tests/fixtures/agent_runtime/v1/invalid-unmatched-tool-call-at-terminal.jsonl \
  tests/test_runtime_protocol.py
git commit -m "fix: require results for every runtime tool call"
```

Expected: both suites pass.

### Task 3: Immutable TypeScript validation results

**Files:**
- Modify: `packages/typescript/asterion-runtime/src/validation.ts`
- Modify: `packages/typescript/asterion-runtime/test/runtime.test.mjs`

**Interfaces:**
- Consumes: JSON-compatible validated values.
- Produces: deeply frozen snapshots whose nested arrays and objects cannot be mutated through the caller's original value.

- [ ] **Step 1: Write the mutation test**

Add:

```javascript
test("returns a deep immutable validation snapshot", async () => {
  const source = await readJson("valid-runtime-manifest.json");
  const validated = validateRuntimeManifest(source);
  source.capabilities.push("z.changed");
  assert.deepEqual(validated.capabilities, ["filesystem.read", "shell.execute"]);
  assert.ok(Object.isFrozen(validated));
  assert.ok(Object.isFrozen(validated.capabilities));
  assert.throws(() => validated.capabilities.push("z.changed"), TypeError);
});
```

Use the exact capabilities present in the fixture if they differ from the
example. Run `npm test` and expect failure because `requireValid()` returns the
original object.

- [ ] **Step 2: Implement snapshot freezing**

Add:

```typescript
function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object") {
    for (const child of Object.values(value as Record<string, unknown>)) {
      deepFreeze(child);
    }
    Object.freeze(value);
  }
  return value;
}

function immutableSnapshot<T>(value: T): T {
  return deepFreeze(structuredClone(value));
}
```

Make `requireValid()` return `immutableSnapshot(value as T)` only after AJV
success. Semantic validators must operate on and return this snapshot.

- [ ] **Step 3: Run and commit**

```bash
npm --prefix packages/typescript/asterion-runtime test
git add packages/typescript/asterion-runtime/src/validation.ts \
  packages/typescript/asterion-runtime/test/runtime.test.mjs
git commit -m "fix: return immutable TypeScript protocol snapshots"
```

Expected: all TypeScript tests pass.

### Task 4: Reject every composition provider ambiguity

**Files:**
- Modify: `src/asterion/packages/composition.py`
- Create: `tests/test_package_composition.py`

**Interfaces:**
- Consumes: validated package manifests plus host/runtime-provided edge sets.
- Produces: one deterministic graph with exactly one provider per consumed capability, policy, event, or artifact edge.

- [ ] **Step 1: Write a direct ambiguity matrix**

Create a manifest builder and a `subTest` matrix covering:

```python
cases = (
    ("duplicate-capability-package", manifests_with_two_capability_providers, {}),
    ("duplicate-event-package", manifests_with_two_event_providers, {}),
    ("duplicate-artifact-package", manifests_with_two_artifact_providers, {}),
    ("host-package-capability", manifests_with_capability_provider, {"host_capabilities": frozenset({"shared.cap"})}),
    ("host-package-policy", manifests_with_policy_provider, {"host_policies": frozenset({"policy.shared"})}),
    ("host-package-event", manifests_with_event_provider, {"host_events": frozenset({"shared.event"})}),
    ("host-package-artifact", manifests_with_artifact_provider, {"host_artifacts": frozenset({"text/plain"})}),
)
```

For every case:

```python
with self.subTest(name=name), self.assertRaises(PackageCompositionError):
    compose_packages(manifests, **kwargs)
```

Also preserve success tests for a single package provider, a single host
provider, stable input-order independence, missing edges, and cycles.

- [ ] **Step 2: Run to verify the new matrix fails**

```bash
uv run python -m unittest -v tests.test_package_composition
```

Expected: event, artifact, and host/package overlap cases fail because the
composer currently accepts them.

- [ ] **Step 3: Implement one-provider maps**

Replace set-valued event/artifact provider maps with one-provider maps and use
one helper:

```python
def _bind_provider(
    providers: dict[str, str],
    edge: str,
    package_id: str,
    *,
    label: str,
) -> None:
    if edge in providers:
        raise PackageCompositionError(f"{label} provider is ambiguous")
    providers[edge] = package_id
```

Before building dependencies, reject intersections between each package
provider-key set and the corresponding host set. Treat runtime capabilities as
part of `host_capabilities`, as `resolve_assembly()` does today.

For one event/artifact consumer, add only the single selected provider to its
dependencies.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v tests.test_package_composition
uv run python -m unittest -v tests.test_package_execution
git add src/asterion/packages/composition.py tests/test_package_composition.py
git commit -m "fix: reject ambiguous package graph providers"
```

Expected: both suites pass.

### Task 5: Deeply immutable package catalogs

**Files:**
- Modify: `src/asterion/packages/catalog.py`
- Create: `tests/test_package_catalog.py`

**Interfaces:**
- Consumes: validated direct JSON children under explicit local roots.
- Produces: immutable catalog entries and fresh mutable selections that cannot affect the stored snapshot.

- [ ] **Step 1: Write mutation and discovery tests**

Use `tempfile.TemporaryDirectory` and create fixtures in `setUp`. Cover:

```python
def test_entry_manifest_is_deeply_immutable(self) -> None:
    catalog = discover_packages((self.root,))
    entry = catalog.entries[0]
    with self.assertRaises(TypeError):
        entry.manifest["kind"] = "policy"
    with self.assertRaises(AttributeError):
        entry.manifest["provides_capabilities"].append("changed")

def test_selected_manifest_is_fresh(self) -> None:
    catalog = discover_packages((self.root,))
    first = catalog.select((catalog.entries[0].ref,))[0]
    first["kind"] = "policy"
    second = catalog.select((catalog.entries[0].ref,))[0]
    self.assertEqual(second["kind"], "capability")
```

Also cover duplicate roots, symlink roots/documents, duplicate identities,
unknown exact refs, duplicate selection, and stable source ordering.

- [ ] **Step 2: Run and expect the entry mutation test to fail**

```bash
uv run python -m unittest -v tests.test_package_catalog
```

- [ ] **Step 3: Freeze stored manifests**

Add recursive mapping/sequence freezing:

```python
def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
```

Store `_freeze(manifest)` in each `CatalogEntry`. Keep `select()` returning a
fresh thawed JSON-shaped dictionary; implement `_thaw()` rather than calling
`deepcopy()` on `MappingProxyType`.

- [ ] **Step 4: Run and commit**

```bash
uv run python -m unittest -v tests.test_package_catalog
uv run python -m unittest -v tests.test_package_execution
git add src/asterion/packages/catalog.py tests/test_package_catalog.py
git commit -m "fix: freeze discovered package manifests"
```

Expected: both suites pass.

### Task 6: Transport real upstream and host evidence

**Files:**
- Modify: `src/asterion/assembly/protocol.py`
- Modify: `src/asterion/packages/execution.py`
- Modify: `src/asterion/runner/composed.py`
- Modify: `tests/test_package_execution.py`

**Interfaces:**
- Consumes: resolved host event/artifact declarations plus actual immutable host values.
- Produces: `PackageInvocation.upstream_events`, `upstream_artifacts`, `host_events`, and `host_artifacts`, all deeply immutable.

- [ ] **Step 1: Write runner data-flow tests**

Add recording implementations for a producer and consumer. Assert:

```python
self.assertEqual(
    tuple(event["type"] for event in consumer.invocation.upstream_events),
    ("producer.completed",),
)
self.assertEqual(
    tuple(item["artifact_id"] for item in consumer.invocation.upstream_artifacts),
    ("producer-artifact",),
)
self.assertEqual(
    tuple(event["type"] for event in consumer.invocation.host_events),
    ("host.ready",),
)
self.assertEqual(
    tuple(item["artifact_id"] for item in consumer.invocation.host_artifacts),
    ("host-input",),
)
```

Attempt nested mutations and assert `TypeError` or `AttributeError`. Add
preflight failures for undeclared host values, missing declared host values,
and duplicate application-wide artifact IDs.

- [ ] **Step 2: Extend the resolved plan and invocation**

Add to `AssemblyPlan`:

```python
host_events: tuple[str, ...]
host_artifacts: tuple[str, ...]
```

Add to `PackageInvocation`:

```python
upstream_events: tuple[Mapping[str, object], ...]
host_events: tuple[Mapping[str, object], ...]
host_artifacts: tuple[Mapping[str, object], ...]
```

Freeze all four collections recursively in `__post_init__`.

- [ ] **Step 3: Extend the composed runner**

Add keyword-only inputs:

```python
host_events: tuple[Mapping[str, object], ...] = ()
host_artifacts: tuple[Mapping[str, object], ...] = ()
```

Preflight exact event types and artifact media types against the resolved
assembly declarations. For each package, filter accumulated package events,
accumulated artifacts, host events, and host artifacts against its declared
consumption arrays.

Maintain one `artifact_ids` set across all package results and reject an ID
before appending it when it has already appeared.

- [ ] **Step 4: Preserve v1 output-cardinality semantics**

Add direct tests proving that v1 declarations are allowed output types:

```python
validate_package_result(manifest, PackageExecutionResult(events=(), artifacts=()))
```

Also retain tests that reject undeclared event/media types, malformed values,
and duplicate artifact IDs inside one package result. Do not add cardinality
fields to a v1 manifest.

- [ ] **Step 5: Run and commit**

```bash
uv run python -m unittest -v tests.test_package_execution
git add src/asterion/assembly/protocol.py src/asterion/packages/execution.py \
  src/asterion/runner/composed.py tests/test_package_execution.py
git commit -m "feat: transport immutable package evidence"
```

Expected: the package execution suite passes.

### Task 7: Remove fictional product host edges

**Files:**
- Modify: `src/asterion/capabilities/dci_research/manifests/dci-research.json`
- Modify: `src/asterion/capabilities/controlled_code/manifests/code-quality-workflow.json`
- Modify: `src/asterion/capabilities/controlled_code/manifests/execution-audit-observability.json`
- Modify: `src/asterion/applications/dci_agent_lite/assemblies/dci-research-capability.json`
- Modify: `src/asterion/applications/dci_agent_lite/assemblies/dci-research-capability-claude.json`
- Modify: `src/asterion/applications/dci_agent_lite/assemblies/dci-complete-application-pi.json`
- Modify: `src/asterion/applications/dci_agent_lite/assemblies/dci-complete-application-claude.json`
- Modify: `src/asterion/applications/dci_agent_lite/assemblies/dci-local-research.json`
- Modify: `src/asterion/applications/controlled_code/assemblies/controlled-code-validation.json`
- Modify: `tests/test_dci_complete_application.py`
- Modify: `tests/test_controlled_code_application.py`
- Modify: `tests/test_package_execution.py`

**Interfaces:**
- Consumes: package input text as the direct research request; runtime events remain internal to the research implementation.
- Produces: product graphs whose declared host edges correspond to actual runner inputs.

- [ ] **Step 1: Write the declaration assertions**

Assert for every DCI assembly:

```python
self.assertEqual(assembly["host_events"], [])
self.assertEqual(assembly["host_artifacts"], [])
```

Assert for `dci.research`:

```python
self.assertEqual(manifest["consumes_events"], [])
self.assertEqual(manifest["consumes_artifacts"], [])
```

Assert for the controlled-code graph:

```python
self.assertEqual(workflow["consumes_events"], [])
self.assertEqual(workflow["consumes_artifacts"], [])
self.assertEqual(audit["consumes_events"], ["workflow.code-quality.completed"])
self.assertEqual(
    audit["consumes_artifacts"],
    ["application/vnd.dci.code-quality-report+json"],
)
self.assertEqual(assembly["host_events"], [])
self.assertEqual(assembly["host_artifacts"], [])
```

Run the focused tests and expect failure.

- [ ] **Step 2: Correct the manifests**

Remove `run.started` and `tool.result` from the research package's
`consumes_events`, and remove `text/plain` from `consumes_artifacts`. Clear the
matching `host_events` and `host_artifacts` in all DCI assemblies.

Also remove the controlled-code workflow's fictional `run.started`,
`tool.result`, and `text/x-source` host inputs. The audit package keeps only
the real workflow completion event and typed report artifact. Clear matching
host events/artifacts from the controlled-code assembly. Keep real
package-to-package completion events and typed artifacts unchanged in both
product graphs.

- [ ] **Step 3: Run promotion-sensitive tests**

```bash
uv run python -m unittest -v \
  tests.test_package_execution \
  tests.test_dci_complete_application \
  tests.test_controlled_code_application \
  tests.test_installed_application_provider
make promotion-check
```

Expected: all commands pass without provider requests.

- [ ] **Step 4: Commit**

```bash
git add src/asterion/capabilities/dci_research/manifests/dci-research.json \
  src/asterion/capabilities/controlled_code/manifests \
  src/asterion/applications/dci_agent_lite/assemblies \
  src/asterion/applications/controlled_code/assemblies \
  tests/test_dci_complete_application.py tests/test_controlled_code_application.py \
  tests/test_package_execution.py
git commit -m "fix: align product assembly edges with runtime data flow"
```

### Task 8: Protocol gate and documentation

**Files:**
- Modify: `docs/architecture/composable-packages.md`
- Modify: `docs/architecture/application-runner.md`
- Modify: `docs/architecture/capability-execution.md`
- Modify: `docs/architecture/dci-capability-audit.md`

**Interfaces:**
- Consumes: completed Tasks 1–7.
- Produces: public v1 semantics and named verification evidence.

- [ ] **Step 1: Document exact semantics**

Document canonical identifiers/arrays, matched tool lifecycle, one-provider
composition, immutable snapshots, real evidence transport, global artifact ID
uniqueness, and allowed-output cardinality. State explicitly that richer
artifact identity/cardinality declarations require a future protocol version.
Record that the repository-wide `make test` and `make check` gates are deferred
to the application-authority plan, which owns the current unrelated generic
CLI `.env` isolation and CI Node-version corrections.

- [ ] **Step 2: Run the focused provider-free gate**

```bash
uv run python -m unittest -v \
  tests.test_runtime_protocol \
  tests.test_package_composition \
  tests.test_package_catalog \
  tests.test_package_execution \
  tests.test_dci_complete_application \
  tests.test_dci_research_capability \
  tests.test_controlled_code_application
npm --prefix packages/typescript/asterion-runtime test
make lint
make docs-check
make promotion-check
```

Expected: every listed command passes. Do not claim that the broader
`make test` or `make check` gate passes until the application-authority plan
has corrected and rerun those repository-wide boundaries.

- [ ] **Step 3: Commit**

```bash
git add docs/architecture/composable-packages.md \
  docs/architecture/application-runner.md \
  docs/architecture/capability-execution.md \
  docs/architecture/dci-capability-audit.md
git commit -m "docs: define hardened v1 package semantics"
```
