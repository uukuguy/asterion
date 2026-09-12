# Prime P1 Resource-Set Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Derive one opaque, deterministic `resource_set_sha256` from every admitted P1 authority resource so a future authenticated ready frame cannot name a constant or partial resource set.

**Architecture:** Each private admitted child exposes only an underscore-level canonical identity byte contribution to the aggregate. The aggregate validates exact child types, hashes fixed domain-separated length-delimited contributions in acquisition order, and makes the final lowercase digest available only to authority-process code. It rejects closed, substituted, malformed, or revalidation-failed resources. It does not connect Docker, write evidence, read model credentials beyond pre-existing config admission, create an IPC frame, or execute a workload.

## Constraints

- Bind authority artifact lock, fixed application-resource lock, static image/seccomp identity, evidence-root inode identity, Docker executable byte digest/identity, and Docker socket identity plus expected daemon projection.
- Contributions contain no path/config string/credential/prompt/output. Use identities already retained on admitted objects; never reopen a configured path or introduce discovery.
- Revalidate Docker executable/socket at the last safe static point; an unavailable/closed child fails with `PrimeP1AuthorityResourceError` and public-safe text.
- Digest algorithm is SHA-256 of `asterion.prime-p1.resource-set/v1\\0` followed by typed, sorted-field canonical binary contributions; no caller supplies keys/values.
- Add mutation/order/closed/revalidation/redaction tests. No Docker/network/subprocess/model/ready/execute effect.

### Task 1: Opaque complete resource-set digest

**Files:**

- Modify: `src/asterion/applications/prime_agent/operator/authority_resources.py`
- Modify: `src/asterion/applications/prime_agent/operator/authority_artifact_lock.py`
- Modify: `src/asterion/applications/prime_agent/operator/authority_application_resources.py`
- Modify: `src/asterion/applications/prime_agent/operator/authority_evidence.py`
- Modify: `src/asterion/applications/prime_agent/operator/authority_docker_executable.py`
- Modify: `src/asterion/applications/prime_agent/operator/authority_docker_socket.py`
- Modify: `src/asterion/applications/prime_agent/operator/resources/authority-artifact-lock.json`
- Modify: `tests/test_prime_p1_authority_resources.py`
- Create: `tests/test_prime_p1_resource_set_identity.py`

- [ ] Write RED tests proving deterministic exact digest, changed child contribution changes digest, all six contributions matter, closed children fail, Docker executable/socket revalidation failures fail before a digest, and no public error leaks sentinels.
- [ ] Implement private canonical contribution methods and aggregate `_resource_set_sha256()` with exact type/liveness checks and domain-separated length-delimited encoding.
- [ ] Update the authority artifact descriptor hashes after sources stabilize and verify descriptor admission.
- [ ] Run focused authority-resource/process/socket tests plus Ruff/diff check; commit `feat: bind complete Prime P1 resource set`.
