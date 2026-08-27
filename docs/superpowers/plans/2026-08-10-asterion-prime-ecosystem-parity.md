# Asterion Prime Ecosystem Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all ten mandatory Prime 0.7.1 `ecosystem.capabilities` scenarios with an Asterion-owned sealed portfolio, four real-Prime provider-free evidence packages, and no model/provider execution.

**Architecture:** Python owns exact resource composition, collision rejection, private source resolution, materialization, authority, and evidence. TypeScript validates a closed private frame, durably fences lifecycle effects, and invokes only digest-locked Prime ecosystem modules. Prime loads the sealed portfolio as an exact implementation; it never discovers operator resources or becomes a composer.

**Tech Stack:** Python 3.12 dataclasses/protocols/unittest, existing Asterion capability-package source locks, no-follow filesystem operations, TypeScript 5/Node 22/node:test, pinned Prime Agent 0.7.1 modules, local MCP fixtures, Make, and the parity ledger/reducer.

## Global Constraints

- Preserve `CLI/host → selected provider → assembly → exact implementation → runner/runtime` dependency direction.
- Keep framework modules domain-neutral; only `control/providers/prime/` and `prime-gateway` may import or invoke Prime-specific implementations.
- Do not change any public v1 schema. The ecosystem frame is private and versioned.
- Catalogs accept explicit roots, exact direct children, and exact versions only. Do not add recursive discovery, ranges, registries, symlink traversal, or hidden precedence.
- Manifests and public values contain no resource bodies, prompts, credentials, executable paths, environment values, provider configuration, or private paths.
- Duplicate resource or registration identities reject the complete portfolio before Prime execution. Input order never chooses a winner.
- All ten scenarios are provider-free: zero model credential reads, zero provider operations, and zero retained owned processes.
- MCP launch and credential refresh are injected host services. The Gateway never starts, authorizes, or configures an MCP process.
- Package installation is limited to already approved local-directory or installed-distribution sources under an exact source lock; no network installation is permitted.
- Provider/model parity proves registration and exact lookup only. Never send a prompt or invoke the registered provider.
- Follow TDD with `unittest` and `node:test`; fake adapters and synthetic receipts never receive parity evidence IDs.
- `asterion.native` remains `missing`, and later interface/operations domains remain blocked.
- The injected private root is host-owned. Before rollback or close, the host must quiesce all projection consumers; no actor may retain a write-capable projection/descendant directory descriptor or mutate that namespace during cleanup. This is not an OS-sandbox guarantee against hostile same-UID concurrent mutation.
- Cleanup verifies held identities and fails closed on pre-cleanup drift. Missing/mismatched names retain ownership; tree removal and parent-fsync use an explicit retry-safe phase. Descriptor-close failures are terminal uncertainty and the same numeric descriptor is never retried.

---

### Task 1: Add closed provider-neutral ecosystem values and collision rejection

**Files:**
- Create: `src/asterion/control/ecosystem.py`
- Modify: `src/asterion/control/__init__.py`
- Create: `tests/test_control_ecosystem.py`

**Interfaces:**
- Consumes: `OPAQUE_ID` and canonical SHA-256 conventions from `asterion.control.protocol`.
- Produces: `EcosystemSourceRef`, `EcosystemResourceRef`, `EcosystemRegistrationRef`, `EcosystemCollision`, `EcosystemPortfolio`, `EcosystemActivationReceipt`, `EcosystemPrivateSourceStore`, `detect_ecosystem_collisions()`, and `build_ecosystem_portfolio()`.

- [ ] **Step 1: Write failing closed-value, immutability, and collision tests**

Add exact construction and rejection cases:

```python
class TestEcosystemPortfolio(unittest.TestCase):
    def test_portfolio_is_sorted_immutable_and_body_free(self) -> None:
        portfolio = build_ecosystem_portfolio(
            portfolio_id="portfolio-1",
            authority_id="authority-1",
            authority_revision=1,
            resources=(_resource("prompt-1", kind="prompt-template"),),
            registrations=(_registration("tool-1", kind="tool"),),
        )
        self.assertEqual(portfolio.resources[0].resource_id, "prompt-1")
        self.assertRegex(portfolio.digest, r"^[0-9a-f]{64}$")
        self.assertNotIn("SENTINEL_BODY", repr(portfolio))

    def test_collision_is_order_independent_and_rejects_before_activation(self) -> None:
        resources = (
            _resource("prompt-1", source_id="source-b"),
            _resource("prompt-1", source_id="source-a"),
        )
        forward = detect_ecosystem_collisions(resources, ())
        reverse = detect_ecosystem_collisions(tuple(reversed(resources)), ())
        self.assertEqual(forward, reverse)
        self.assertEqual(forward[0].source_ids, ("source-a", "source-b"))
        with self.assertRaisesRegex(EcosystemError, "portfolio has a collision"):
            build_ecosystem_portfolio(
                portfolio_id="portfolio-1",
                authority_id="authority-1",
                authority_revision=1,
                resources=resources,
                registrations=(),
            )
```

Cover all closed kinds, three scopes, duplicate source IDs, malformed versions/digests, booleans as integers, reordered arrays, registration ownership, named terminal constructors, recursively immutable public mappings, and sentinel-free `repr`/errors.

- [ ] **Step 2: Run the focused tests and observe the missing module**

Run: `uv run python -m unittest -v tests.test_control_ecosystem`

