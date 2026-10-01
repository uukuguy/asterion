# Prime Application Tool Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move P7 application-tool registration behind a generic Prime registry contract, remove Prime-to-P7 registration coupling, and prove Python/TypeScript/bundled tool sets stay identical.

**Architecture:** `asterion.agents.prime.tool_registry` owns immutable, domain-neutral registry validation. P7 owns a concrete registry and all ARC implementations; the preflighted `PrimeLaunch` carries that registry into the selected P7 runtime. The Prime dispatcher lazily selects application bindings, while the TypeScript extension and checked-in resource expose the same canonical P7 names.

**Tech Stack:** Python 3.12+ with `unittest`, TypeScript 6, Node 20+, esbuild, Hatch resource collection, existing Pi RPC and Prime execution kernel.

## Global Constraints

- Generic Prime modules must not import P7 implementations or contain ARC semantics.
- Tool-name arrays are immutable, unique, and in canonical sorted order.
- P7 registry injection is exact and fail-closed; non-P7 applications retain `ipython` only.
- Manifests remain compatibility declarations; no prompts, credentials, commands, executable paths, environment values, or mutable state enter them.
- Production changes follow test-first red-green-refactor, with each task committed independently.
- Final completion requires an independent code review and rerun of affected checks.

---

### Task 1: Add the generic immutable Prime registry contract

**Files:**
- Create: `src/asterion/agents/prime/tool_registry.py`
- Modify: `src/asterion/agents/prime/__init__.py`
- Test: `tests/test_prime_tool_registry.py`

**Interfaces:**
- Produces `PrimeApplicationToolRegistry(module_id: str, capability_id: str, tool_names: tuple[str, ...])`.
- Produces `PrimeApplicationToolRegistry.allowed_tool_names -> tuple[str, ...]`.
- Produces `PrimeApplicationToolRegistry.matches(module_id: str, capability_id: str) -> bool`.
- Invalid identifiers, empty names, duplicates, non-tuples, or unsorted names raise `ProtocolError` without retaining mutable input.

- [ ] **Step 1: Write the failing tests**

Add tests covering:

```python
class TestPrimeApplicationToolRegistry(unittest.TestCase):
    def test_accepts_sorted_unique_names_and_freezes_input(self):
        registry = PrimeApplicationToolRegistry(
            "prime.example.tools", "prime.tool.example", ("ipython", "tool.z")
        )
        self.assertEqual(registry.allowed_tool_names, ("ipython", "tool.z"))
        self.assertTrue(registry.matches("prime.example.tools", "prime.tool.example"))

    def test_rejects_unsorted_duplicate_or_mutable_names(self):
        with self.assertRaises(ProtocolError):
            PrimeApplicationToolRegistry("prime.example.tools", "prime.tool.example", ("z", "a"))
        with self.assertRaises(ProtocolError):
            PrimeApplicationToolRegistry("prime.example.tools", "prime.tool.example", ("a", "a"))
        with self.assertRaises(ProtocolError):
            PrimeApplicationToolRegistry("prime.example.tools", "prime.tool.example", ["a"])

    def test_matches_rejects_cross_module_capability(self):
        registry = PrimeApplicationToolRegistry(
            "prime.example.tools", "prime.tool.example", ("ipython",)
        )
        self.assertFalse(registry.matches("prime.other.tools", "prime.tool.example"))
        self.assertFalse(registry.matches("prime.example.tools", "prime.tool.other"))
```

- [ ] **Step 2: Run the focused test and verify the expected red failure**

Run: `uv run python -m unittest -v tests.test_prime_tool_registry`

Expected: import or attribute failures because the registry module and class do not exist yet.

- [ ] **Step 3: Implement the smallest contract**

Use a frozen, slotted dataclass. Validate exact `str` identifiers with the existing Prime identifier rules, require a tuple of exact strings, require `tool_names == tuple(sorted(set(tool_names)))`, and expose the tuple directly because it is immutable. Export the class from `asterion.agents.prime`.

- [ ] **Step 4: Run the focused test and verify green**

Run: `uv run python -m unittest -v tests.test_prime_tool_registry`

