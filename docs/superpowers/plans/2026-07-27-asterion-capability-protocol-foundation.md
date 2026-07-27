# Asterion Capability Protocol Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the generic DCI-named contracts with the complete Asterion protocol family and migrate every built-in declaration and cross-language validator atomically.

**Architecture:** Canonical schemas remain the source of truth. Python and TypeScript validators consume the same closed contracts and fixtures. Individual composable units become capabilities; a separate capability-package descriptor owns their portable closure.

**Tech Stack:** JSON Schema Draft 2020-12, Python dataclasses and `unittest`, TypeScript strict mode, Node test runner.

## Global Constraints

- Delete old protocol identifiers; do not accept aliases.
- Every schema is closed with `additionalProperties: false`.
- Identifiers and exact semantic versions retain current canonical patterns.
- Arrays are sorted by Unicode scalar value, unique, and immutable after validation.
- Manifest errors remain body-free and do not echo unknown keys or values.
- No provider, Agent, Judge, download, setup, or full dataset work.

## File structure

- `schemas/agent-runtime/v1/`: canonical `asterion.agent-runtime/v1` schemas.
- `schemas/capabilities/v1/capability-manifest.schema.json`: one composable capability.
- `schemas/capability-packages/v1/capability-package.schema.json`: portable package closure.
- `schemas/application-assembly/v1/application-assembly.schema.json`: application composition.
- `schemas/benchmark-suite/v1/benchmark-suite.schema.json`: generic suite metadata.
- `schemas/capability-source/v1/{source,lock}.schema.json`: operator source and lock documents.
- `src/asterion/capabilities/{protocol,catalog,composition,execution}.py`: generic capability core replacing `src/asterion/packages/`.
- `src/asterion/capability_packages/protocol.py`: package, suite, source, and lock immutable values.
- `src/asterion/assembly/protocol.py`: application assembly validation.
- `packages/typescript/asterion-runtime/src/`: exact cross-language types and validators.

---

### Task 1: Hard-rename the runtime protocol

**Files:**
- Modify: `schemas/agent-runtime/v1/runtime-manifest.schema.json`
- Modify: `schemas/agent-runtime/v1/run-request.schema.json`
- Modify: `schemas/agent-runtime/v1/event.schema.json`
- Modify: `src/asterion/runtime/protocol.py`
- Modify: `packages/typescript/asterion-runtime/src/types.ts`
- Modify: `packages/typescript/asterion-runtime/src/validation.ts`
- Modify: `packages/typescript/asterion-runtime/test/type-contract.ts`
- Modify: `packages/typescript/asterion-runtime/test/runtime.test.mjs`
- Modify: `tests/fixtures/agent_runtime/v1/*`
- Modify: `tests/test_runtime_protocol.py`

**Interfaces:**
- Produces: `RUNTIME_PROTOCOL_VERSION = "asterion.agent-runtime/v1"` in Python and TypeScript.
- Consumes: existing closed runtime request/event semantics unchanged except protocol identity.

- [ ] **Step 1: Write the failing absence and exact-identity tests**

Add to `tests/test_runtime_protocol.py`:

```python
def test_runtime_protocol_is_asterion_owned(self) -> None:
    self.assertEqual(RUNTIME_PROTOCOL_VERSION, "asterion.agent-runtime/v1")
    for path in (PROJECT / "schemas/agent-runtime/v1").glob("*.json"):
        self.assertNotIn("dci.agent-runtime/v1", path.read_text(encoding="utf-8"))
```

Add a Node assertion:

```js
assert.equal(RUNTIME_PROTOCOL_VERSION, "asterion.agent-runtime/v1");
```

- [ ] **Step 2: Run the tests and observe the old identifier**

Run:

```bash
uv run python -m unittest -v tests.test_runtime_protocol
npm test --prefix packages/typescript/asterion-runtime
```

Expected: both fail because the current constant is `dci.agent-runtime/v1`.

- [ ] **Step 3: Replace the protocol identity in all runtime contracts**

Use exactly:

```python
RUNTIME_PROTOCOL_VERSION = "asterion.agent-runtime/v1"
```

and:

```ts
export const RUNTIME_PROTOCOL_VERSION = "asterion.agent-runtime/v1" as const;
```

Update all valid fixtures to the new value. Keep invalid fixtures invalid for
their named reason; do not make protocol mismatch an accidental second reason.

- [ ] **Step 4: Verify runtime contracts**

Run:

```bash
uv run python -m unittest -v tests.test_runtime_protocol tests.test_runtime_adapter_redaction
npm test --prefix packages/typescript/asterion-runtime
```

Expected: PASS with no `dci.agent-runtime/v1` match below runtime schemas,
fixtures, Python, or TypeScript.

- [ ] **Step 5: Commit**