Expected: FAIL because `asterion.control.ecosystem` does not exist.

- [ ] **Step 3: Implement exact frozen values and canonical identities**

Use these closed literals and fields:

```python
EcosystemResourceKind = Literal[
    "context-file", "prompt-template", "markdown-skill", "python-skill",
    "extension", "package", "mcp-server",
]
EcosystemRegistrationKind = Literal["command", "tool", "provider-model"]
EcosystemSourceKind = Literal["local-child", "installed-distribution"]
EcosystemScope = Literal["session", "project", "global"]
EcosystemTerminalStatus = Literal["succeeded", "failed", "cancelled", "uncertain"]

@dataclass(frozen=True, repr=False)
class EcosystemSourceRef:
    source_id: str
    kind: EcosystemSourceKind
    version: str
    content_sha256: str

@dataclass(frozen=True, repr=False)
class EcosystemResourceRef:
    resource_id: str
    version: str
    kind: EcosystemResourceKind
    scope: EcosystemScope
    source: EcosystemSourceRef
    content_sha256: str

@dataclass(frozen=True)
class EcosystemRegistrationRef:
    registration_id: str
    kind: EcosystemRegistrationKind
    extension_id: str
    version: str

@dataclass(frozen=True)
class EcosystemCollision:
    kind: str
    logical_id: str
    source_ids: tuple[str, ...]
    reason_code: Literal["ecosystem-resource-collision"]
```

`EcosystemPortfolio` stores `portfolio_id`, `authority_id`, `authority_revision`, sorted `resources`, sorted `registrations`, and a computed `digest`. `EcosystemActivationReceipt` stores the portfolio digest, sorted feature IDs, terminal status, resource/registration/package/MCP/lifecycle counts, `provider_operations`, `model_credential_reads`, and `owned_process_count`; expose `.succeeded()`, `.failed()`, `.cancelled()`, and `.uncertain()` constructors.

Keep private lookup behind this exact protocol; implementations and locators are
introduced in Task 2:

```python
class EcosystemPrivateSourceStore(Protocol):
    def open_file(
        self,
        resource_id: str,
        relative_path: str,
    ) -> ContextManager[IO[bytes]]: ...
```

`detect_ecosystem_collisions()` groups resources by `(kind, scope, resource_id)` and registrations by `(kind, registration_id)`, sorts source/extension identities, and returns a canonical tuple. `build_ecosystem_portfolio()` copies all containers, rejects any collision, and hashes canonical sorted-key JSON.

- [ ] **Step 4: Export the public provider-neutral values and rerun tests**

Add the Task 1 names to `src/asterion/control/__init__.py` and `__all__`.

Run: `uv run python -m unittest -v tests.test_control_ecosystem tests.test_control_provider`

Expected: PASS with no sentinel or private locator in output.

- [ ] **Step 5: Commit the closed portfolio contract**

```bash
git add src/asterion/control/ecosystem.py src/asterion/control/__init__.py tests/test_control_ecosystem.py
git commit -m "feat: add sealed ecosystem portfolio contracts"
```

---

### Task 2: Add exact private source storage and atomic materialization

**Files:**
- Create: `src/asterion/control/ecosystem_materialization.py`
- Modify: `src/asterion/control/ecosystem.py`
- Create: `tests/test_control_ecosystem_materialization.py`

**Interfaces:**
- Consumes: Task 1 source/resource/portfolio values and a host-owned private root.
- Produces: `EcosystemPrivateFile`, `EcosystemPrivateResource`, `FileEcosystemPrivateSourceStore`, `EcosystemProjection`, and `SealedEcosystemMaterializer.materialize()` / `.close()`.

- [ ] **Step 1: Write failing no-follow, digest, race, and rollback tests**

Use an explicit private declaration rather than directory discovery:

```python
private = EcosystemPrivateResource(
    resource_id="python-skill-1",
    source_id="source-1",
    files=(
        EcosystemPrivateFile("SKILL.md", "a" * 64, 12),
        EcosystemPrivateFile("src/skill_one/__init__.py", "b" * 64, 20),
    ),
)
store = FileEcosystemPrivateSourceStore(
    roots={"source-1": source_root},
    resources=(private,),
)
projection = SealedEcosystemMaterializer(private_root).materialize(
    _portfolio_for(private), store
)
self.assertEqual(projection.portfolio_digest, _portfolio_for(private).digest)
self.assertEqual(stat.S_IMODE(projection.root.stat().st_mode), 0o700)
self.assertNotIn(str(source_root), repr(projection))
```

Add subtests for root/intermediate/final symlinks, FIFO/device/socket inputs, `..` and absolute child paths, undeclared files, wrong byte count, content digest drift, duplicate file paths, source replacement after open, partial copy failure, existing final projection, pre-cleanup projection-name drift, retry after post-removal parent-fsync failure, cleanup failure, and source/private sentinel redaction.

- [ ] **Step 2: Run tests and observe missing materialization types**

Run: `uv run python -m unittest -v tests.test_control_ecosystem_materialization`

Expected: FAIL on missing `asterion.control.ecosystem_materialization`.

- [ ] **Step 3: Implement explicit file declarations and held-descriptor copying**

Implement these exact private shapes:

```python
@dataclass(frozen=True)
class EcosystemPrivateFile:
    relative_path: str
    sha256: str
    size_bytes: int

@dataclass(frozen=True, repr=False)
class EcosystemPrivateResource:
    resource_id: str
    source_id: str
    files: tuple[EcosystemPrivateFile, ...]

@dataclass(frozen=True, repr=False)
class EcosystemProjection:
    projection_id: str
    portfolio_digest: str
    root: Path
    resource_roots: Mapping[str, Path]
```

