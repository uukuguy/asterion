# Asterion Capability Package Sources and SDK Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load built-in and third-party capability packages through one source-neutral, metadata-first model with exact source locking and a stable public SDK.

**Architecture:** Source adapters produce immutable metadata candidates without importing providers. An exact lock selects one candidate, payload validation binds content identity, and only then may the selected factory produce an `InstalledCapabilityPackage`. Built-in packages use the same interface as installed and local extensions.

**Tech Stack:** Python protocols/dataclasses, `importlib.metadata`, `importlib.resources`, SHA-256, canonical JSON, `unittest`, Hatchling entry points.

## Global Constraints

- Consume the protocol values created by the protocol-foundation plan.
- No source scanning, recursive catalog discovery, version ranges, or implicit precedence.
- Provider factories are not imported by list/describe/discover operations.
- Source paths and provider locators are private operator data.
- Symlinks and package-root escapes fail closed.
- Installed third-party Python code is trusted only after exact selection; no sandbox claim.
- No provider-backed execution or network access.

## File structure

- `src/asterion/capability_packages/model.py`: candidate, payload, installed-package, and binding values.
- `src/asterion/capability_packages/payload.py`: canonical closure and digest validation.
- `src/asterion/capability_packages/sources/base.py`: source protocol.
- `sources/{builtin,distribution,local}.py`: first-phase adapters.
- `src/asterion/capability_packages/resolution.py`: exact source-lock resolution.
- `src/asterion/capability_sdk/`: stable third-party-facing re-exports and helpers.
- `src/asterion/cli_capability.py`: `asterion capability` author commands.
- `tests/fixtures/extensions/`: third-party distribution and local-directory fixtures.

---

### Task 1: Define source-neutral package values

**Files:**
- Create: `src/asterion/capability_packages/model.py`
- Create: `src/asterion/capability_packages/sources/__init__.py`
- Create: `src/asterion/capability_packages/sources/base.py`
- Modify: `src/asterion/capability_packages/__init__.py`
- Create: `tests/test_capability_package_model.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class CapabilityPackageCandidate:
    package_ref: CapabilityPackageRef
    source_id: str
    source_kind: str
    payload_sha256: str | None
    metadata: Mapping[str, str]

@dataclass(frozen=True, slots=True)
class PortableCapabilityPayload:
    manifest: CapabilityPackageManifest
    payload_sha256: str
    resource_root: Traversable

@dataclass(frozen=True, slots=True)
class BenchmarkTaskBinding:
    owner_package: CapabilityPackageRef
    binding_id: str
    implementation: object = field(repr=False)

@dataclass(frozen=True, slots=True)
class InstalledCapabilityPackage:
    package_ref: CapabilityPackageRef
    payload_sha256: str
    source_id: str
    source_kind: str
    catalog_roots: tuple[Path, ...]
    benchmark_suite_paths: tuple[Path, ...]
    implementations: tuple[CapabilityImplementationBinding, ...]
    benchmark_bindings: tuple[BenchmarkTaskBinding, ...]
```

`implementation` is an opaque selected-provider value at this layer. The
generic benchmark subsystem defines and validates its executable protocol
before creating a resolved plan.

- Produces:

```python
class CapabilityPackageSource(Protocol):
    def discover_metadata(self) -> tuple[CapabilityPackageCandidate, ...]: ...
    def open_payload(self, candidate: CapabilityPackageCandidate) -> PortableCapabilityPayload: ...
    def validate_source_identity(self, candidate: CapabilityPackageCandidate, payload: PortableCapabilityPayload) -> None: ...
    def load_provider(self, candidate: CapabilityPackageCandidate) -> InstalledCapabilityPackage: ...
```

- [ ] **Step 1: Write immutability and body-free representation tests**

Verify frozen assignment fails, metadata is copied into an immutable mapping,
and `repr(candidate)` omits locators and factory names.

- [ ] **Step 2: Run and observe missing model**

Run:

```bash
uv run python -m unittest -v tests.test_capability_package_model
```

Expected: import failure.

- [ ] **Step 3: Implement immutable values**

Normalize candidate metadata with:

```python
safe_metadata = MappingProxyType({
    str(key): str(value)
    for key, value in sorted(metadata.items())
    if key in {"distribution_name", "distribution_version"}
})
```

Reject unknown `source_kind`; reserve exact values:

```python
SOURCE_KINDS = ("archive", "builtin", "local-directory", "python-distribution", "registry")
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_capability_package_model
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capability_packages tests/test_capability_package_model.py
git commit -m "feat: define source-neutral capability package values"
```

### Task 2: Validate canonical portable payload closure and identity

