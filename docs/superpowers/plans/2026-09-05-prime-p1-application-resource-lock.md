# Prime P1 Application Resource Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make production P1 authority reject changed fixed application inputs before Docker, socket, readiness, or model activity.

**Architecture:** A private package-owned descriptor enumerates exact non-code resources of the closed `prime.ipython-coding/v1` request contract. A strict no-follow byte verifier admits this set as an opaque aggregate child immediately after the authority artifact lock and before static/Docker resources. It validates resource identities against the canonical request contract and never discovers a package, assembly, image, prompt, command, or host path at runtime.

**Tech Stack:** Python 3.10+, `unittest`, `hashlib`, canonical JSON, existing authority artifact-lock conventions.

## Global Constraints

- Accept only fixed P1 application `prime.ipython-coding@1.0.0`, package `prime-agent@1.0.0`, implementation `prime.ipython-coding@1.0.0`, runtime `prime.agent`, and sole tool `ipython`.
- Descriptor entries use exact sorted unique relative POSIX paths and lowercase SHA-256 values. Do not expose paths, values, prompt/source text, Docker, network, subprocess, model, readiness, receipt, or execute behavior.
- Lock exactly: P1 assembly; capability package manifest; capability manifest; package fixture; image fixture lock; fixed starter; fixed oracle; fixed launcher.
- Reject absent, extra, substituted, symlinked, nonregular, hard-linked, group/world-writable, oversized, changed-during-read, or digest-mismatched resources with the existing redacted resource error.
- Descriptor-relative no-follow opens and pre/post identity checks are required. Aggregate order is artifacts, application resources, static, evidence, Docker executable, socket; closure is exact reverse.

---

### Task 1: Exact fixed P1 application-resource admission

**Files:**

- Create: `src/asterion/applications/prime_agent/operator/authority_application_resources.py`
- Create: `src/asterion/applications/prime_agent/operator/resources/prime-p1-application-resource-lock.json`
- Modify: `src/asterion/applications/prime_agent/operator/authority_resources.py`
- Modify: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`
- Create: `tests/test_prime_p1_authority_application_resources.py`
- Modify: `tests/test_prime_p1_authority_resources.py`

**Interfaces:**

- Produces private `admit_prime_p1_application_resources() -> AdmittedPrimeP1ApplicationResources`; `close() -> None` is idempotent/redacted and retains no public path or FD.
- `AdmittedProductionAuthorityResources` owns an exact `AdmittedPrimeP1ApplicationResources` child.

- [ ] Write failing boundary tests for exact package-resource admission, redacted rejection of an injected verifier error, descriptor schema/path/digest mutation, symlink/FIFO/hardlink rejection, and aggregate acquisition/cleanup ordering.
- [ ] Run `uv run python -m unittest -v tests.test_prime_p1_authority_application_resources tests.test_prime_p1_authority_resources` and record the expected missing-module failure.
- [ ] Implement an exact JSON descriptor whose keys are `protocol`, `identity`, `resources`; its identity keys are exactly `application_id`, `application_version`, `assembly_ref`, `package_ref`, `implementation_ref`, `runtime_id`, `workload_sha256`, `oracle_sha256`. Validate them against `authority_request_contract` canonical values. Resource entries are only `path` and `sha256`, and exactly name the eight resources above.
- [ ] Use fixed package roots and bounded descriptor-relative no-follow reads with full before/after admissibility plus constant-time SHA-256 comparison. No resource list may choose a filesystem target.
- [ ] Integrate aggregate acquisition after `admit_authority_artifact_lock()` and before static resources; exact-type validate and close children once in reverse order. Update the authority artifact descriptor to lock the new Python module after its bytes stabilize.
- [ ] Run `uv run python -m unittest -v tests.test_prime_p1_authority_application_resources tests.test_prime_p1_authority_resources tests.test_prime_p1_authority_process tests.test_prime_p1_authority_docker_socket`, then focused Ruff and `git diff --check`; commit as `feat: lock Prime P1 application resources`.