`FileEcosystemPrivateSourceStore.open_file(resource_id, relative_path)` must open every root/path component with `O_NOFOLLOW`, require regular files, hold the final descriptor, verify the exact size and SHA-256 while reading at most the declared size plus one byte, and raise only `EcosystemMaterializationError("ecosystem source is invalid")` without chaining.

`SealedEcosystemMaterializer.materialize()` creates one mode-0700 staging directory under the injected private root, copies only declared files to mode 0600, fsyncs files/directories, validates the aggregate resource digest, atomically publishes a new direct-child projection, and returns immutable private paths with redacted `repr`. On any failure it removes only its owned staging inode after the host-owned namespace is quiescent. `.close()` runs only after projection consumers are quiescent, removes only the exact projection identity, and is idempotent. Missing or mismatched managed names fail with the fixed redacted error while retaining ownership. Record `bound`, `tree-removed-pending-fsync`, and `closed` phases so a post-removal parent-fsync failure retries fsync without retrying deletion. Treat descriptor-close failure as terminal uncertainty and never retry the same descriptor number.

- [ ] **Step 4: Run filesystem, package-source, and redaction regressions**

Run: `uv run python -m unittest -v tests.test_control_ecosystem_materialization tests.test_local_capability_source tests.test_distribution_capability_source tests.test_capability_package_model`

Expected: PASS; existing package source behavior remains exact and provider-free.

- [ ] **Step 5: Commit the sealed materializer**

```bash
git add src/asterion/control/ecosystem.py src/asterion/control/ecosystem_materialization.py tests/test_control_ecosystem_materialization.py
git commit -m "feat: materialize exact ecosystem resources"
```

---

### Task 3: Add selected-Prime ecosystem translation and host-service preflight

**Files:**
- Create: `src/asterion/control/providers/prime/ecosystem.py`
- Modify: `src/asterion/control/providers/prime/factory.py`
- Modify: `src/asterion/control/providers/prime/client.py`
- Modify: `src/asterion/control/providers/prime/process.py`
- Modify: `src/asterion/control/providers/prime/resources/control-plane.json`
- Create: `tests/test_prime_ecosystem_adapter.py`
- Modify: `tests/test_prime_control_factory.py`

**Interfaces:**
- Consumes: Task 1 portfolio/receipt, Task 2 projection/materializer, injected services `ecosystem-source-store`, `ecosystem-materializer`, and `mcp-credential-refresh`.
- Produces: `PrimeEcosystemClient.activate_ecosystem()`, `PrimeEcosystemService.activate()`, and factory capability `ecosystem.portfolio`.

- [ ] **Step 1: Write failing exact-frame and missing-service tests**

```python
class TestPrimeEcosystemService(unittest.TestCase):
    def test_activation_materializes_before_client_and_returns_body_free_receipt(self) -> None:
        client = RecordingPrimeEcosystemClient()
        receipt = PrimeEcosystemService(client, materializer, source_store).activate(
            portfolio, credential_refresh
        )
        self.assertEqual(receipt.status, "succeeded")
        self.assertEqual(receipt.provider_operations, 0)
        self.assertEqual(receipt.model_credential_reads, 0)
        self.assertNotIn("SENTINEL_BODY", repr(receipt))

    def test_factory_rejects_missing_ecosystem_service_before_process(self) -> None:
        with self.assertRaisesRegex(ControlPlaneFactoryError, "host service is unavailable"):
            create_prime_control_plane(_context(host_services={}))
        self.assertEqual(process_factory.calls, 0)
```

Cover exact feature/resource consistency, authority digest drift, client receipt drift, terminal uncertainty, materializer cleanup on every terminal path, omitted credential service, wrong protocol objects, and redacted service exceptions.

- [ ] **Step 2: Run focused tests and observe the missing adapter**

Run: `uv run python -m unittest -v tests.test_prime_ecosystem_adapter tests.test_prime_control_factory`

Expected: FAIL because the ecosystem adapter and capability binding do not exist.

- [ ] **Step 3: Implement the private translation and service boundary**

Define:

```python
class PrimeEcosystemClient(Protocol):
    async def activate_ecosystem(self, frame: Mapping[str, object]) -> Mapping[str, object]: ...

class McpCredentialRefresh(Protocol):
    def refresh(self, lease_id: str, challenge_digest: str) -> str: ...

class PrimeEcosystemService:
    async def activate(
        self,
        portfolio: EcosystemPortfolio,
        credential_refresh: McpCredentialRefresh,
    ) -> EcosystemActivationReceipt: ...
```

The private frame contains exact sorted resources/registrations, `portfolioDigest`, `authorityDigest`, private projection references, feature IDs, module/artifact locks, an opaque MCP credential lease ID, and fixed limits. Do not place file paths in `EcosystemActivationReceipt` or any exception. Validate the Gateway mapping against the exact portfolio digest/counts/status before constructing the named receipt.

The service is bound to the selected provider authority ID/revision and rejects a portfolio for any other authority before materialization or IPC. The factory requires the three services only when the selected manifest declares `ecosystem.portfolio`; reject missing/wrong services before creating the Prime process, then construct and retain the usable async ecosystem service instead of discarding the validated services. Extend the selected client and process transport with one private IPC request kind `ecosystem_activate`, exact response type `ecosystem_receipt`, and no public protocol field.