Expected: all registry validation and matching tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/agents/prime/tool_registry.py src/asterion/agents/prime/__init__.py tests/test_prime_tool_registry.py
git commit -m "feat(prime): add immutable application tool registry"
```

### Task 2: Create the P7 concrete registry and move the canonical Python names

**Files:**
- Create: `src/asterion/applications/prime/p7/tool_registry.py`
- Modify: `src/asterion/applications/prime/p7/live.py`
- Modify: `src/asterion/applications/prime/p7/broker.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Test: `tests/test_prime_p7_tool_registry.py`
- Modify: `tests/test_prime_p7_live_command.py`
- Modify: `tests/test_prime_p7_native_broker.py`

**Interfaces:**
- Produces `P7_TOOL_MODULE_ID = "prime.p7.application-tools"`.
- Produces `P7_TOOL_CAPABILITY_ID = "prime.tool.p7"`.
- Produces `P7_APPLICATION_TOOL_NAMES` and `P7_TOOL_REGISTRY` from one tuple containing `ipython` and all currently implemented P7 bridge methods, sorted uniquely.
- Keeps `p7.live.P7_APPLICATION_TOOL_NAMES` as a compatibility re-export.

- [ ] **Step 1: Write the failing tests**

Add tests that import the P7 registry, assert its exact module/capability ids, assert sorted unique names, assert every `p7_*` facade method has a registry name, and assert the existing `live.pi_base_command()` uses the registry tuple. Add a prompt-registry test that rejects a `Tool` whose name is absent from `P7_APPLICATION_TOOL_NAMES`.

- [ ] **Step 2: Run the focused tests and verify red**

Run: `uv run python -m unittest -v tests.test_prime_p7_tool_registry tests.test_prime_p7_live_command tests.test_prime_p7_native_broker`

Expected: the new imports/registry identity and prompt-name assertion fail against the current `live.py` constant and independent prompt registration.

- [ ] **Step 3: Implement the concrete registry**

Move the existing 23-name list into `p7/tool_registry.py`, canonicalize its order, construct `P7_TOOL_REGISTRY`, and replace the old tuple definition in `live.py` with a re-export. Make `P7ToolRegistry.register()` validate that the registered tool name belongs to the executable P7 registry while retaining its existing prompt-rendering behavior.

- [ ] **Step 4: Run focused tests and verify green**

Run the same command from Step 2. Expected: all registry, prompt, and Pi command tests pass with the canonical order.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime/p7/tool_registry.py src/asterion/applications/prime/p7/live.py src/asterion/applications/prime/p7/broker.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_tool_registry.py tests/test_prime_p7_live_command.py tests/test_prime_p7_native_broker.py
git commit -m "feat(p7): centralize concrete prime tool registry"
```

### Task 3: Carry the registry through P7 preflight and fail closed at runtime

**Files:**
- Create: `src/asterion/applications/prime/p7/runtime_binding.py`
- Modify: `src/asterion/applications/prime/runtime_binding.py`
- Modify: `src/asterion/applications/prime/p7/operator.py`
- Test: `tests/test_prime_p7_native_provider.py`
- Create: `tests/test_prime_runtime_dependency_direction.py`

**Interfaces:**
- `PrimeLaunch` gains `tool_registry: PrimeApplicationToolRegistry` and retains its redacted representation.
- `build_p7_runtime()` and `build_p7_gameplay_runtime()` require `launch.tool_registry.matches(P7_TOOL_MODULE_ID, P7_TOOL_CAPABILITY_ID)` and pass `launch.tool_registry.allowed_tool_names` to `AsterionPrimeSession`.
- `build_asterion_prime_runtime()` remains a thin exact-key dispatcher and lazily imports P7 bindings.

- [ ] **Step 1: Write failing tests**

Extend the P7 native-provider fixtures to construct `PrimeLaunch` with `P7_TOOL_REGISTRY`; add cases for missing, wrong-module, wrong-capability, and mutable registry values that must raise `RuntimeFactoryError` and close the lease. Add a dependency-direction test that imports the Prime root binding and asserts no P7 module is loaded solely by that import, then verifies exact P7 dispatch still works through lazy import.

- [ ] **Step 2: Run tests and verify red**

Run: `uv run python -m unittest -v tests.test_prime_p7_native_provider tests.test_prime_runtime_dependency_direction`

Expected: constructor/type failures for the new launch field and a failure showing the current root binding imports P7 modules eagerly.

- [ ] **Step 3: Move P7-specific runtime code**

Move `PrimeLaunch`, P7 launch validation, P7 continuation/terminal helpers, P7 event projectors, and the two P7 builders into `src/asterion/applications/prime/p7/runtime_binding.py`. Leave the root module with shared imports, the exact dispatcher, and the runtime factory publication. Update P7 operator/tests to import `PrimeLaunch` from the P7 binding module. The P7 module imports the generic registry protocol and concrete P7 registry; the root module imports neither `p7.live` nor other P7 implementation modules.

- [ ] **Step 4: Inject and validate the registry**

Create `PrimeLaunch(..., tool_registry=P7_TOOL_REGISTRY)` in P7 preflight. In both P7 builders validate the exact module/capability pair before reconstructing the extension binding, then pass `launch.tool_registry.allowed_tool_names` to the session. Preserve all existing launch fingerprint, environment, trace, and lease checks.

- [ ] **Step 5: Run focused tests and verify green**

Run: `uv run python -m unittest -v tests.test_prime_p7_native_provider tests.test_prime_p7_official_operator tests.test_asterion_prime_runtime tests.test_prime_runtime_dependency_direction`

Expected: P7 solve/gameplay construction, rejection paths, lease cleanup, and lazy dispatch all pass.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/applications/prime/runtime_binding.py src/asterion/applications/prime/p7/runtime_binding.py src/asterion/applications/prime/p7/operator.py tests/test_prime_p7_native_provider.py tests/test_prime_p7_official_operator.py tests/test_asterion_prime_runtime.py tests/test_prime_runtime_dependency_direction.py
git commit -m "refactor(prime): inject P7 tools through application launch"
```

