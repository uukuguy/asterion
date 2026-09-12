# Prime Capability Program P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the runnable Prime application's source lock, restricted-worker contract, and public-safe evidence ladder before any model-backed Prime capability is implemented.

**Architecture:** Add product-specific Prime application support under `src/asterion/applications/prime_agent/`; do not modify generic framework contracts or reimplement the upstream kernel/RLM.  The restricted-worker profile is an operator-injected OCI worker contract; OrbStack/Docker is an eligible local implementation only when it proves digest-pinned image, disposable mount, network denial, and absent credentials.

**Tech Stack:** Python 3.12 `dataclasses`/`unittest`, existing installed-application provider pattern, SHA-256, OCI-compatible operator worker.

## Global Constraints

- `3th-party/prime-agent` remains read-only and pinned to an exact Git commit.
- `make test`, `make check`, and promotion checks perform zero provider calls.
- Rust controlled executor is not a sandbox and cannot satisfy restricted acceptance.
- Public results contain only fixed status, opaque IDs, digests, counters, and relative artifact IDs.
- Formal acceptance requires an injected restricted worker; trusted-local runs are labeled and non-promotable.

---

### Task 1: Restricted-worker profile contract

**Files:**
- Create: `src/asterion/applications/prime_agent/__init__.py`
- Create: `src/asterion/applications/prime_agent/restricted_worker.py`
- Create: `tests/test_prime_restricted_worker.py`

**Interfaces:**
- Produces `PrimeRestrictedWorkerProfile(image_digest, network_mode, workspace_mode, credential_mode, max_runtime_seconds, max_output_bytes)`.
- Produces `validate_prime_restricted_worker(profile)` and fails closed unless image is digest-pinned, network is `none`, workspace is `disposable`, credentials are `absent`, and finite limits are positive.

- [ ] **Step 1: Write failing validation tests**

```python
def test_profile_requires_closed_sandbox_properties(self):
    profile = PrimeRestrictedWorkerProfile(
        image_digest="sha256:" + "a" * 64,
        network_mode="none", workspace_mode="disposable",
        credential_mode="absent", max_runtime_seconds=300, max_output_bytes=65536,
    )
    self.assertEqual(validate_prime_restricted_worker(profile), profile)
```

- [ ] **Step 2: Run the focused test**

Run: `uv run python -m unittest -v tests.test_prime_restricted_worker`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the frozen profile and closed validator**

```python
@dataclass(frozen=True)
class PrimeRestrictedWorkerProfile:
    image_digest: str
    network_mode: Literal["none"]
    workspace_mode: Literal["disposable"]
    credential_mode: Literal["absent"]
    max_runtime_seconds: int
    max_output_bytes: int
```

Reject every other literal, mutable mapping, non-digest image, non-positive limit, or unexpected field with `PrimeRestrictedWorkerError`.

- [ ] **Step 4: Run the focused test matrix**

Run: `uv run python -m unittest -v tests.test_prime_restricted_worker`

Expected: PASS, including network/credential/mount/digest/limit rejection cases.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent tests/test_prime_restricted_worker.py
git commit -m "feat(prime): define restricted worker profile"
```

### Task 2: Exact upstream lock and evidence levels

**Files:**
- Create: `src/asterion/applications/prime_agent/source_lock.py`
- Create: `src/asterion/applications/prime_agent/evidence.py`
- Create: `tests/test_prime_source_lock.py`
- Create: `tests/test_prime_capability_evidence.py`

**Interfaces:**
- Produces `PrimeSourceLock(commit, tree_sha256, package_lock_sha256)` and `verify_prime_source_lock(root, lock)`.
- Produces immutable `PrimeEvidenceLevel` values: `provider-free`, `bounded-sandboxed`, and `full-authorized`; evidence can promote only within its exact scenario and level.

- [ ] **Step 1: Write failing lock/evidence tests**

```python
with self.assertRaises(PrimeSourceLockError):
    verify_prime_source_lock(source_root, wrong_lock)
self.assertFalse(can_promote("prime.arc-agi-3/v1", "bounded-sandboxed", "full-authorized"))
```

- [ ] **Step 2: Run focused tests**

Run: `uv run python -m unittest -v tests.test_prime_source_lock tests.test_prime_capability_evidence`

Expected: FAIL because the modules do not exist.

- [ ] **Step 3: Implement exact verification and non-promotable evidence**

Hash only canonical, declared source/package-lock inputs; reject symlinks, missing files, version drift, and non-canonical paths.  Define the seven scenario IDs as a sorted closed set and require a matching scenario ID for any PASS receipt.

- [ ] **Step 4: Run focused tests**

Run: `uv run python -m unittest -v tests.test_prime_source_lock tests.test_prime_capability_evidence`

Expected: PASS; a provider-free or ARC-subset receipt cannot claim broader PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent tests/test_prime_source_lock.py tests/test_prime_capability_evidence.py
git commit -m "feat(prime): lock source and evidence claims"
```

### Task 3: Installed Prime application discovery and safe preflight

**Files:**
- Create: `src/asterion/applications/prime_agent/provider.py`
- Create: `src/asterion/applications/prime_agent/preflight.py`
- Create: `tests/test_prime_application_provider.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces `create_provider()` with provider ID `prime-agent` and one metadata-only application `prime.capability-program@1.0.0`.
- Produces `prime_preflight(profile, source_lock)` that returns only `PASS` or fixed safe failure codes; it never starts a kernel, reads `.env`, or contacts a model.

- [ ] **Step 1: Write failing provider/preflight tests**

```python
provider = create_provider()
self.assertEqual(provider.provider_id, "prime-agent")
self.assertEqual(prime_preflight(profile, lock).status, "PASS")
```

- [ ] **Step 2: Run focused tests**

Run: `uv run python -m unittest -v tests.test_prime_application_provider`

Expected: FAIL because the entry point is absent.

- [ ] **Step 3: Implement metadata-only discovery and provider-free preflight**

Register the application entry point using the existing installed-provider pattern.  Preflight validates only the injected profile and source lock; it returns fixed codes `worker-invalid`, `worker-unavailable`, or `source-invalid` and never exposes paths, commands, credentials, or source contents.

- [ ] **Step 4: Run package gates**

Run: `uv run python -m unittest -v tests.test_prime_application_provider && make promotion-check && git diff --check`

Expected: PASS with zero provider operations.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/asterion/applications/prime_agent tests/test_prime_application_provider.py
git commit -m "feat(prime): add capability program preflight"
```

## Self-review

- P0 covers the specification's upstream lock, evidence ladder, sandbox gate, and runnable application entry point.
- It deliberately does not create IPython, RLM, Harness, or ARC execution: those require the P0 contracts and are later phases.
- All named symbols are introduced in their producing task; no provider-backed command appears in the verification steps.