- [ ] **Step 4: Run adapter, factory, host, and sentinel tests**

Run: `uv run python -m unittest -v tests.test_prime_ecosystem_adapter tests.test_prime_control_factory tests.test_control_host tests.test_control_provider`

Expected: PASS with zero process calls on every preflight rejection.

- [ ] **Step 5: Commit the selected-provider binding**

```bash
git add src/asterion/control/providers/prime/ecosystem.py src/asterion/control/providers/prime/factory.py src/asterion/control/providers/prime/client.py src/asterion/control/providers/prime/resources/control-plane.json tests/test_prime_ecosystem_adapter.py tests/test_prime_control_factory.py
git commit -m "feat: bind sealed ecosystem to Prime"
```

---

### Task 4: Add the closed Gateway frame and durable lifecycle fence

**Files:**
- Create: `packages/typescript/prime-gateway/src/ecosystem.ts`
- Modify: `packages/typescript/prime-gateway/src/durable-store.ts`
- Modify: `packages/typescript/prime-gateway/src/gateway.ts`
- Modify: `packages/typescript/prime-gateway/src/index.ts`
- Modify: `packages/typescript/prime-gateway/src/main.ts`
- Create: `packages/typescript/prime-gateway/test/ecosystem.test.mjs`
- Modify: `packages/typescript/prime-gateway/test/gateway.test.mjs`
- Modify: `packages/typescript/prime-gateway/test/main.test.mjs`

**Interfaces:**
- Consumes: Task 3 `asterion.prime-ecosystem-frame/v1` and a pinned `PrimeEcosystemModule`.
- Produces: `validatePrimeEcosystemFrame()`, `PrimeEcosystemAdapter.activate()`, and durable bind/result methods keyed by effect ID.

- [ ] **Step 1: Write failing frame, bind-before-effect, and reopen tests**

```javascript
test("binds the exact ecosystem effect before Prime lifecycle", async () => {
  const store = new RecordingStore();
  const module = new RecordingPrimeModule(store);
  const result = await new PrimeEcosystemAdapter({ store, module }).activate(frame);
  assert.deepEqual(store.calls.slice(0, 2), ["bind", "module-start"]);
  assert.equal(result.status, "succeeded");
  assert.equal(result.providerOperations, 0);
});

test("reopen fences a bound nonterminal effect as uncertain", async () => {
  const reopened = new PrimeEcosystemAdapter({ store: reopen(boundStore), module: failModule });
  const result = await reopened.activate(frame);
  assert.equal(result.status, "uncertain");
  assert.equal(failModule.calls, 0);
});
```

Reject extra/missing keys, unsorted resources/registrations/features, duplicate IDs, unsafe integers, digest drift, paths outside the projection root, wrong modes, source/module/artifact drift, nonzero provider/model usage, lifecycle count drift, and content-bearing errors.

- [ ] **Step 2: Run Node tests and observe missing ecosystem exports**

Run: `npm --prefix packages/typescript/prime-gateway test -- test/ecosystem.test.mjs`

Expected: FAIL because `ecosystem.js` is absent.

- [ ] **Step 3: Implement the exact frame validator and adapter**

Use the private shape:

```typescript
export interface PrimeEcosystemFrame {
  readonly format: "asterion.prime-ecosystem-frame/v1";
  readonly effectId: string;
  readonly authorityDigest: string;
  readonly portfolioDigest: string;
  readonly features: readonly string[];
  readonly resources: readonly PrimeEcosystemResource[];
  readonly registrations: readonly PrimeEcosystemRegistration[];
  readonly projectionRoot: string;
  readonly artifactLockDigest: string;
  readonly moduleLockDigest: string;
  readonly mcpCredentialLeaseId: string;
  readonly limits: PrimeEcosystemLimits;
}
```

Validate exact keys, canonical arrays, byte/entry/process/deadline caps, owned canonical paths, exact mode 0600/0700 including rejection of special permission bits, and digest syntax before bind. Globally sort the complete file manifest by the same `relative_path` order as Python before hashing. Hash a public form that excludes paths and lease IDs. Add `bindEcosystemEffect()`, `commitEcosystemEffectResult()`, `ecosystemEffectBinding()`, and `ecosystemEffectResult()` to the durable store. Binding atomically returns created/pre-existing disposition and persists the safe expected feature/count contract; concurrent or reopened pre-existing nonterminal bindings become `uncertain` without module invocation. Every terminal commit/replay validates effect identity, frame/lock digests, features, and derived counts against that binding.

Extend the private main-process envelope with exact `ecosystem_activate` request and `ecosystem_receipt` response variants. Dispatch only through an injected `PrimeEcosystemAdapter`; Task 5 supplies the real digest-locked module dependency. Keep durable-only effect/frame/lock fields out of the IPC result and project exactly the twelve Task 3 receipt fields so Python rejects no valid response and accepts no extras.

- [ ] **Step 4: Build and run the complete Gateway package**

Run: `npm --prefix packages/typescript/prime-gateway test`

Expected: PASS; public errors and snapshots exclude projection paths, credential lease IDs, and sentinels.

- [ ] **Step 5: Commit the private Gateway boundary**

