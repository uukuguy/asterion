# Prime Platform-Neutral Release Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the synthetic single-target Prime image authority with a platform-neutral recipe, explicit candidate-target policy, and truthful untrusted acquisition proposals.

**Architecture:** A new operator contracts module owns the pinned Prime source triple, platform-free recipe identity, and exact candidate descriptors. The promoted image-input catalog may be empty; synthetic bytes are tests only. Proposal generation and staging consume recipe/policy, while artifact verification remains promoted-lock-only.

**Tech Stack:** Python 3.12 frozen dataclasses, `unittest`, SHA-256, canonical JSON, existing no-follow verifier and injected release transport.

## Global Constraints

- Recipe records contain no OS, architecture, variant, URL, credential, host path, environment, mutable state, or execution authority.
- Candidate policy is exactly sorted `linux/arm64` then `linux/amd64`, each with `variant=None`; missing, unknown, duplicate, substituted, host-derived, fallback, range, or variant-mismatched targets fail closed.
- Candidate policy never promotes a lock. The default promoted catalog is empty until a real reviewed lock exists; the former size-one/cp312 lock is test-only synthetic data.
- Image-lock hashing and full-set verification require an explicit promoted lock; they have no synthetic default argument.
- Every source triple equals the pinned Prime triple. Recipe Python is exactly `3.11`; Node is exactly `22.8.0`.
- Metadata and downloaded objects are distinct records; a code-owned parser claim binds a metadata declaration to object size and SHA-256.
- Proposals/staging remain `untrusted`; they never construct a verified proof, parse as an image-input lock, claim release authority, or claim PASS.
- No task accesses a network, Docker, `.env`, or external release root. Public JSON redacts raw URLs.

---

### Task 18: Platform-neutral recipe and candidate policy

**Files:** Create `src/asterion/applications/prime_agent/operator/release_recipe.py` and `tests/test_prime_release_recipe.py`; modify `image_input_lock.py`, `tests/test_prime_image_input_lock.py`, `tools/materialize_prime_ipython_inputs.py`, and `tests/test_prime_release_spec_generation.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class PrimeSourceTriple:
    commit: str
    tree_sha256: str
    package_lock_sha256: str

@dataclass(frozen=True)
class ReleaseRecipe:
    source: PrimeSourceTriple
    recipe_revision: str
    python_major_minor: str
    node_version: str
    base_distribution: str
    libc: str
    python_dependency_lock_sha256: str
    frontend_recipe_sha256: str

@dataclass(frozen=True)
class CandidateTargetPolicy:
    targets: tuple[ImagePlatformDescriptor, ...]

def validate_release_recipe(value: object) -> ReleaseRecipe: ...
def resolve_candidate_target(target: object) -> ImagePlatformDescriptor: ...
```

- [ ] **Step 1: Write failing tests.** Assert the exact pinned source and `python_major_minor == "3.11"`; assert no recipe platform field. Assert exact arm64/amd64 candidates succeed and `v8`, Darwin, s390x, mapping, substitute, unsorted and duplicate policies raise the public error. Replace the synthetic-amd64 authority assertion with an empty catalog and failed arm64 promoted resolution. Also assert a caller-created non-default catalog cannot resolve a synthetic lock; update every affected caller/test to pass an explicit reviewed lock or a test-local lock.
- [ ] **Step 2: Verify RED.** Run `uv run python -m unittest -v tests.test_prime_release_recipe tests.test_prime_image_input_lock`. Expected: recipe API absent and synthetic amd64 still authoritative.
- [ ] **Step 3: Implement minimally.** Reuse `ImagePlatformDescriptor` validation without host inspection. Bind every recipe scalar by identity to the code-owned recipe; require exact Prime source, Python 3.11, Node 22.8.0, Debian bookworm/glibc and lower-case SHA-256 fields. Implement one code-owned sorted policy and exact resolver. Move size-one data to private/test helper, set the default catalog empty, and retain verifier-only proof/no-follow validation. Promoted resolution accepts only the code-owned catalog, never a caller-supplied catalog. Change `image_input_lock_sha256(lock)` and `verify_image_input_artifact_set(root, lock)` to require explicit locks; make `verify_external_materialization(output_root, reviewed_lock)` require the same explicit lock; update focused tests to use only test-local synthetic locks.
- [ ] **Step 4: Verify GREEN.** Run the RED command plus `uv run ruff check src/asterion/applications/prime_agent/operator/release_recipe.py src/asterion/applications/prime_agent/operator/image_input_lock.py tests/test_prime_release_recipe.py tests/test_prime_image_input_lock.py`, `uv run pyright` on the same files, and `git diff --check`.
- [ ] **Step 5: Commit.** Stage exactly the four owned files and commit `feat(prime): define platform-neutral release recipe`.

### Task 19: Metadata-to-object acquisition claims