**Files:**
- Create: `src/asterion/capability_packages/payload.py`
- Create: `tests/test_capability_package_payload.py`
- Create: `tests/fixtures/extensions/minimal/payload/capability-package.json`
- Create: direct capability/resource/conformance children for the minimal fixture

**Interfaces:**
- Produces:

```python
def open_portable_payload(root: Path) -> PortableCapabilityPayload: ...
def canonical_payload_sha256(root: Path, manifest: CapabilityPackageManifest) -> str: ...
```

- [ ] **Step 1: Write failure matrices**

Use `subTest` cases for:

```text
missing declared member
extra identity-bearing member
symlinked root
symlinked child
child path escape
resource digest mismatch
non-regular file
noncanonical JSON
provider or command field in manifest
```

The happy-path digest must be stable after copying the same payload to a
different absolute directory and changing mtimes.

- [ ] **Step 2: Run and observe missing validator**

Run:

```bash
uv run python -m unittest -v tests.test_capability_package_payload
```

Expected: import failure.

- [ ] **Step 3: Implement descriptor-relative reads**

Open the canonical root with `O_DIRECTORY | O_NOFOLLOW`, enumerate only the
exact declared direct children, and hash a canonical map:

```python
entry = relative_name.encode("utf-8") + b"\0" + sha256(content).digest()
payload_digest.update(len(entry).to_bytes(8, "big"))
payload_digest.update(entry)
```

Sort relative names by Unicode scalar order. Exclude source envelopes,
timestamps, wheel metadata, and operator configuration.

- [ ] **Step 4: Verify location-independent identity**

Run:

```bash
uv run python -m unittest -v tests.test_capability_package_payload
```

Expected: PASS and equal digests for copied payload roots.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capability_packages/payload.py tests/test_capability_package_payload.py tests/fixtures/extensions/minimal
git commit -m "feat: validate portable capability payloads"
```

### Task 3: Implement exact source-lock resolution

**Files:**
- Create: `src/asterion/capability_packages/resolution.py`
- Create: `tests/test_capability_source_resolution.py`

**Interfaces:**
- Produces:

```python
def resolve_capability_source(
    package_ref: CapabilityPackageRef,
    candidates: Sequence[CapabilityPackageCandidate],
    lock: CapabilitySourceLock | None,
) -> CapabilityPackageCandidate: ...
```

- [ ] **Step 1: Write resolution truth-table tests**

Cover:

```text
zero candidates -> missing
one exact candidate, no lock -> selected
two exact candidates, no lock -> ambiguous
two candidates with identical digest, no lock -> still ambiguous
lock selects exact source and digest -> selected
lock source missing -> missing
lock digest mismatch -> rejected
unrelated package candidates -> ignored
```

- [ ] **Step 2: Run and observe missing resolver**

Run:

```bash
uv run python -m unittest -v tests.test_capability_source_resolution
```

Expected: import failure.

- [ ] **Step 3: Implement exact resolver**

The core selection is:

```python
matches = tuple(
    candidate for candidate in candidates
    if candidate.package_ref == package_ref
)
if lock is None:
    if len(matches) != 1:
        raise CapabilitySourceResolutionError("capability source is unavailable or ambiguous")
    return matches[0]
```

With a lock, require exact package ref, source ID, and payload digest. Never
sort and pick a first candidate.

- [ ] **Step 4: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_capability_source_resolution
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capability_packages/resolution.py tests/test_capability_source_resolution.py
git commit -m "feat: resolve exact capability package sources"
```

### Task 4: Implement the built-in source adapter

**Files:**
- Create: `src/asterion/capability_packages/sources/builtin.py`
- Create: `src/asterion/capabilities/builtin.py`
- Modify: `src/asterion/applications/provider.py`
- Modify: the controlled-code built-in application provider
- Create: `tests/test_builtin_capability_source.py`

**Interfaces:**
- Produces:

```python
@dataclass(frozen=True, slots=True)
class BuiltinCapabilityRegistration:
    package_ref: CapabilityPackageRef
    payload_root: Path
    provider_factory: Callable[[], InstalledCapabilityPackage]

def builtin_capability_sources() -> tuple[BuiltinCapabilityRegistration, ...]: ...
```

- [ ] **Step 1: Write tests proving built-in has no bypass**

Patch a built-in descriptor to have a bad digest/member and assert discovery
succeeds metadata-only but `open_payload` fails. Patch the provider factory and
assert `discover_metadata()` never calls it.

- [ ] **Step 2: Run and observe missing adapter**

Run:

```bash
uv run python -m unittest -v tests.test_builtin_capability_source
```

Expected: import failure.

- [ ] **Step 3: Implement an explicit registration table**

Use immutable explicit registrations:

```python
return (
    BuiltinCapabilityRegistration(
        CapabilityPackageRef("controlled-code", "1.0.0"),
        package_root / "controlled_code",
        create_controlled_code_package,
    ),
)
```

Do not glob `src/asterion/capabilities`.
Do not register DCI here: its transitional payload is exercised through the
explicit local-directory adapter in Task 6, and the DCI migration plan must
prove installed-distribution form before registering the final built-in form.

- [ ] **Step 4: Adapt the controlled-code application to exact package refs**

`InstalledApplication` stores:

```python
capability_packages: tuple[CapabilityPackageRef, ...]
```

It no longer owns raw catalog roots or implementation tuples. The host resolves
those from selected installed packages.

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_builtin_capability_source tests.test_installed_application_provider tests.test_builtin_controlled_code_application
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/capability_packages/sources/builtin.py src/asterion/capabilities/builtin.py src/asterion/applications/controlled_code src/asterion/applications/provider.py tests/test_builtin_capability_source.py tests/test_installed_application_provider.py tests/test_builtin_controlled_code_application.py
git commit -m "feat: load built-in capabilities through source adapter"
```

### Task 5: Implement metadata-only installed-distribution discovery

**Files:**
- Create: `src/asterion/capability_packages/sources/distribution.py`
- Create: `tests/fixtures/extensions/distribution/pyproject.toml`
- Create: a minimal extension package and standard payload data root
- Create: `tests/test_distribution_capability_source.py`
- Modify: root `pyproject.toml` only if a test fixture helper dependency is required

**Interfaces:**
- Produces:

```python
ENTRY_POINT_GROUP = "asterion.capability_packages"

class DistributionCapabilityPackageSource(CapabilityPackageSource):
    def __init__(self, distributions: Iterable[Distribution] | None = None): ...
```

- [ ] **Step 1: Build a fixture wheel and write import-sentinel tests**

The fixture provider raises if imported during discovery:

```python
if os.environ.get("ASTERION_TEST_FORBID_PROVIDER_IMPORT") == "1":
    raise RuntimeError("provider imported during metadata discovery")
```

The test installs the wheel into a temporary target and asserts list/discovery
finds `acme.sample@1.0.0` without triggering the sentinel.

- [ ] **Step 2: Run and observe missing adapter**

Run:

```bash
uv run python -m unittest -v tests.test_distribution_capability_source
```

Expected: import failure.

- [ ] **Step 3: Implement discovery from distribution files**

Read `importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)` and the
standard payload data root from `Distribution.files`. Parse the exact entry
point name as `package_id@version`; do not call `EntryPoint.load()` in
discovery or `open_payload`.

- [ ] **Step 4: Load only the selected provider and bind identity**

On `load_provider`, call the selected entry point and require:

```python
installed.package_ref == candidate.package_ref
installed.payload_sha256 == validated_payload.payload_sha256
installed.source_kind == "python-distribution"
```

Reject duplicate entry-point names before import.

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_distribution_capability_source
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/capability_packages/sources/distribution.py tests/fixtures/extensions/distribution tests/test_distribution_capability_source.py pyproject.toml
git commit -m "feat: discover installed capability distributions"
```

### Task 6: Implement explicit local-directory source

**Files:**
- Create: `src/asterion/capability_packages/sources/local.py`
- Create: `src/asterion/capabilities/dci_research/provider.py`
- Create: `tests/test_local_capability_source.py`
- Extend: `tests/fixtures/extensions/minimal/`
- Modify: `src/asterion/applications/dci_agent_lite/provider.py`
- Modify: `tests/test_dci_complete_application.py`

**Interfaces:**
- Consumes: `CapabilitySourceDeclaration` with exact canonical root and factory locator.
- Produces: `LocalDirectoryCapabilityPackageSource`.

- [ ] **Step 1: Write local trust-boundary tests**

Cover root symlink, descriptor symlink, child symlink, outside-root factory,
missing factory, identity mismatch, private path redaction, and a valid explicit
root. Assert no parent or sibling is scanned.

- [ ] **Step 2: Run and observe missing adapter**

Run:

```bash
uv run python -m unittest -v tests.test_local_capability_source
```

Expected: import failure.

- [ ] **Step 3: Implement canonical explicit-root loading**

Resolve with `strict=True`, compare `lstat`/opened descriptor identity, reject
symlinks, and import only the exact operator-supplied module/factory. Never
insert the package parent into global `sys.path`; use a scoped import spec and
remove temporary module entries after factory failure.

Create the transitional DCI package provider at
`asterion.capabilities.dci_research.provider:create_provider`. It constructs
the exact local-package bindings through the internal source API only; it is
selected solely by an explicit local source declaration and is not registered
in the built-in adapter. Plan 4 removes it after the external distribution
form is proven.