```bash
git add packages/typescript/prime-gateway/src/ecosystem.ts packages/typescript/prime-gateway/src/durable-store.ts packages/typescript/prime-gateway/src/gateway.ts packages/typescript/prime-gateway/src/index.ts packages/typescript/prime-gateway/test/ecosystem.test.mjs packages/typescript/prime-gateway/test/gateway.test.mjs
git commit -m "feat: fence Prime ecosystem activation"
```

---

### Task 5: Lock the exact Prime ecosystem module bundle and shared harness

**Files:**
- Create: `packages/typescript/prime-gateway/resources/prime-ecosystem-module-lock.json`
- Create: `packages/typescript/prime-gateway/resources/prime-ecosystem-module.mjs`
- Modify: `packages/typescript/prime-gateway/resources/prime-artifact-lock.json`
- Modify: `tools/setup_prime_agent.py`
- Modify: `tests/test_setup_prime_agent.py`
- Create: `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- Create: `tests/test_prime_ecosystem_real_process.py`

**Interfaces:**
- Consumes: pinned Prime commit `a18809e00ea30638584d87b3afea7285a9d7296c` and the Task 4 module interface.
- Produces: `resolve_prime_ecosystem_module()`, one digest-locked module bundle, and a shared real-process harness accepting only sealed fixture roots.

- [ ] **Step 1: Write failing module-lock and two-process determinism tests**

```python
def test_resolver_requires_exact_source_build_and_bundle_digests(self) -> None:
    resolved = resolve_prime_ecosystem_module(PINNED_SOURCE, LOCK)
    self.assertEqual(resolved.source_commit, PINNED_COMMIT)
    self.assertEqual(resolved.module_ids, EXPECTED_MODULE_IDS)
    with self.assertRaisesRegex(PrimeSetupError, "Prime ecosystem module is invalid"):
        resolve_prime_ecosystem_module(_tampered_source(), LOCK)

def test_real_harness_runs_twice_with_identical_public_digest(self) -> None:
    first = _run_real_harness()
    second = _run_real_harness()
    self.assertEqual(first["observation_digest"], second["observation_digest"])
    self.assertEqual(first["provider_operations"], 0)
    self.assertEqual(first["model_credential_reads"], 0)
    self.assertEqual(first["owned_process_count_after_close"], 0)
```

Also reject missing built modules, source/build drift, reordered lock arrays, symlinked modules, world-writable files, extra exports, raw observations on stdout, inherited model credentials, and unsealed roots.

- [ ] **Step 2: Run resolver and real-process tests and observe missing lock**

Run: `uv run python -m unittest -v tests.test_setup_prime_agent tests.test_prime_ecosystem_real_process`

Expected: FAIL because the ecosystem module lock/resolver is absent.

- [ ] **Step 3: Implement the lock, resolver, and module bundle**

The lock contains exactly `format`, `source_commit`, `artifact_lock_sha256`, `bundle_sha256`, and a sorted `modules` array of `{module_id, source_path, built_path, sha256}` for Prime resource loader, prompt templates, skills, extension loader/runner, package manager, MCP manager/OAuth, diagnostics, and model registry. The resolver verifies the pinned commit and every source/built/bundle digest without importing modules.

The Asterion-owned `.mjs` bundle imports only locked built paths and exports `inspectResources`, `runExtensionLifecycle`, `resolvePackage`, and `runMcpFixture`. Each function accepts a sealed frame, disables defaults/bundled discovery, returns a private observation, and exposes no executable path or provider invocation function.

- [ ] **Step 4: Implement the shared real-process fixture and rerun twice**

The fixture accepts only `--module-lock`, `--artifact-lock`, `--sealed-root`, and `--scenario-package`; it starts no provider, clears model credential variables, emits one canonical body-free JSON object, closes all owned handles, and exits nonzero on lifecycle/count/digest drift.

Run: `uv run python -m unittest -v tests.test_prime_ecosystem_real_process tests.test_setup_prime_agent`

Expected: PASS twice with identical public digest and zero provider/model/process counts.

- [ ] **Step 5: Commit the locked real-Prime harness**

```bash
git add packages/typescript/prime-gateway/resources/prime-ecosystem-module-lock.json packages/typescript/prime-gateway/resources/prime-ecosystem-module.mjs packages/typescript/prime-gateway/resources/prime-artifact-lock.json tools/setup_prime_agent.py tests/test_setup_prime_agent.py tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs tests/test_prime_ecosystem_real_process.py
git commit -m "test: lock Prime ecosystem module bundle"
```

---

### Task 6: Prove resource loading and collision diagnostics provider-free

**Files:**
- Create: `tests/fixtures/prime_ecosystem/v1/resources/`
- Modify: `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- Create: `tests/test_prime_ecosystem_resources.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: Tasks 1–5 sealed portfolio and `inspectResources()`.
- Produces: command `test.prime-ecosystem-resources.provider-free` and one safe receipt covering four exact feature IDs.

- [ ] **Step 1: Write failing exact resource-order, expansion, skill, and collision tests**

Create explicit fixtures for one global and one project context file, one prompt template with positional/slice arguments, one Markdown skill, one Python skill metadata tree, and two colliding prompt declarations. Tests must assert Prime-native parsing/ordering, nonrecursive substitution, exact skill kind/import identity, order-independent collision digest, no arbitrary Python import, and absence of file bodies/paths in the receipt.

```python
self.assertEqual(receipt["feature_ids"], [
    "ecosystem.collision-diagnostics",
    "ecosystem.context-files",
    "ecosystem.prompt-templates",
    "ecosystem.skills",
])
self.assertEqual(receipt["provider_operations"], 0)
self.assertEqual(receipt["model_credential_reads"], 0)
```

- [ ] **Step 2: Run the named tests and observe missing resource package support**

Run: `uv run python -m unittest -v tests.test_prime_ecosystem_resources`

Expected: FAIL until the real harness implements `resources` package observations.

- [ ] **Step 3: Implement the sealed resource scenario package**

Use only declared fixture files. Materialize them through Task 2, call Prime-native loaders through the locked bundle, compare private results to exact expected digests/order/kinds, reduce collisions to stable source IDs, and emit only feature IDs, assertion IDs, counts, and observation digest.

- [ ] **Step 4: Add and run the provider-free Make target twice**

```make
test.prime-ecosystem-resources.provider-free:
	$(UV_BIN) run python -m unittest -v tests.test_control_ecosystem tests.test_control_ecosystem_materialization tests.test_prime_ecosystem_resources