**Files:** Modify `src/asterion/applications/prime_agent/operator/release_spec_generation.py` and `tests/test_prime_release_spec_generation.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class MetadataBlob:
    parser_revision: str
    size: int
    sha256: str

@dataclass(frozen=True)
class ObjectBlob:
    url: str
    size: int
    sha256: str

@dataclass(frozen=True)
class MetadataObjectClaim:
    artifact_kind: str
    artifact_path: str
    metadata: MetadataBlob
    object: ObjectBlob
    declared_object_size: int
    declared_object_sha256: str
```

- [ ] **Step 1: Write failing tests.** Replace the identical metadata/object fixture with differently sized and hashed blobs. Assert canonical untrusted JSON carries separate records and `url_sha256`, never raw URL. Reject parser-revision drift, declaration/object mismatch, non-recipe source, target outside candidate policy, duplicate path/locator and missing metadata claim. Retain redaction and proof/parser separation tests.
- [ ] **Step 2: Verify RED.** Run `uv run python -m unittest -v tests.test_prime_release_spec_generation`. Expected: existing capture code requires equal metadata/object bytes and lacks recipe/policy admission.
- [ ] **Step 3: Implement minimally.** Replace `AcquisitionCapture` with the three frozen records. Parse exact JSON shapes only; validate HTTPS locator without credentials/query/fragment, non-boolean non-negative sizes, lower-case hashes, sorted unique paths/locator hashes, exact parser revision and declaration-to-object equality. Extend request with `ReleaseRecipe`; validate singleton recipe and resolve target through candidate policy. Preserve `candidate-native` only for exact Linux/native/non-emulated, always untrusted.
- [ ] **Step 4: Verify GREEN.** Run `uv run python -m unittest -v tests.test_prime_release_spec_generation tests.test_prime_release_recipe tests.test_prime_image_input_lock`, then ruff/pyright on changed files and `git diff --check`.
- [ ] **Step 5: Commit.** Stage the two owned files and commit `feat(prime): bind acquisition metadata to release objects`.

### Task 20: Decouple authorized staging from promotion

**Files:** Modify `src/asterion/applications/prime_agent/operator/image_input_lock.py`, `tools/materialize_prime_ipython_inputs.py`, `tests/test_prime_image_release_materializer.py`, and `tests/test_prime_image_input_lock.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class ReleaseSpecification:
    recipe: ReleaseRecipe
    platform: ImagePlatformDescriptor
    artifacts: tuple[ReleaseArtifact, ...]

def validate_release_specification(value: object) -> ReleaseSpecification: ...
def plan_materialization(output_root: Path, platform: ImagePlatformDescriptor) -> MaterializationPlan: ...
```

- [ ] **Step 1: Write failing tests.** Change `_spec()` to the singleton recipe and arm64 candidate. Assert planning/staging accepts arm64 while promoted resolution fails. Reject before fetch non-candidate, target mismatch, recipe substitute, wrong source, raw URL leakage and proof construction. Retain authorization, redirect, fresh-root, no-follow, replay, size and digest tests.
- [ ] **Step 2: Verify RED.** Run `uv run python -m unittest -v tests.test_prime_image_release_materializer tests.test_prime_image_input_lock`. Expected: staging resolves the promoted catalog before a candidate proposal can exist.
- [ ] **Step 3: Implement minimally.** Make `ReleaseSpecification` own `ReleaseRecipe`, validate recipe/candidate target before fetch, and make planning carry recipe digest plus descriptor without resolving promoted locks. Retain one-use authorization, redirect rejection, no-follow writes and post-write size/hash verification. Return only untrusted proposal. Leave `verify_external_materialization` promoted-lock-only.
- [ ] **Step 4: Verify GREEN.** Run `uv run python -m unittest -v tests.test_prime_image_release_materializer tests.test_prime_release_spec_generation tests.test_prime_release_recipe tests.test_prime_image_input_lock`, ruff/pyright for the two changed staging files, and `git diff --check`.
- [ ] **Step 5: Commit.** Stage exactly the four owned files and commit `feat(prime): stage candidate targets without promotion`.

## Self-review

- Task 18 removes false synthetic authority before a proposal can depend on it.
- Task 19 makes real metadata claims possible without granting promotion.
- Task 20 breaks the promotion cycle without weakening staging authorization or the full-set verifier.
- No task downloads, builds, runs an image, or promotes either platform.

---

### Task 21: Canonical recipe identity and authority types

Files: modify `src/asterion/applications/prime_agent/operator/release_recipe.py`, `src/asterion/applications/prime_agent/operator/image_input_lock.py`, `tests/test_prime_release_recipe.py`, and `tests/test_prime_image_input_lock.py`.

Interfaces: add `MetadataParserRevisions` with exact Node SHASUMS, PyPI JSON, OCI index, OCI manifest, recipe-output-manifest, and claim-binding revisions. Extend `ReleaseRecipe` with `fixture_recipe_sha256`, `artifact_graph_revision`, and `metadata_parsers`. Add `canonical_release_recipe_json(recipe)`, `release_recipe_sha256(recipe)`, `VerifiedCandidateArtifactSet`, and opaque `PromotedImageInput`.