### Task 4: Make the TypeScript extension expose the canonical P7 tool set

**Files:**
- Modify: `packages/typescript/asterion-prime-extension/src/ipython-extension.ts`
- Modify: `packages/typescript/asterion-prime-extension/test/ipython-extension.test.mjs`
- Test: `tests/test_prime_extension_tool_contract.py`

**Interfaces:**
- `toolNames(): string[]` returns one canonical sorted list containing `ipython` and every P7 registered method.
- `createAppLevelTools(bridge)` returns exactly one executable tool per P7 name, with the existing schemas preserved for current tools and explicit schemas for level/hypothesis inputs.
- `registered.map(tool => tool.name)` equals `toolNames()`.

- [ ] **Step 1: Write failing TypeScript/Python contract tests**

Update the Node test expected list to the complete P7 registry set and assert `toolNames()`, registration output, and sorted uniqueness. Add a Python test that loads the TypeScript module through Node, parses the JSON tool-name output, and compares it to `P7_APPLICATION_TOOL_NAMES`.

- [ ] **Step 2: Run tests and verify red**

Run: `npm test --prefix packages/typescript/asterion-prime-extension` and `uv run python -m unittest -v tests.test_prime_extension_tool_contract`

Expected: source `toolNames()` and registered tool count differ from the complete P7 registry.

- [ ] **Step 3: Implement one TypeScript specification table**

Define a frozen `P7_TOOL_SPECS` table containing each P7 name, bridge method, description, parameter schema, and optional input key. Build `toolNames()` from `['ipython', ...P7_TOOL_SPECS.map(spec => spec.name)]` after canonical sorting; build `createAppLevelTools()` by mapping the same table through `makeMethodTool`. Keep `createIpythonTool()` separate and unchanged at the generic Prime boundary.

- [ ] **Step 4: Run TypeScript and contract tests**