```

Run twice: `make test.prime-ecosystem-resources.provider-free`

Expected: both PASS with identical safe digest, zero model/provider operations, and zero retained processes.

- [ ] **Step 5: Commit the resource evidence package**

```bash
git add tests/fixtures/prime_ecosystem/v1/resources tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs tests/test_prime_ecosystem_resources.py Makefile
git commit -m "test: prove Prime ecosystem resources"
```

---

### Task 7: Prove extension lifecycle and registrations provider-free

**Files:**
- Create: `tests/fixtures/prime_ecosystem/v1/extensions/exact-extension.ts`
- Modify: `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- Create: `tests/test_prime_ecosystem_extensions.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: Tasks 1–5 `runExtensionLifecycle()` and durable Task 4 effect store.
- Produces: command `test.prime-ecosystem-extensions.provider-free` covering four exact feature IDs.

- [ ] **Step 1: Write failing lifecycle, command-state, tool, and provider/model tests**

The fixture extension registers one command `ecosystem-state`, one tool `ecosystem_echo`, and one provider/model pair `ecosystem-local/model-1`. Tests require lifecycle order `start → session → shutdown → teardown`, one invocation of each hook, durable command-state digest after close/reopen, deterministic local tool output digest, exact provider/model lookup, and zero provider invocation.

Add failure matrices for duplicate registrations, teardown throw, state append failure, reopened nonterminal effect, hostile tool output, provider invocation attempt, and sentinel-bearing extension errors.

- [ ] **Step 2: Run focused tests and observe missing extension scenario package**

Run: `uv run python -m unittest -v tests.test_prime_ecosystem_extensions`

Expected: FAIL until the shared harness supports `extensions`.

- [ ] **Step 3: Implement real Prime extension lifecycle observations**

Load only the exact fixture extension from the sealed root, bind the effect before lifecycle start, invoke the deterministic tool locally, resolve but never call the provider/model registration, persist only the command-state digest, teardown in reverse order, and reduce all private observations to fixed counts/digests.

- [ ] **Step 4: Add and run the provider-free extension gate twice**

```make
test.prime-ecosystem-extensions.provider-free:
	$(UV_BIN) run python -m unittest -v tests.test_prime_ecosystem_extensions
	npm --prefix packages/typescript/prime-gateway test -- test/ecosystem.test.mjs
```

Run twice: `make test.prime-ecosystem-extensions.provider-free`

Expected: PASS with identical receipt digest, exact lifecycle counts, zero provider/model operations, and zero retained processes.

- [ ] **Step 5: Commit the extension evidence package**

```bash
git add tests/fixtures/prime_ecosystem/v1/extensions/exact-extension.ts tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs tests/test_prime_ecosystem_extensions.py Makefile
git commit -m "test: prove Prime ecosystem extensions"
```

---

### Task 8: Prove exact package source selection provider-free

**Files:**
- Create: `tests/fixtures/prime_ecosystem/v1/packages/`
- Create: `tests/test_prime_ecosystem_packages.py`
- Modify: `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- Modify: `Makefile`

**Interfaces:**
- Consumes: existing `CapabilitySourceDeclaration`, `CapabilitySourceLock`, local/distribution source adapters, Task 2 materializer, and Task 5 `resolvePackage()`.
- Produces: command `test.prime-ecosystem-packages.provider-free` covering `ecosystem.packages`.

- [ ] **Step 1: Write failing exact-source and no-install tests**

Create one portable package fixture exposed through both a local-directory declaration and an installed-distribution declaration with distinct source IDs. Require the exact source lock to select one candidate and reject missing/duplicate candidates, digest drift, range syntax, remote/npm/git locators, symlinks, undeclared payload files, import during metadata discovery, fallback after selected-source failure, and network/process calls.

- [ ] **Step 2: Run focused tests and observe missing Prime package observation**

Run: `uv run python -m unittest -v tests.test_prime_ecosystem_packages`

Expected: FAIL until the real harness implements the package scenario.

- [ ] **Step 3: Implement exact package projection and Prime resolution**

Resolve the candidate through Asterion first, materialize only its declared payload, pass the exact selected identity/digest to Prime's locked package manager, disable installation commands and source fallback, and compare Prime's private resource result to the admitted package digest. Emit only one package count, selected source ID digest, and zero operation counts.

- [ ] **Step 4: Add and run the package gate twice**