- [ ] Step 1: Write failing tests. Mutate every scalar and nested parser revision, asserting recipe digest changes; assert canonical digest determinism and no platform/URL/path fields. Assert candidate verification cannot construct promoted evidence and empty catalog remains empty. Task 22 and Task 23, not this task, add recipe identity to public proposals and plans.
- [ ] Step 2: Verify RED with `uv run python -m unittest -v tests.test_prime_release_recipe tests.test_prime_image_input_lock`; expected missing digest/authority APIs.
- [ ] Step 3: Implement the minimum. Canonical sorted compact JSON covers every nested field and SHA-256 is outside the recipe. Keep singleton recipe identity, opaque code-owned promoted construction, distinct untrusted candidate evidence, empty catalog, and no proposal-to-promotion converter.
- [ ] Step 4: Verify GREEN using the focused tests, ruff, pyright, and `git diff --check`.
- [ ] Step 5: Commit exact owned files with `feat(prime): bind candidate closures to canonical recipes`.

### Task 22: Offline parsed metadata and complete target artifact graph

Files: create `src/asterion/applications/prime_agent/operator/release_metadata.py` and `tests/test_prime_release_metadata.py`; modify `src/asterion/applications/prime_agent/operator/release_spec_generation.py` and `tests/test_prime_release_spec_generation.py`.

Interfaces: define offline `parse_node_shasums(data, selector)`, `parse_pypi_json(data, selector)`, `parse_oci_index_descriptor(data, selector)`, `parse_oci_manifest_descriptor(data, selector)`, and `parse_recipe_output_manifest(data, selector)`. Parser-produced declarations have guarded construction. Private input holds `repr=False` locator and metadata bytes; output holds only public claim/evidence projections.

- [ ] Step 1: Write failing literal-bytes tests: Node 22.8.0 arm64/x64 SHASUMS selection/duplicates/no declared size; PyPI project/version/file/size/digest and Python 3.11 target-wheel tags; exact OCI index child then config/contiguous layers; recipe-output source/recipe/scope/target binding. Reject metadata mutation, caller-made declaration, missing/extra/duplicate/unordered slots and arm64/amd64 artifact exchange. Assert result/repr/str/JSON never has URL/host/path sentinel.
- [ ] Step 2: Verify RED with `uv run python -m unittest -v tests.test_prime_release_metadata tests.test_prime_release_spec_generation`; expected parser module and complete graph admission missing.
- [ ] Step 3: Implement minimum offline parsers and public projection. Require exactly selected OCI child/config/layers, target Node archive/modules, one exact wheel per code-owned closure plus local prime-agent-runtime 0.1.0, fixtures, frontend. Bind target-specific filename/tag/path/manifest/output to descriptor. No fetch/write/promotion/host inspection; proposal remains untrusted.
- [ ] Step 4: Verify GREEN with parser/generation/recipe/image-lock suites, ruff, pyright, and `git diff --check`.
- [ ] Step 5: Commit exact owned files with `feat(prime): require parsed complete target closures`.

### Task 23: Descriptor-relative authorized candidate staging

Files: modify `tools/materialize_prime_ipython_inputs.py` and `tests/test_prime_image_release_materializer.py`.

- [ ] Step 1: Write failing tests: plan carries full recipe SHA-256; incomplete graph/recipe/source/target drift rejects pre-fetch; symlink substitution cannot escape pinned root; every descendant opens with `dir_fd`, `O_DIRECTORY`, `O_NOFOLLOW`; absent descriptor APIs fail closed. Keep token/action/redirect/overrun/underrun/hash/post-write/public-redaction tests and assert both candidates fail promoted resolution.
- [ ] Step 2: Verify RED with `uv run python -m unittest -v tests.test_prime_image_release_materializer`; expected dependency-lock-only plan and path-based traversal.
- [ ] Step 3: Implement minimum. Use recipe digest and complete graph validation before first fetch. Pin external parent and operate only descriptor-relatively: leaf check/mkdir, component mkdir/open with `dir_fd|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC`, leaf `O_CREAT|O_EXCL|O_NOFOLLOW`, fstat and descriptor revalidation. No fallback. Keep authorization-before-fetch, exact redirect, bounds/hash checks, URL-free untrusted result.
- [ ] Step 4: Verify GREEN with materializer/metadata/generation/recipe/image-lock suites, ruff, pyright, and `git diff --check`.
- [ ] Step 5: Commit exact owned files with `feat(prime): stage complete candidate closures safely`.

## Corrective self-review

- Tasks 21–23 close the final-review blockers: recipe identity, parsed metadata bytes, complete target graph, URL privacy, and descriptor-relative staging.
- They still do not acquire real artifacts, build/run images, promote targets, or produce native/bounded PASS.