- [ ] **Step 4: Verify**

Adapt the transitional DCI application test host to inject one explicit
local-directory source declaration for
`src/asterion/capabilities/dci_research`. This is test/operator wiring, not a
built-in registration, and is removed by the DCI migration plan after the
external distribution is proven.

Run:

```bash
uv run python -m unittest -v tests.test_local_capability_source tests.test_dci_complete_application
```

Expected: PASS with sentinel paths absent from exceptions.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/capability_packages/sources/local.py src/asterion/capabilities/dci_research/provider.py src/asterion/applications/dci_agent_lite/provider.py tests/test_local_capability_source.py tests/test_dci_complete_application.py tests/fixtures/extensions/minimal
git commit -m "feat: load explicit local capability packages"
```

### Task 7: Publish the public capability SDK and conformance kit

**Files:**
- Create: `src/asterion/capability_sdk/__init__.py`
- Create: `src/asterion/capability_sdk/provider.py`
- Create: `src/asterion/capability_sdk/conformance.py`
- Create: `tests/test_capability_sdk.py`
- Create: `tests/test_capability_conformance.py`
- Modify: built-in capability implementation imports

**Interfaces:**
- Public exports are only:

```python
CapabilityRef
CapabilityPackageRef
CapabilityInvocation
CapabilityExecutionResult
CapabilityExecutionError
CapabilityPackageProvider
InstalledCapabilityPackage
BenchmarkTaskBinding
CancellationSignal
HostServices
run_capability_conformance
```

- [ ] **Step 1: Write public-surface and private-import tests**

Assert the exact `__all__` set. AST-scan built-in capability Python files and
reject imports from private composer, runner, source adapters, or application
providers.

- [ ] **Step 2: Run and observe missing SDK**

Run:

```bash
uv run python -m unittest -v tests.test_capability_sdk tests.test_capability_conformance
```

Expected: import failure.

- [ ] **Step 3: Implement stable re-exports and conformance runner**

`run_capability_conformance(installed)` validates exact identity, immutable
bindings, manifest closure, binding completeness, body-free failures, and
fixture vectors without provider/runtime execution.

- [ ] **Step 4: Migrate built-ins to public SDK imports**

Capability implementation modules may import only `asterion.capability_sdk`
plus standard-library and package-owned modules.

- [ ] **Step 5: Verify**

Run:

```bash
uv run python -m unittest -v tests.test_capability_sdk tests.test_capability_conformance tests.test_builtin_controlled_code_application tests.test_dci_complete_application
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/asterion/capability_sdk src/asterion/capabilities tests/test_capability_sdk.py tests/test_capability_conformance.py tests/test_builtin_controlled_code_application.py tests/test_dci_complete_application.py
git commit -m "feat: publish capability provider SDK"
```

### Task 8: Add capability author commands and phase gate

**Files:**
- Create: `src/asterion/cli_capability.py`
- Modify: `src/asterion/cli.py`
- Create: `tests/test_capability_cli.py`
- Create: `docs/guides/asterion-capability-packages.md`
- Modify: `tools/check_promotion.py`

**Interfaces:**
- Adds:

```text
asterion capability init
asterion capability validate
asterion capability inspect
asterion capability test
```

`pack` and `convert` validate arguments but report unsupported until their
archive-form plan is approved; help text states the staged boundary.

- [ ] **Step 1: Write CLI behavior and redaction tests**

Test help, valid fixture validation, invalid private path redaction, metadata
inspection without provider import, and no monetary/provider options.

- [ ] **Step 2: Run and observe missing command**

Run:

```bash
uv run python -m unittest -v tests.test_capability_cli
```

Expected: parser failure because `capability` is unknown.

- [ ] **Step 3: Implement commands through source/payload APIs**

Do not duplicate validation in CLI. `init` copies the checked-in template;
`validate` opens a portable payload; `inspect` prints safe IDs/digests only;
`test` runs public conformance.

- [ ] **Step 4: Run the package-source phase gate**

Run:

```bash
uv run python -m unittest -v tests.test_capability_package_model tests.test_capability_package_payload tests.test_capability_source_resolution tests.test_builtin_capability_source tests.test_distribution_capability_source tests.test_local_capability_source tests.test_capability_sdk tests.test_capability_conformance tests.test_capability_cli
make check
make promotion-check
```

Expected: all PASS; provider operations `0`; full dataset `no`.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/cli.py src/asterion/cli_capability.py tests/test_capability_cli.py docs/guides/asterion-capability-packages.md tools/check_promotion.py
git commit -m "feat: add capability package author workflow"
```