```make
test.prime-ecosystem-packages.provider-free:
	$(UV_BIN) run python -m unittest -v tests.test_prime_ecosystem_packages tests.test_local_capability_source tests.test_distribution_capability_source
```

Run twice: `make test.prime-ecosystem-packages.provider-free`

Expected: PASS with no provider, model, network-install, or retained-process operation.

- [ ] **Step 5: Commit the package evidence package**

```bash
git add tests/fixtures/prime_ecosystem/v1/packages tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs tests/test_prime_ecosystem_packages.py Makefile
git commit -m "test: prove Prime ecosystem packages"
```

---

### Task 9: Prove MCP configuration and credential refresh provider-free

**Files:**
- Create: `src/asterion/control/ecosystem_mcp.py`
- Create: `tests/fixtures/prime_ecosystem/v1/mcp/local-server.mjs`
- Create: `tests/test_control_ecosystem_mcp.py`
- Create: `tests/test_prime_ecosystem_mcp.py`
- Modify: `tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs`
- Modify: `Makefile`

**Interfaces:**
- Consumes: Task 3 `McpCredentialRefresh`, Task 5 `runMcpFixture()`, an injected direct-invocation process service, cancellation signal, and fixed limits.
- Produces: `OwnedMcpFixtureService`, one body-free MCP receipt, and command `test.prime-ecosystem-mcp.provider-free` covering `ecosystem.mcp`.

- [ ] **Step 1: Write failing launch, one-refresh, cancellation, and redaction tests**

The local server supports one exact initialize/list operation, returns one fixed auth challenge, accepts one refreshed opaque credential, and exits on shutdown. Tests require direct argv without shell, cleared environment, mode-0600 discovery data, deadline/output caps, exactly one refresh, no refresh on replayed terminal receipt, cancellation that kills/reaps the child, zero children after close, and absence of credential/path/body sentinels in events/errors/receipts.

- [ ] **Step 2: Run focused tests and observe missing MCP host service**

Run: `uv run python -m unittest -v tests.test_control_ecosystem_mcp tests.test_prime_ecosystem_mcp`

Expected: FAIL because `OwnedMcpFixtureService` and MCP scenario support are absent.

- [ ] **Step 3: Implement the narrow host-owned MCP service**

Define:

```python
class OwnedMcpFixtureService:
    def start(self, descriptor: EcosystemMcpDescriptor, cancellation: CancellationSignal) -> EcosystemMcpSession: ...
    def refresh(self, lease_id: str, challenge_digest: str) -> str: ...
    def close(self, session: EcosystemMcpSession) -> None: ...
```

Validate one exact local server identity and executable binding injected by the operator; never accept an executable path from a manifest/frame. Launch directly with a cleared environment, cap bytes/deadline, persist bind before refresh, allow one refresh for the exact lease/challenge digest, and close/reap on success, failure, cancellation, or uncertainty. Return only IDs, counts, digests, and terminal state.

- [ ] **Step 4: Implement the real Prime MCP observation and run twice**

Call Prime's locked MCP manager/OAuth integration over the owned local channel, prove explicit configuration and one refresh, then shutdown both manager and server. Add:

```make
test.prime-ecosystem-mcp.provider-free:
	$(UV_BIN) run python -m unittest -v tests.test_control_ecosystem_mcp tests.test_prime_ecosystem_mcp
```

Run twice: `make test.prime-ecosystem-mcp.provider-free`

Expected: PASS with one host credential refresh, zero model credential reads, zero provider operations, and zero retained processes.

- [ ] **Step 5: Commit the MCP evidence package**

```bash
git add src/asterion/control/ecosystem_mcp.py tests/fixtures/prime_ecosystem/v1/mcp/local-server.mjs tests/fixtures/prime_gateway/v1/real-prime-ecosystem.mjs tests/test_control_ecosystem_mcp.py tests/test_prime_ecosystem_mcp.py Makefile
git commit -m "test: prove Prime ecosystem MCP integration"
```

---

### Task 10: Bind evidence, close the domain, and advance Climb

**Files:**
- Create: `src/asterion/control/providers/prime/ecosystem_parity_testing.py`
- Modify: `src/asterion/control/providers/prime/parity_testing.py`
- Create: `tests/test_prime_ecosystem_parity.py`
- Modify: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Modify: `tests/test_prime_parity_ledger.py`
- Modify: `tests/test_check_prime_parity.py`
- Modify: `docs/status/PRIME-PARITY-LEDGER.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/JOURNAL.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/climb/hypotheses.yaml`
- Modify: `tools/climb/regen-tree.py`
- Modify: `tools/climb/cycle.sh`

**Interfaces:**
- Consumes: four exact provider-free receipts from Tasks 6–9.
- Produces: ten evidence records, Prime Gateway `ecosystem.capabilities` 10/10 PASS, native results unchanged, and deterministic next Climb hypothesis for client interfaces.

- [ ] **Step 1: Write failing observation, ledger, and exact-domain tests**

```python
def test_observations_cover_exact_ten_without_provider_work(self) -> None:
    observations = build_prime_ecosystem_observations(_four_receipts())
    self.assertEqual(tuple(item.scenario_id for item in observations), PRIME_ECOSYSTEM_SCENARIO_IDS)
    self.assertTrue(all(item.provider_operations == 0 for item in observations))
    self.assertTrue(all(item.model_credential_reads == 0 for item in observations))

def test_ecosystem_domain_closes_only_with_all_ten(self) -> None:
    report = run_checker("ecosystem.capabilities", "asterion.prime-gateway")
    self.assertEqual(report["selected_feature_count"], 10)
    self.assertEqual(report["passed_feature_count"], 10)
    self.assertEqual(report["blocking_feature_count"], 0)
    self.assertEqual(report["status"], "PASS")
```