```bash
git add schemas/agent-runtime src/asterion/runtime packages/typescript/asterion-runtime tests/fixtures/agent_runtime tests/test_runtime_protocol.py tests/test_runtime_adapter_redaction.py
git commit -m "refactor: rename Asterion runtime protocol"
```

### Task 2: Replace package terminology with capability terminology

**Files:**
- Create: `schemas/capabilities/v1/capability-manifest.schema.json`
- Create: `src/asterion/capabilities/protocol.py`
- Create: `src/asterion/capabilities/catalog.py`
- Create: `src/asterion/capabilities/composition.py`
- Create: `src/asterion/capabilities/execution.py`
- Modify: `src/asterion/capabilities/__init__.py`
- Delete: `schemas/packages/v1/package-manifest.schema.json`
- Delete: `src/asterion/packages/protocol.py`
- Delete: `src/asterion/packages/catalog.py`
- Delete: `src/asterion/packages/composition.py`
- Delete: `src/asterion/packages/execution.py`
- Delete: `src/asterion/packages/__init__.py`
- Move: `tests/fixtures/packages/v1/*` to `tests/fixtures/capabilities/v1/*`
- Rename tests: `tests/test_package_{catalog,composition,execution}.py` to `tests/test_capability_{catalog,composition,execution}.py`
- Modify: all Python imports of `asterion.packages`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, order=True, slots=True)
class CapabilityRef:
    capability_id: str
    version: str

def validate_capability_manifest(value: object) -> Mapping[str, object]: ...
```

- Produces renamed immutable values:
  `CapabilityInvocation`, `CapabilityExecutionResult`,
  `CapabilityExecutionError`, `CapabilityCatalog`, and
  `CapabilityImplementationBinding`.

- [ ] **Step 1: Add failing capability-protocol fixtures and tests**

Create `tests/fixtures/capabilities/v1/valid-capability.json` with:

```json
{
  "protocol": "asterion.capability/v1",
  "capability_id": "example.research",
  "version": "1.0.0",
  "kind": "research",
  "provides_capabilities": ["research.local"],
  "requires_capabilities": [],
  "requires_policies": [],
  "emits_events": ["research.completed"],
  "consumes_events": [],
  "produces_artifacts": ["application/vnd.example.research+json"],
  "consumes_artifacts": []
}
```

Add tests asserting `package_id` and protocol `dci.package/v1` are rejected.

- [ ] **Step 2: Run the new tests and observe missing modules/schema**

Run:

```bash
uv run python -m unittest -v tests.test_capability_catalog tests.test_capability_composition tests.test_capability_execution
```

Expected: import/schema failure before implementation.

- [ ] **Step 3: Implement the closed capability protocol and rename the core**

The canonical identity check is:

```python
CAPABILITY_PROTOCOL_VERSION = "asterion.capability/v1"

if value.get("protocol") != CAPABILITY_PROTOCOL_VERSION:
    raise CapabilityProtocolError("capability protocol is invalid")
```

The exact reference is:

```python
@dataclass(frozen=True, order=True, slots=True)
class CapabilityRef:
    capability_id: str
    version: str

    @property
    def selector(self) -> str:
        return f"{self.capability_id}@{self.version}"
```

Apply this mechanical rename matrix repository-wide:

```text
PackageRef -> CapabilityRef
PackageInvocation -> CapabilityInvocation
PackageExecutionResult -> CapabilityExecutionResult
PackageExecutionError -> CapabilityExecutionError
PackageCatalog -> CapabilityCatalog
package_id -> capability_id (only for individual capability manifests/refs)
dci.package/v1 -> asterion.capability/v1
asterion.packages -> asterion.capabilities
```

Do not rename capability-package concepts introduced in later tasks.

- [ ] **Step 4: Verify the capability core and absence of the old core**

Run:

```bash
uv run python -m unittest -v tests.test_capability_catalog tests.test_capability_composition tests.test_capability_execution tests.test_project_boundary
test ! -d src/asterion/packages
test ! -d schemas/packages
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schemas/capabilities src/asterion/capabilities tests/fixtures/capabilities tests/test_capability_catalog.py tests/test_capability_composition.py tests/test_capability_execution.py src tests
git add -u schemas/packages src/asterion/packages tests/fixtures/packages tests/test_package_catalog.py tests/test_package_composition.py tests/test_package_execution.py
git commit -m "refactor: establish Asterion capability protocol"
```

### Task 3: Add portable capability-package protocol values and fixtures

**Files:**
- Create: `schemas/capability-packages/v1/capability-package.schema.json`
- Create: `src/asterion/capability_packages/__init__.py`
- Create: `src/asterion/capability_packages/protocol.py`
- Create: `tests/fixtures/capability_packages/v1/valid-minimal.json`
- Create: invalid fixtures for duplicate refs, unknown fields, unsorted refs, digest shape, and forbidden authority fields
- Create: `tests/test_capability_package_protocol.py`
- Create: `src/asterion/capabilities/controlled_code/capability-package.json`
- Create: `src/asterion/capabilities/dci_research/capability-package.json`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, order=True, slots=True)
class CapabilityPackageRef:
    package_id: str
    version: str

@dataclass(frozen=True, slots=True)
class CapabilityPackageManifest:
    package_ref: CapabilityPackageRef
    capabilities: tuple[CapabilityRef, ...]
    benchmark_suites: tuple["BenchmarkSuiteRef", ...]
    resources: tuple["ResourceIdentity", ...]
```