Run the two commands from Step 2. Expected: all existing bridge behavior tests and the exact cross-language name comparison pass.

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/asterion-prime-extension/src/ipython-extension.ts packages/typescript/asterion-prime-extension/test/ipython-extension.test.mjs tests/test_prime_extension_tool_contract.py
git commit -m "feat(prime-extension): register the complete P7 tool set"
```

### Task 5: Make the checked-in bundled resource reproducible and drift-checked

**Files:**
- Create: `packages/typescript/asterion-prime-extension/scripts/sync-runtime-resource.mjs`
- Modify: `packages/typescript/asterion-prime-extension/package.json`
- Modify: `Makefile` target `test-typescript`
- Modify: `src/asterion/applications/prime/resources/ipython-extension.mjs`
- Modify: `tests/test_prime_extension_build.py`

**Interfaces:**
- `npm run sync-resource --prefix packages/typescript/asterion-prime-extension` builds and copies the tested bundle to the checked-in resource.
- `npm run check-resource --prefix packages/typescript/asterion-prime-extension` fails when the generated bundle differs from the checked-in resource.

- [ ] **Step 1: Write failing resource-sync tests**

Extend `test_prime_extension_build.py` to assert the package script names, source/resource digest parity after sync, and non-zero check behavior after a one-byte resource mutation. Add a Makefile test-typescript assertion that the Prime extension package test and resource check both run.

- [ ] **Step 2: Run the new tests and verify red**

Run: `uv run python -m unittest -v tests.test_prime_extension_build`

Expected: the script names and resource parity checks are absent.

- [ ] **Step 3: Implement sync/check scripts**

Use the package root, `dist/ipython-extension.mjs`, and `../../../../src/asterion/applications/prime/resources/ipython-extension.mjs`. `sync-resource` runs the existing build, copies the bundle, and exits non-zero on build/copy failure. `check-resource` runs the build in a temporary output path and compares bytes without mutating the repository. Add both commands to the Prime extension package scripts and include `npm test` plus `npm run check-resource` in `Makefile:test-typescript`.

- [ ] **Step 4: Regenerate and verify the checked-in resource**

Run: `npm run sync-resource --prefix packages/typescript/asterion-prime-extension`, then `npm run test --prefix packages/typescript/asterion-prime-extension` and `npm run check-resource --prefix packages/typescript/asterion-prime-extension`.

Expected: the bundle contains the complete registry set, is comment-free, and the check exits zero without changing it.

- [ ] **Step 5: Commit**

```bash
git add packages/typescript/asterion-prime-extension/scripts/sync-runtime-resource.mjs packages/typescript/asterion-prime-extension/package.json Makefile src/asterion/applications/prime/resources/ipython-extension.mjs tests/test_prime_extension_build.py
git commit -m "build(prime-extension): verify bundled tool registry resource"
```

### Task 6: Run integrated regression checks and update durable state

**Files:**
- Modify: `docs/status/JOURNAL.md`

- [ ] **Step 1: Run focused Python and TypeScript suites**

Run:

```bash
uv run python -m unittest -v tests.test_prime_tool_registry tests.test_prime_p7_tool_registry tests.test_prime_p7_live_command tests.test_prime_p7_native_provider tests.test_prime_p7_native_broker tests.test_asterion_prime_runtime tests.test_prime_runtime_dependency_direction tests.test_prime_extension_tool_contract
npm test --prefix packages/typescript/asterion-prime-extension
```

Expected: all focused tests pass with no stale-resource or dependency-direction failures.

- [ ] **Step 2: Run repository checks required by the changed surfaces**

Run: `make test`, `make lint`, `make docs-check`, `make check`, and `make promotion-check`.

Expected: each command has a named passing result. If an external backend or unavailable packaged dependency prevents a check, record it as external-limited or not rerun rather than promoting it to PASS.

- [ ] **Step 3: Record verification evidence**

Append one journal line per durable commit and one line for the final verification result. Update `CURRENT-STATE.md` only for structural changes and keep in-flight details in `RESUME-NEXT-SESSION.md`.

- [ ] **Step 4: Commit verification/state changes**

```bash
git add docs/status/JOURNAL.md docs/status/CURRENT-STATE.md docs/status/RESUME-NEXT-SESSION.md
git commit -m "docs(status): record prime registry verification"
```

### Task 7: Independent code review and review-fix cycle

**Files:**
- Review all files changed by Tasks 1–6.
- Create only the review artifact required by the code-review workflow.

- [ ] **Step 1: Dispatch an independent reviewer**

Use a fresh reviewer with no implementation ownership. Ask it to inspect registry immutability, P7 capability isolation, non-P7 denial, lazy dependency direction, TypeScript/resource parity, bridge dispatch preservation, redaction, and test adequacy.

- [ ] **Step 2: Classify every finding**

For each finding, reproduce it with a focused test or static evidence. Mark it fixed, accepted with rationale, or external-limited; do not leave unclassified findings.

- [ ] **Step 3: Fix material findings test-first**

For each fix, add or update a failing regression test, run it red, apply the smallest fix, run the focused suite green, and commit the fix separately.

- [ ] **Step 4: Rerun affected checks and review the diff**

Run the focused suites plus the repository checks required by the finding. Confirm `git diff --check`, `git status --short`, and the final dependency scan are clean.

- [ ] **Step 5: Commit the review outcome**

```bash
git add docs/superpowers/reviews/ src/asterion/agents/prime src/asterion/applications/prime packages/typescript/asterion-prime-extension Makefile tests
git commit -m "review(prime): resolve registry implementation findings"
```
