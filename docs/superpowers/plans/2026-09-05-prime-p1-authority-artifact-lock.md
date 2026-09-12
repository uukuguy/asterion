# Prime P1 Authority Artifact Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse P1 authority startup unless its installed authority artifact set exactly matches a package-owned lock.

**Architecture:** A private operator module owns a closed descriptor set for the authority entry module and its direct authority dependencies.  It opens every installed artifact without following links, validates a regular non-group/world-writable file, bounds and hashes bytes, and returns an opaque retained admission object. `admit_production_authority_resources()` acquires this artifact resource before all existing P1 resources and releases it in reverse order. This is a static file verification only: it must not contact Docker, create a socket, emit readiness, or call a model.

**Tech Stack:** Python 3.10+, `unittest`, `hashlib`, `importlib.resources`, existing Prime P1 operator resource conventions.

## Global Constraints

- Preserve the generic framework/application dependency direction; only `asterion.applications.prime_agent.operator` changes.
- The packaged lock has exact, sorted, unique relative POSIX paths and lowercase SHA-256 values; no runtime enrolment, source scanning, package discovery, fallback, or mutable operator configuration.
- Resolve only package-owned resources; reject absolute paths, traversal, symlinks, non-regular files, group/world writable files, oversized inputs, identity changes during a read, malformed/extra/missing descriptor fields, and digest mismatch.
- Public failures are `PrimeP1AuthorityResourceError` with no path, digest, configuration, Docker, or source error context.
- Admission has no Docker, network, subprocess, readiness, receipt, or provider effect. On failure it closes all owned FDs/resources exactly once.
- Tests run on Darwin as well as Linux; no host platform is inferred.

---

### Task 1: Packaged authority artifact admission

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/authority_artifact_lock.py`
- Create: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`
- Modify: `src/asterion/applications/prime_agent/operator/authority_resources.py`
- Modify: `tests/test_prime_p1_authority_resources.py`
- Create: `tests/test_prime_p1_authority_artifact_lock.py`

**Interfaces:**
- Consumes: `PrimeP1AuthorityResourceError` from `authority_resources.py` only through the existing resource-admission boundary.
- Produces: `admit_authority_artifact_lock() -> AdmittedPrimeP1AuthorityArtifacts`, whose `close() -> None` is idempotent; a private `AdmittedProductionAuthorityResources` retains it as its first child.
- Produces: an immutable package resource with exact keys `protocol`, `authority_version`, and `artifacts`; each artifact has exactly `path` and `sha256` and paths are sorted/unique.

- [ ] **Step 1: Write failing public-behaviour tests**

```python
def test_admits_only_the_exact_packaged_authority_artifact_set(self) -> None:
    resource = admit_authority_artifact_lock()
    self.addCleanup(resource.close)
    self.assertEqual(repr(resource), "AdmittedPrimeP1AuthorityArtifacts(redacted)")

def test_rejects_a_digest_or_regular_file_change_without_leaking_the_path(self) -> None:
    with mock.patch(f"{MODULE}._read_verified_artifact", side_effect=ValueError("sentinel/path")):
        with self.assertRaises(PrimeP1AuthorityResourceError) as caught:
            admit_authority_artifact_lock()
    self.assertEqual(str(caught.exception), "prime P1 authority resource is unavailable")
    self.assertNotIn("sentinel", str(caught.exception))

def test_production_aggregate_acquires_artifacts_first_and_closes_them_last(self) -> None:
    # Patch each child admission to record acquisition/close order.
    # Expect: artifacts, static, evidence, docker executable, socket;
    # then socket, docker executable, evidence, static, artifacts.
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_artifact_lock tests.test_prime_p1_authority_resources`

Expected: failure because `authority_artifact_lock` and `admit_authority_artifact_lock` do not exist.

- [ ] **Step 3: Add the immutable descriptor and minimal no-follow verifier**

```python
def admit_authority_artifact_lock() -> AdmittedPrimeP1AuthorityArtifacts:
    try:
        descriptor = _load_packaged_descriptor()
        for artifact in descriptor.artifacts:
            _read_verified_artifact(_package_root(), artifact)
        return AdmittedPrimeP1AuthorityArtifacts(_TOKEN)
    except BaseException:
        raise PrimeP1AuthorityResourceError() from None
```

The descriptor loader must read the exact package resource once, parse canonical UTF-8 JSON, reject every schema deviation, and verify the declared artifact set against a code-owned tuple. `_read_verified_artifact` must traverse from the resolved package root without a symlink or parent escape, open with `O_NOFOLLOW|O_CLOEXEC` when available, check a single-link regular file with no group/world write mode, read at most the explicit cap plus one byte, compare `fstat` identity before/after, and compare SHA-256 with `hmac.compare_digest`. The opaque object must not expose paths, digest values, descriptor contents, or FDs.

The resource JSON must name the current exact files required to run P1 authority (`authority_process.py`, `authority_config.py`, `authority_resources.py`, `authority_artifact_lock.py`, `authority_docker_executable.py`, `authority_docker_socket.py`, `authority_evidence.py`, `authority_seccomp.py`, `authority_receipt.py`, `authority_protocol.py`, and `authority_request_contract.py`) with their actual current SHA-256 values. Its `authority_version` must exactly equal the project distribution version and `protocol` must be a fixed P1-private literal.

- [ ] **Step 4: Integrate the artifact child into aggregate ownership**

```python
artifacts = admit_authority_artifact_lock()
static = admit_static_authority_resources(config)
evidence = admit_evidence_root(config)
docker = admit_docker_executable(config)
socket = admit_docker_socket(config)
return AdmittedProductionAuthorityResources(artifacts, static, evidence, docker, socket, _token=_TOKEN)
```

Validate exact types; on every failure close acquired resources once in reverse acquisition order. Keep the aggregate private and do not add ready/probe/execute calls.

- [ ] **Step 5: Run GREEN verification and static checks**

Run: `uv run python -m unittest -v tests.test_prime_p1_authority_artifact_lock tests.test_prime_p1_authority_resources tests.test_prime_p1_authority_process tests.test_prime_p1_authority_docker_socket`

Expected: PASS, with only existing platform-specific skips.

Run: `uv run ruff check src/asterion/applications/prime_agent/operator/authority_artifact_lock.py src/asterion/applications/prime_agent/operator/authority_resources.py tests/test_prime_p1_authority_artifact_lock.py tests/test_prime_p1_authority_resources.py && git diff --check`

Expected: exit 0.

- [ ] **Step 6: Commit the focused change**

```bash
git add src/asterion/applications/prime_agent/operator/authority_artifact_lock.py \
  src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json \
  src/asterion/applications/prime_agent/operator/authority_resources.py \
  tests/test_prime_p1_authority_artifact_lock.py tests/test_prime_p1_authority_resources.py
git commit -m "feat: lock Prime P1 authority artifacts"
```

## Self-review

- The task covers the redesign's first required production revalidation: packaged authority artifact lock plus distribution version; package/assembly/implementation/workload locks remain separate later slices.
- The plan does not let a descriptor or source scan select arbitrary files, nor does it create execution authority.
- The plan includes a real red test, lifecycle order assertion, no-effect boundary, and exact focused commands.