- [ ] **Step 1: Write failing closed-schema tests**

Test forbidden fields explicitly:

```python
for forbidden in ("command", "executable", "prompt", "credentials", "environment", "provider"):
    with self.subTest(forbidden=forbidden):
        with self.assertRaises(CapabilityPackageProtocolError):
            validate_capability_package_manifest({**VALID, forbidden: "SECRET"})
```

- [ ] **Step 2: Run and observe missing protocol**

Run:

```bash
uv run python -m unittest -v tests.test_capability_package_protocol
```

Expected: import failure.

- [ ] **Step 3: Implement the immutable values and validator**

Use:

```python
CAPABILITY_PACKAGE_PROTOCOL_VERSION = "asterion.capability-package/v1"

@dataclass(frozen=True, order=True, slots=True)
class ResourceIdentity:
    resource_id: str
    media_type: str
    sha256: str
```

Validate lowercase 64-character SHA-256 digests and exact sorted refs. The
payload digest itself is computed by the source layer and is not self-declared
inside `capability-package.json`.

- [ ] **Step 4: Add exact built-in descriptors**

Controlled code declares its four exact capability refs. DCI declares the
current seven exact capability/policy refs and an empty suite list until the
DCI migration plan adds suite manifests. Neither descriptor contains paths.

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_capability_package_protocol tests.test_builtin_controlled_code_application tests.test_dci_complete_application
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add schemas/capability-packages src/asterion/capability_packages src/asterion/capabilities/*/capability-package.json tests/fixtures/capability_packages tests/test_capability_package_protocol.py
git commit -m "feat: define portable capability package protocol"
```

### Task 4: Replace the assembly protocol and add exact package refs

**Files:**
- Create: `schemas/application-assembly/v1/application-assembly.schema.json`
- Delete: `schemas/assembly/v1/assembly.schema.json`
- Modify: `src/asterion/assembly/protocol.py`
- Move: `tests/fixtures/assembly/v1/*` to `tests/fixtures/application_assembly/v1/*`
- Modify: `tests/test_protocol_canonical_ordering.py`
- Modify: all JSON files below `src/asterion/applications/*/assemblies/`
- Modify: `packages/typescript/asterion-runtime/src/{types,validation}.ts`
- Modify: `packages/typescript/asterion-runtime/test/*`

**Interfaces:**
- Produces:

```python
APPLICATION_ASSEMBLY_PROTOCOL_VERSION = "asterion.application-assembly/v1"
```

- Assembly field:

```json
"capability_packages": [
  {"package_id": "dci", "version": "1.0.0"}
]
```

- Existing `packages` field becomes `capabilities` and uses
  `capability_id`/`version`.

- [ ] **Step 1: Write failing assembly identity and package-ref tests**

Require old `protocol`, `packages`, and `package_id` capability members to fail.
Require unsorted `capability_packages` to fail independently.

- [ ] **Step 2: Run tests and observe old schema behavior**

Run:

```bash
uv run python -m unittest -v tests.test_protocol_canonical_ordering tests.test_capability_composition tests.test_installed_application_provider
npm test --prefix packages/typescript/asterion-runtime
```

Expected: FAIL on new field/protocol expectations.

- [ ] **Step 3: Implement and migrate every built-in assembly**

Use exact protocol and field names:

```json
{
  "protocol": "asterion.application-assembly/v1",
  "application_id": "dci.complete-application",
  "version": "1.0.0",
  "runtime_id": "pi.reference",
  "capability_packages": [{"package_id": "dci", "version": "1.0.0"}],
  "capabilities": [{"capability_id": "dci.research", "version": "1.0.0"}]
}
```

Keep every existing host edge unchanged and canonically sorted.

- [ ] **Step 4: Verify Python and TypeScript agreement**

Run:

```bash
uv run python -m unittest -v tests.test_protocol_canonical_ordering tests.test_capability_composition tests.test_installed_application_provider tests.test_dci_complete_application
npm test --prefix packages/typescript/asterion-runtime
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schemas/application-assembly src/asterion/assembly src/asterion/applications tests/fixtures/application_assembly tests packages/typescript/asterion-runtime
git add -u schemas/assembly tests/fixtures/assembly
git commit -m "refactor: establish Asterion application assembly protocol"
```

### Task 5: Add benchmark-suite, source, and source-lock protocols

**Files:**
- Create: `schemas/benchmark-suite/v1/benchmark-suite.schema.json`
- Create: `schemas/capability-source/v1/source.schema.json`
- Create: `schemas/capability-source/v1/lock.schema.json`
- Modify: `src/asterion/capability_packages/protocol.py`
- Create: `tests/fixtures/benchmark_suite/v1/{valid-minimal,invalid-command,invalid-task-order}.json`
- Create: `tests/fixtures/capability_source/v1/{valid-source,valid-lock,invalid-private-public-field,invalid-duplicate-lock}.json`
- Create: `tests/test_benchmark_suite_protocol.py`
- Create: `tests/test_capability_source_protocol.py`
- Modify: TypeScript types, validation, and tests

**Interfaces:**
- Produces `BenchmarkSuiteRef`, `BenchmarkSuiteManifest`,
  `CapabilitySourceDeclaration`, and `CapabilitySourceLock`.

- [ ] **Step 1: Add failing fixtures for safe declarative boundaries**

The valid task shape is:

```json
{
  "task_id": "example.task",
  "capability": {"capability_id": "example.benchmark", "version": "1.0.0"},
  "binding_id": "example.task",
  "metric_contract_id": "example.metric/v1",
  "result_contract_id": "example.result/v1",
  "note": ""
}
```

Fixtures containing `command`, `dataset_path`, `corpus_path`, `provider`, or
`environment` must fail.

- [ ] **Step 2: Run tests and observe missing schemas**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_suite_protocol tests.test_capability_source_protocol
```

Expected: import/schema failure.

- [ ] **Step 3: Implement exact immutable values**

Use:

```python
@dataclass(frozen=True, order=True, slots=True)
class BenchmarkSuiteRef:
    suite_id: str
    version: str

@dataclass(frozen=True, slots=True)
class CapabilitySourceLockEntry:
    package_ref: CapabilityPackageRef
    payload_sha256: str
    source_id: str
```

Source declaration private locators stay in the operator value and have no
public projection beyond `source_id`, `kind`, exact package ref, and digest.

- [ ] **Step 4: Verify cross-language contracts**

Run:

```bash
uv run python -m unittest -v tests.test_benchmark_suite_protocol tests.test_capability_source_protocol
npm test --prefix packages/typescript/asterion-runtime
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schemas/benchmark-suite schemas/capability-source src/asterion/capability_packages tests/fixtures/benchmark_suite tests/fixtures/capability_source tests/test_benchmark_suite_protocol.py tests/test_capability_source_protocol.py packages/typescript/asterion-runtime
git commit -m "feat: add benchmark suite and capability source protocols"
```

### Task 6: Prove old protocol removal and full protocol coherence

**Files:**
- Modify: `tools/check_docs.py`
- Modify: `tools/check_promotion.py`
- Modify: `tests/test_project_boundary.py`
- Modify: `tests/test_standalone_repository.py`
- Modify: protocol documentation and TypeScript README

**Interfaces:**
- Consumes: all protocol constants and schemas from Tasks 1-5.
- Produces: repository-wide absence and installed-wheel protocol gates.

- [ ] **Step 1: Add a failing forbidden-identifier gate**

Add a test that scans identity-bearing source files:

```python
FORBIDDEN = (
    "dci.agent-runtime/v1",
    "dci.package/v1",
    "dci.assembly/v1",
)

for path in identity_files():
    text = path.read_text(encoding="utf-8")
    for value in FORBIDDEN:
        self.assertNotIn(value, text, path)
```

Exclude historical design and journal documents only; never exclude schemas,
fixtures, executable source, manifests, assemblies, or active user guides.

- [ ] **Step 2: Run and identify every remaining executable occurrence**

Run:

```bash
uv run python -m unittest -v tests.test_project_boundary tests.test_standalone_repository
rg -n 'dci\\.(agent-runtime|package|assembly)/v1' schemas src packages tests
```

Expected: test failure until all active occurrences are migrated.

- [ ] **Step 3: Correct remaining docs, examples, and build resources**

Use only the new protocol identifiers. Update copied schema paths in
`packages/typescript/asterion-runtime/scripts/copy-schemas.mjs` and built-wheel
resource assertions.

- [ ] **Step 4: Run the phase gate**

Run:

```bash
uv run python -m unittest discover -s tests -v
make check
make promotion-check
```

Expected: all exit `0`, provider operations `0`, full dataset `no`.

- [ ] **Step 5: Commit**

```bash
git add tools tests docs packages src schemas
git commit -m "test: enforce Asterion protocol ownership"
```