Add tests that each receipt can promote only its exact package features, wrong command/source/module/portfolio digests reject atomically, fake/nonzero-operation receipts have no evidence ID, arrays must be canonical, every native ecosystem result remains `missing`, and the verified-system claim remains BLOCKED on later domains.

- [ ] **Step 2: Run focused tests and observe ten missing ledger blockers**

Run: `uv run python -m unittest -v tests.test_prime_ecosystem_parity tests.test_prime_parity_ledger tests.test_check_prime_parity`

Expected: FAIL with exactly ten `ecosystem.capabilities` Prime Gateway results still `missing`.

- [ ] **Step 3: Implement exact observation reduction and evidence registration**

Define sorted `PRIME_ECOSYSTEM_SCENARIO_IDS`, four command-to-feature mappings, and immutable `PrimeEcosystemScenarioObservation`. Validate exact receipt keys, pinned baseline/artifact/module/portfolio identities, zero model/provider/process counts, expected lifecycle/MCP/package counts, and canonical observation digests. Register all ten runners with boundary `real-prime-provider-free` and fixed assertion IDs `authority-preserved`, `feature-reachable`, `identity-stable`, `public-redacted`.

- [ ] **Step 4: Promote only ten Prime Gateway rows and run closure gates**

Add ten sorted evidence objects with boundary `real-prime-provider-free` and their exact named commands. Change only the ten Prime Gateway results to `provider-free-pass`; keep every native result missing.

Run:

```bash
make test.prime-ecosystem-resources.provider-free
make test.prime-ecosystem-extensions.provider-free
make test.prime-ecosystem-packages.provider-free
make test.prime-ecosystem-mcp.provider-free
uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway
make check
make promotion-check
git diff --check
```

Expected: exact domain 10/10 PASS; all commands provider-free; promotion reports zero provider operations; native/system parity remains blocked.

- [ ] **Step 5: Regenerate Climb state and commit closure**

Use these exact implementation hypotheses and command IDs:

| ID | Outcome meaning | Command ID |
|---|---|---|
| H-025 | closed ecosystem portfolio contracts pass | `test.control-ecosystem.provider-free` |
| H-026 | exact materialization and cleanup pass | `test.ecosystem-materialization.provider-free` |
| H-027 | selected Prime adapter and host preflight pass | `test.prime-ecosystem-adapter.provider-free` |
| H-028 | Gateway frame and lifecycle fencing pass | `test.prime-ecosystem-gateway.provider-free` |
| H-029 | pinned Prime module bundle passes | `test.prime-ecosystem-module.provider-free` |
| H-030 | resource evidence package passes | `test.prime-ecosystem-resources.provider-free` |
| H-031 | extension evidence package passes | `test.prime-ecosystem-extensions.provider-free` |
| H-032 | exact package evidence passes | `test.prime-ecosystem-packages.provider-free` |
| H-033 | local MCP evidence passes | `test.prime-ecosystem-mcp.provider-free` |
| H-034 | 10/10 ecosystem and repository gates pass | `check.ecosystem-capabilities-closure` |

Set H-035 to pending with description `client interface closure inventory identifies exact shared-stream evidence packages` and parent paradigm `interface-clients`. Teach `regen-tree.py` these exact transitions, run H-034 once after all closure gates, and verify every cycle number occurs once.

```bash
git add src/asterion/control/providers/prime/ecosystem_parity_testing.py src/asterion/control/providers/prime/parity_testing.py tests/test_prime_ecosystem_parity.py tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json tests/test_prime_parity_ledger.py tests/test_check_prime_parity.py docs/status/PRIME-PARITY-LEDGER.md docs/status/CURRENT-STATE.md docs/status/JOURNAL.md docs/status/RESUME-NEXT-SESSION.md docs/status/climb tools/climb/regen-tree.py tools/climb/cycle.sh
git commit -m "feat: close Prime ecosystem parity"
```

---

## Plan Self-Review

- **Spec coverage:** Tasks 1–2 own exact public values, collision rejection, private declarations, no-follow materialization, atomic publication, and cleanup. Tasks 3–5 own host preflight, selected-provider translation, durable Gateway fencing, source/module locks, recovery, and real Prime execution. Tasks 6–9 independently deliver the four required provider-free evidence packages. Task 10 binds all ten results without widening native or system claims.
- **Scope:** The four evidence packages share one portfolio, materializer, frame, and reducer, so one plan avoids four conflicting composers while retaining independently reviewable tasks.
- **Placeholder scan:** Every task names exact files, interfaces, red/green commands, closed fields, failure matrices, and commit boundaries. No implementation placeholder or deferred behavior remains.
- **Type consistency:** `EcosystemPortfolio.digest` becomes `portfolioDigest` only in the private Gateway frame. `EcosystemActivationReceipt` and `PrimeEcosystemScenarioObservation` use the same feature IDs and zero-operation counts. MCP credential lease IDs exist only in the private frame/service and never in receipts or evidence.
- **Boundary check:** No task changes a public v1 schema, scans operator roots, installs from a registry, invokes a custom provider, grants Gateway authority, starts MCP from a runner, promotes fake evidence, or changes the native column.
