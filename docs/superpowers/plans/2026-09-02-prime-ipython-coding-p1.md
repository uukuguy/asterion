# Prime IPython Coding P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the real restricted-worker and host-side model-broker boundaries required before `prime.ipython-coding/v1` can make a bounded-sandboxed claim.

**Architecture:** Python defines domain-neutral, typed lease and broker protocols; a Prime application integration supplies the fixed worker image and scenario-specific launcher. The worker backend, not a profile or the Rust controlled executor, produces host-verified attestation and cleanup receipts. The model broker retains operator credentials and exposes only a single bounded, revocable session capability outside the kernel environment.

**Tech Stack:** Python 3.12 `dataclasses`/`Protocol`/`unittest`; Docker-compatible operator worker only in explicitly bounded integration verification; existing host-service registry and redacted immutable mappings.

## Global Constraints

- `3th-party/prime-agent` stays read-only at the P0 exact lock.
- A worker request never contains arbitrary commands, host paths, environment mappings, credentials, prompts, or model/provider configuration.
- `make test`, `make check`, and `make promotion-check` remain provider-free and must not start a worker.
- The worker profile is not evidence of isolation; only an injected worker service's host-verified attestation and cleanup receipt may support a bounded-sandboxed claim.
- Public values contain fixed states, opaque IDs, digests, and counters only; no source, output, prompt, credential, socket, container, or private path text.
- Rust `executor.controlled` is not used as a sandbox backend.

---

### Task 1: Domain-neutral restricted worker lease contract

**Files:**
- Create: `src/asterion/services/restricted_worker.py`
- Modify: `src/asterion/services/__init__.py`
- Create: `tests/test_restricted_worker_service.py`

**Interfaces:**
- Produces `RestrictedWorkerRequest(role_id, image_digest, run_id, challenge_digest, max_runtime_seconds, max_output_bytes)`.
- Produces `RestrictedWorkerLease(worker_id, run_id, challenge_digest)` and `RestrictedWorkerAttestation(worker_id, run_id, challenge_digest, image_digest, network_isolated, root_read_only, workspace_disposable, credentials_absent, kernel_credential_absent, source_read_only, resource_limited)`.
- Produces `RestrictedWorkerCleanupReceipt(worker_id, run_id, challenge_digest, destroyed)` and async `RestrictedWorkerService.open(request, *, signal) -> AbstractAsyncContextManager[RestrictedWorkerLease]`, `attest(lease)`, and `cleanup_receipt(lease)`.

- [ ] **Step 1: Write failing closed-contract tests**

```python
request = RestrictedWorkerRequest(
    role_id="prime.ipython-coding", image_digest="sha256:" + "a" * 64,
    run_id="run-1", challenge_digest="sha256:" + "b" * 64,
    max_runtime_seconds=300, max_output_bytes=65536,
)
self.assertEqual(request.role_id, "prime.ipython-coding")
with self.assertRaises(RestrictedWorkerError):
    RestrictedWorkerAttestation(
        worker_id="worker-1", run_id="run-1", challenge_digest="sha256:" + "b" * 64,
        image_digest="sha256:" + "a" * 64, network_isolated=False,
        root_read_only=True, workspace_disposable=True, credentials_absent=True,
        kernel_credential_absent=True, source_read_only=True, resource_limited=True,
    )
```

- [ ] **Step 2: Run the focused test before implementation**

Run: `uv run python -m unittest -v tests.test_restricted_worker_service`

Expected: FAIL because `asterion.services.restricted_worker` does not exist.

- [ ] **Step 3: Implement immutable exact contracts**

```python
class RestrictedWorkerService(Protocol):
    def open(self, request: RestrictedWorkerRequest, *, signal: CancellationSignal | None = None) -> AbstractAsyncContextManager[RestrictedWorkerLease]: ...
    async def attest(self, lease: RestrictedWorkerLease) -> RestrictedWorkerAttestation: ...
    async def cleanup_receipt(self, lease: RestrictedWorkerLease) -> RestrictedWorkerCleanupReceipt: ...
```

Reject booleans where integers are required, non-digest image/challenge values, empty or non-canonical identifiers, mismatched receipt identities, false isolation controls, and unknown dataclass fields. Do not define a method that accepts a command, environment, mount path, image tag, or model secret.

- [ ] **Step 4: Verify the full provider-free matrix**

Run: `uv run python -m unittest -v tests.test_restricted_worker_service && uv run ruff check src/asterion/services/restricted_worker.py tests/test_restricted_worker_service.py`

Expected: PASS for identity mismatch, every false attestation control, invalid limit/digest, immutable values, and redacted representation tests.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/services/restricted_worker.py src/asterion/services/__init__.py tests/test_restricted_worker_service.py
git commit -m "feat(services): define restricted worker lease contract"
```

### Task 2: Bounded host-side model session contract

**Files:**
- Create: `src/asterion/services/bounded_model_session.py`
- Modify: `src/asterion/services/__init__.py`
- Create: `tests/test_bounded_model_session.py`

**Interfaces:**
- Consumes: `run_id` and host authority; never consumes a credential or model name from an assembly.
- Produces `BoundedModelSessionRequest(run_id, max_requests, max_input_bytes, max_output_bytes, deadline_seconds)`, opaque `BoundedModelSessionLease(session_id, run_id)`, and `BoundedModelSessionService.open(request)`, `revoke(lease)`.

- [ ] **Step 1: Write failing budget and redaction tests**

```python
request = BoundedModelSessionRequest(
    run_id="run-1", max_requests=2, max_input_bytes=32768,
    max_output_bytes=32768, deadline_seconds=300,
)
self.assertNotIn("secret", repr(BoundedModelSessionLease("session-1", "run-1")))
with self.assertRaises(BoundedModelSessionError):
    BoundedModelSessionRequest("run-1", 0, 32768, 32768, 300)
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_bounded_model_session`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the host-only broker protocol**

Provide only bounded count/byte/deadline metadata and opaque identity. The protocol has no field for API key, provider, model, prompt body, network endpoint, or a raw bearer capability; the Prime worker integration will receive a one-use local mediation channel from an operator-owned implementation, never this Python value.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_bounded_model_session && uv run ruff check src/asterion/services/bounded_model_session.py tests/test_bounded_model_session.py`

Expected: PASS for invalid budgets, identity mismatch, no secret-bearing fields, and immutable leases.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/services/bounded_model_session.py src/asterion/services/__init__.py tests/test_bounded_model_session.py
git commit -m "feat(services): define bounded model session contract"
```

### Task 3: Prime worker attestation gate

**Files:**
- Create: `src/asterion/applications/prime_agent/worker_gate.py`
- Create: `tests/test_prime_worker_gate.py`

**Interfaces:**
- Consumes the P0 `PrimeRestrictedWorkerProfile`, one `RestrictedWorkerLease`, attestation, and cleanup receipt.
- Produces `verify_prime_worker_boundary(profile, lease, attestation, cleanup) -> PrimeWorkerBoundaryReceipt` whose only public fields are identity digests/count-free IDs and `status` equal to `PASS`.

- [ ] **Step 1: Write failing boundary tests**

```python
receipt = verify_prime_worker_boundary(profile, lease, attestation, cleanup)
self.assertEqual(receipt.status, "PASS")
for changed in ("worker_id", "run_id", "challenge_digest", "image_digest"):
    with self.subTest(changed=changed), self.assertRaises(PrimeWorkerBoundaryError):
        verify_prime_worker_boundary(profile, lease, invalid_attestation, cleanup)
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_worker_gate`

Expected: FAIL because the gate does not exist.

- [ ] **Step 3: Implement one-way evidence admission**

Require exact identity equality and every host-verified control true, including `network_isolated`, `root_read_only`, `workspace_disposable`, `credentials_absent`, `kernel_credential_absent`, `source_read_only`, `resource_limited`, and `cleanup.destroyed`. Reject status upgrades, missing cleanup, and all raw worker evidence values. This task must not launch Docker or Prime.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_worker_gate tests.test_restricted_worker_service tests.test_prime_restricted_worker`

Expected: PASS including each individual attestation/identity/cleanup rejection.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/worker_gate.py tests/test_prime_worker_gate.py
git commit -m "feat(prime): gate worker attestation evidence"
```

## Self-review

- This P1 foundation fulfills Sol's hard precondition: it can distinguish static configuration from actual attested isolation without invoking an LLM or kernel.
- Tasks 1–3 are provider-free and do not claim a sandbox merely because their contracts pass; a concrete operator backend and the coding fixture are later P1 tasks.
- RLM recursion, long-session recovery, harness mutation, autonomy, and ARC remain out of scope until the bounded IPython coding receipt is real.

### Task 4: Fixed Docker role and closed engine transport

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/docker_worker.py`
- Create: `tests/test_prime_docker_worker.py`

**Interfaces:**
- Produces private `DockerWorkerRole` for the sole role `prime.ipython-coding` and an injected `DockerEngineTransport` protocol.
- Produces `DockerRestrictedWorkerService` implementing the existing `RestrictedWorkerService` contract without accepting arbitrary commands, paths, environments, image tags, mounts, or credentials.

- [ ] **Step 1: Write failing closed-role tests**

```python
with self.assertRaises(RestrictedWorkerError):
    service.request_for(RestrictedWorkerRequest("other.role", digest, "run-1", challenge, 30, 1024))
```

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker`

Expected: FAIL because the operator backend module is absent.

- [ ] **Step 3: Implement fixed role mapping and request admission**

The code-owned role maps only `prime.ipython-coding` to exact image ID/repository digest, fixed launcher, non-root UID/GID, and maxima. Request digest must equal the role digest and limits must be equal-or-stricter. The transport receives only a typed, internally created fixed create specification; it has no generic command or environment API. Prime boundary admission must additionally require this exact role.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_worker_gate && uv run ruff check src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py`

Expected: PASS for unknown role, tag-like digest, mismatched image, relaxed limits, command/env/mount injection, and role confusion rejection.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py
git commit -m "feat(prime): define fixed docker worker role"
```

### Task 5: Pre-start Docker inspection and attestation evidence

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/docker_worker.py`
- Modify: `tests/test_prime_docker_worker.py`

**Interfaces:**
- The injected transport exposes only create, inspect, start, and remove by opaque container identity.
- `DockerRestrictedWorkerService.open()` creates then validates inspect evidence before calling start; any missing or unsafe field raises a redacted `RestrictedWorkerError`.

- [ ] **Step 1: Write failing pre-start ordering and mutation tests**

```python
await service.open(request).__aenter__()
self.assertEqual(transport.calls[:2], ["create", "inspect"])
self.assertNotIn("start", transport.calls)
```

Add one failing subtest per changed inspect control: network, readonly rootfs, privileged/capabilities/NNP, uid, mounts, env, PID/memory/swap/CPU, and image identity.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker`

Expected: FAIL because pre-start inspection is absent.

- [ ] **Step 3: Implement closed inspect evidence validation**

Reject every unknown/missing/mismatched field before start. Require no mounts/devices/ports, `NetworkMode=none`, read-only root, non-privileged, cap-drop ALL, no-new-privileges, fixed non-root user, bounded cgroup values, exact safe environment, and only the bounded workspace tmpfs. Retain raw inspect data only privately.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_worker_gate && uv run ruff check src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py`

Expected: PASS; unsafe inspect never calls start and messages reveal no inspect content.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py
git commit -m "feat(prime): inspect docker worker before start"
```

### Task 6: Runtime self-check and post-start attestation

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/docker_worker.py`
- Modify: `tests/test_prime_docker_worker.py`

**Interfaces:**
- The fixed launcher returns a typed, redacted self-check record after start.
- Admission requires a second safe engine inspection and an exact self-check for no network, read-only root, only the disposable workspace writable, no credentials, zero effective capabilities, no-new-privileges, seccomp filtering, and the fixed non-root UID.

- [ ] **Step 1: Write failing post-start and self-check tests**

Use the fake transport only. Cover changed post-start inspect data, each missing or unsafe self-check control, and assert that no attestation is returned and the container is removed.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_worker_gate`

Expected: FAIL before runtime evidence admission exists.

- [ ] **Step 3: Implement fail-closed runtime evidence admission**

After `start`, re-inspect and validate the same closed engine controls, then require the typed launcher self-check. Keep raw engine/self-check values private and normalize failures to the existing redacted worker error. Do not invoke Docker or an LLM in tests.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_worker_gate && uv run ruff check src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py && uv run pyright src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py`

Expected: PASS with no attestation for unsafe runtime evidence.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py
git commit -m "feat(prime): attest docker worker after start"
```

### Task 7: Verified teardown and tombstone-only cleanup receipt

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/docker_worker.py`
- Modify: `tests/test_prime_docker_worker.py`

**Interfaces:**
- The narrow injected transport supports a fixed-role final inspection, force removal, and an opaque absence assertion; it exposes no arbitrary container command surface.
- A successful context exit validates the final engine evidence, force-removes the exact opaque container, proves absence, erases live lease/container state, and retains only the minimum identity-bound tombstone needed for `cleanup_receipt()`.

- [ ] **Step 1: Write failing teardown-order and stale-state tests**

Assert the exact successful order `inspect → force_remove → assert_absent` after operation use. Cover unsafe final inspection, remove failure, and absence failure: each must fail closed without a cleanup receipt. Assert the live lease record is erased after a successful close, role/request substitutions cannot use a tombstone, and no raw container data reaches an exception or receipt.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker`

Expected: FAIL before verified teardown exists.

- [ ] **Step 3: Implement verified teardown**

Do not turn generic Docker operations into a public API. Validate the final inspect with the existing closed controls, invoke only code-owned force removal, then require the injected absence assertion. Move exact lease identity to a minimal tombstone only after all three succeed; remove active request/container records. Failure may attempt best-effort removal but must not mint cleanup evidence.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_worker_gate && uv run ruff check src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py && uv run pyright src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py`

Expected: PASS; cleanup evidence proves the engine reported the exact container absent and cannot be replayed across worker identity.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py
git commit -m "feat(prime): verify docker worker teardown"
```

### Task 8: Cancellation-safe lifecycle and cleanup uncertainty

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/docker_worker.py`
- Modify: `tests/test_prime_docker_worker.py`

**Interfaces:**
- A private control value carries one absolute monotonic execution deadline, a later fixed cleanup deadline, and the read-only cancellation signal. It is passed to every pre-admission engine operation; no command may reset the execution deadline.
- All post-create rejection and cancellation paths use force removal plus absence proof. A lifecycle that cannot prove absence records no cleanup receipt and cannot be promoted.

- [ ] **Step 1: Write failing cancellation and post-start-rejection tests**

Cover cancellation before/during every lifecycle call, an unsafe post-start inspection or launcher check, cancellation during context exit, and force-remove/absence failure. Assert no ordinary `remove()` is used after a container exists; the exact opaque identity is force-removed and proven absent under shielded cleanup. Assert no attestation or cleanup receipt after cancellation/uncertainty.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker`

Expected: FAIL before cancellation-safe control and forced rejection cleanup exist.

- [ ] **Step 3: Implement cancellation-safe closed lifecycle**

Use `asyncio.CancelledError`-aware handling and `asyncio.shield` for bounded cleanup. Pass one code-owned absolute deadline through create, inspect, start, and self-check; use only the cleanup deadline for force removal/absence proof. Replace post-create `remove()` rejection cleanup with `force_remove → assert_absent`. If create is uncertain, delegate compensation/absence proof by the code-owned opaque preallocated identity; do not admit a lease or issue a receipt until certainty exists.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_worker_gate && uv run ruff check src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py && uv run pyright src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py`

Expected: PASS; cancellation/deadline and cleanup uncertainty never produce attestation, cleanup receipt, or a scenario PASS.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py
git commit -m "fix(prime): close docker worker cancellation cleanup"
```

### Task 9: Closed Docker CLI adapter with fake-process verification

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/docker_cli.py`
- Create: `tests/test_prime_docker_cli.py`

**Interfaces:**
- `DockerCliEngineTransport` is application/operator-owned and implements only the existing closed worker lifecycle transport. It may be constructed only with private operator configuration: an absolute Docker executable, an explicit local Unix socket, and the fixed role's pinned seccomp profile.
- A typed injected subprocess runner enables fake-process tests. No standard test command invokes Docker, reads credentials, or uses the network.

- [ ] **Step 1: Write failing closed-argv and raw-evidence tests**

Assert exact code-owned argv for the allowlisted lifecycle operations only: version/info preflight, image/container inspect, container create, start/attach, force remove, and exact-ID absence query. Reject relative executable paths, TCP/SSH contexts, tags, mismatched IDs, raw/malformed/partial inspect JSON, unexpected raw config fields, output caps, timeouts, and any user-derived argument/credential. Assert no `run`, `exec`, `cp`, `pull`, `logs`, `build`, shell, PATH lookup, or inherited Docker environment.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_docker_cli`

Expected: FAIL before the adapter exists.

- [ ] **Step 3: Implement closed subprocess translation**

Use only `asyncio.create_subprocess_exec` behind the injected runner with a bounded, cleared environment and absolute executable. Create uses a fixed code-owned argv, `--pull=never`, exact digest, fixed entrypoint/security controls, preallocated opaque identity, and no labels with run/challenge content. Parse complete supported Docker JSON shapes before producing the narrow normalized inspection/self-check values consumed by `DockerRestrictedWorkerService`; redact all failures. The absence query must distinguish daemon failure from verified exact absence.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_docker_cli tests.test_prime_docker_worker && uv run ruff check src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_cli.py && uv run pyright src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_cli.py`

Expected: PASS with fake processes only; provider-free gates never call a daemon.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_cli.py
git commit -m "feat(prime): add closed docker cli transport"
```

### Task 9.1: Bounded streaming Docker subprocess output

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/docker_cli.py`
- Modify: `tests/test_prime_docker_cli.py`

**Interfaces:**
- The production runner never calls a buffering API that can consume unbounded Docker stdout/stderr. It concurrently streams both pipes under one shared byte cap, kills and reaps the exact child on timeout or cap breach, and reports only the existing redacted worker error.

- [ ] **Step 1: Write failing oversized-stream and cleanup tests**

Use an injected/fake process with independently growing stdout and stderr. Assert a combined cap breach kills and waits for the process before failure; assert timeout has the same child-reaping behavior; assert no raw bytes appear in the exception.

- [ ] **Step 2: Implement bounded concurrent reads**

Read both streams incrementally and concurrently against a shared cap. On cap breach, timeout, cancellation, or stream failure, kill if needed and await child reaping before raising the redacted error. Do not use `Process.communicate()`.

- [ ] **Step 3: Verify and commit**

Run: `uv run python -m unittest -v tests.test_prime_docker_cli tests.test_prime_docker_worker && uv run ruff check src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_cli.py && uv run pyright src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_cli.py`

```bash
git add src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_cli.py
git commit -m "fix(prime): bound docker cli output streams"
```

### Task 10: Fixed launcher barrier and Linux-only backend probe contract

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/launcher_barrier.py`
- Create: `src/asterion/applications/prime_agent/operator/linux_probe.py`
- Create: `tests/test_prime_launcher_barrier.py`
- Create: `tests/test_prime_linux_probe.py`

**Interfaces:**
- The launcher barrier is a private, one-shot, exact run/challenge/worker binding. It cannot reveal a socket path, token, provider identity, model identity, prompt, or credential; Prime/kernel release is impossible until the host has recorded worker attestation and bound the barrier identity.
- The backend probe is injected and provider-free. It classifies unsupported platform, Docker Desktop/OrbStack, daemon/image/operator absence, and safety mismatch as non-PASS public states. Only a supported native Linux precondition can be `ready`, and readiness is explicitly not a scenario evidence receipt.

- [ ] **Step 1: Write failing barrier/probe matrices**

Assert release-before-attestation, cross-run/worker/challenge substitution, duplicate release, and any public-sensitive field fail closed. For platform matrices, assert Darwin/Desktop/OrbStack and unknown engines are `External-limited`; no injected probe action occurs unless native Linux preconditions are exact; a ready probe cannot construct `PrimeEvidenceReceipt` or `bounded-sandboxed`.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_launcher_barrier tests.test_prime_linux_probe`

Expected: FAIL before the contracts exist.

- [ ] **Step 3: Implement provider-free closed contracts**

Make barrier state private and one-shot; its host admission accepts only the existing typed worker lease/attestation identities. Make probe inputs private operator facts with exact redacted public classification. Do not shell out, invoke Docker, read `.env`, resolve an image, or invoke a model in either module.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_launcher_barrier tests.test_prime_linux_probe && uv run ruff check src/asterion/applications/prime_agent/operator/launcher_barrier.py src/asterion/applications/prime_agent/operator/linux_probe.py tests/test_prime_launcher_barrier.py tests/test_prime_linux_probe.py && uv run pyright src/asterion/applications/prime_agent/operator/launcher_barrier.py src/asterion/applications/prime_agent/operator/linux_probe.py tests/test_prime_launcher_barrier.py tests/test_prime_linux_probe.py`

Expected: PASS; no Docker/provider process invocation and no possible evidence-level upgrade.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/launcher_barrier.py src/asterion/applications/prime_agent/operator/linux_probe.py tests/test_prime_launcher_barrier.py tests/test_prime_linux_probe.py
git commit -m "feat(prime): add launcher barrier and linux probe"
```

### Task 11: Enforcing host model broker and private framed mediation

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/model_broker.py`
- Create: `tests/test_prime_model_broker.py`

**Interfaces:**
- The operator-owned broker accepts an existing bounded model-session lease plus an injected provider callable. Provider/model/credential/endpoint remain entirely inside that callable and never appear in request, lease, channel, receipt, repr, or exception.
- A private one-session, one-in-flight framed channel binds exact run/session/worker identity before release. It enforces cumulative request/input/output limits and one absolute deadline before every provider attempt. Revoke closes admission, waits for the in-flight call to quiesce, and emits only a body-free exact usage/terminal receipt.

- [ ] **Step 1: Write failing accounting and revocation matrices**

Use a fake provider. Assert request count is reserved before invocation; input/output caps are cumulative; retries consume attempts; concurrent calls are rejected; expired/revoked sessions do not call the provider; exact identity substitutions fail; revoke waits for an in-flight call; all public values/reprs/errors omit prompt body, answer body, credentials, provider/model/endpoint, channel/token/socket.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_model_broker`

Expected: FAIL before enforcing broker exists.

- [ ] **Step 3: Implement private framed mediation**

Keep frames internal to the operator/launcher boundary. The broker may pass model text only through the private frame to the launcher-facing channel; it must never put raw content in a public receipt. Enforce an absolute monotonic deadline, one in-flight call, and cumulative bounds under a lock. Revoke must prevent new frames and quiesce in-flight work before yielding its receipt. Do not resolve `.env`, provider choice, credentials, or network endpoints.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_model_broker && uv run ruff check src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py && uv run pyright src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py`

Expected: PASS with fake provider only; no real model, credential, or network action.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py
git commit -m "feat(prime): add enforcing model broker"
```

### Task 11.1: Deadline, proof, and accounting hardening for the model broker

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/model_broker.py`
- Modify: `tests/test_prime_model_broker.py`

- [ ] **Step 1: Write failing adversarial tests**

Cover a never-returning provider timed out at the broker absolute deadline, a provider-originated `CancelledError` carrying sentinel secret text, forged directly constructed launcher proof, and an over-limit output attempt that consumes cumulative output accounting and closes future admission.

- [ ] **Step 2: Implement fail-closed hardening**

Bound the provider await by remaining absolute deadline. Normalize provider-originated cancellation/error text to the public broker error while retaining only genuine caller cancellation semantics. Replace constructible release proof with a per-broker unforgeable identity token bridged only by the actual barrier release. Charge attempted output bytes before cap rejection and revoke when any cumulative bound is exceeded.

- [ ] **Step 3: Verify and commit**

Run: `uv run python -m unittest -v tests.test_prime_model_broker && uv run ruff check src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py && uv run pyright src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py`

```bash
git add src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py
git commit -m "fix(prime): harden model broker admission"
```

### Task 11.2: Host-private broker coordinator and quiescence terminal

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/model_broker.py`
- Modify: `tests/test_prime_model_broker.py`

**Decision:** Python underscore names, object tokens, and closures are not an ACL for an importer that has a broker object. The TCB is host Python coordinator + `PrimeLauncherBarrier` + provider adapter. The restricted worker receives only a channel over the future IPC boundary, never the coordinator/broker object or an activation method. If arbitrary hostile code can introspect or monkeypatch host objects, only a process/IPC boundary may claim non-forgeability.

- [ ] **Step 1: Write failing coordinator and non-quiescence matrices**

Assert public worker-facing values expose only the request channel (no broker, coordinator, release/activation callable). Assert direct imports, constructors, getters, and prior proof routes cannot mint a channel. Cover provider sync/async `CancelledError` redaction, outer cancellation propagation, deadline/revoke cancellation suppression, retained in-flight task, and the terminal `cleanup-uncertain` state. A provider that fails to terminate by the fixed cleanup grace may never yield a revoked/quiesced receipt even if it later ends; all future admission fails closed.

- [ ] **Step 2: Implement host-private coordination**

Replace proof/token activation with a coordinator-owned factory that calls the real launcher barrier action then mints the channel internally. Do not make this a public capability handed to worker code. Invoke provider inside a tracked task so sync and async cancellation are normalized correctly. Keep a strong in-flight reference until terminal and consume its result. After cancellation begins, wait only the fixed cleanup grace: terminal completion permits a body-free revoked receipt; noncompletion produces the non-promotable cleanup-uncertain terminal and blocks all receipt/admission success.

- [ ] **Step 3: Verify and commit**

Run: `uv run python -m unittest -v tests.test_prime_model_broker && uv run ruff check src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py && uv run pyright src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py`

```bash
git add src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py
git commit -m "fix(prime): isolate broker coordination"
```

### Task 11.3: Opaque framed channel and output-cap terminal closure

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/model_broker.py`
- Modify: `tests/test_prime_model_broker.py`

- [ ] **Step 1: Write failing object-graph and output-terminal tests**

From a worker-facing channel, recursively inspect normal attributes and assert no coordinator, broker, provider, barrier, release, activation, revoke, usage, or callable that can invoke provider is reachable. Verify the channel can only submit an exact framed request to host-owned mediation. After any attempted output exceeds the cumulative cap, assert the broker latches a terminal admission-closed state and a second request never invokes the provider.

- [ ] **Step 2: Implement opaque request mediation**

Replace the channel-to-coordinator reference with paired framed endpoints: the worker-facing channel contains only its request/response transport and fixed identity, while host-owned coordinator consumes/validates frames and invokes provider. Keep host authority solely on the host endpoint. This is an in-process test transport for the eventual separate IPC boundary, not a claim that a hostile host interpreter is sandboxed. On observed over-cap output, charge bytes, latch closed/revoked admission, and reject every later frame before provider invocation.

- [ ] **Step 3: Verify and commit**

Run: `uv run python -m unittest -v tests.test_prime_model_broker && uv run ruff check src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py && uv run pyright src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py`

```bash
git add src/asterion/applications/prime_agent/operator/model_broker.py tests/test_prime_model_broker.py
git commit -m "fix(prime): seal model broker channel"
```

### Task 12: Fixed coding-fixture receipt truth table

**Files:**
- Create: `src/asterion/applications/prime_agent/coding_fixture_receipt.py`
- Create: `tests/test_prime_coding_fixture_receipt.py`

**Interfaces:**
- An internal fixed-fixture observation contains only normalized identities, counts, booleans, hashes, and named witness kinds; it never contains prompt/source/oracle/model/provider/credential/kernel output text.
- The verifier may emit a `PrimeEvidenceReceipt` at `provider-free` only for a complete fixed-fixture truth table. It may not emit `bounded-sandboxed`; the future authorized Linux run must separately bind this result to real worker/broker evidence.

- [ ] **Step 1: Write failing exact truth-table tests**

Require advertised built-in tools exactly `("ipython",)`, every recorded model tool call `ipython`, at least two turns with one actual compaction, one exact session and kernel generation across all witnesses, namespace/import/function/cwd/workspace-file witnesses after compaction, no child session/action, immutable oracle initially failed then passed, a bound broker terminal receipt within budget, and exact worker attestation plus verified cleanup. Add one subtest per missing/mutated fact and redaction tests with sentinels.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_coding_fixture_receipt`

Expected: FAIL before verifier exists.

- [ ] **Step 3: Implement the non-upgrading verifier**

Use closed dataclasses and exact identity checks. Produce only `PrimeEvidenceReceipt("prime.ipython-coding/v1", PROVIDER_FREE, "PASS")`; reject a request/value attempting any evidence-level upgrade. The verifier must consume the existing broker/worker receipt types without exposing their private internals.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_coding_fixture_receipt tests.test_prime_model_broker tests.test_prime_worker_gate && uv run ruff check src/asterion/applications/prime_agent/coding_fixture_receipt.py tests/test_prime_coding_fixture_receipt.py && uv run pyright src/asterion/applications/prime_agent/coding_fixture_receipt.py tests/test_prime_coding_fixture_receipt.py`

Expected: PASS provider-free; no Docker/model/provider call and no `bounded-sandboxed` claim.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/coding_fixture_receipt.py tests/test_prime_coding_fixture_receipt.py
git commit -m "feat(prime): verify fixed coding fixture receipt"
```

### Task 13: Real-Docker contract corrections before the fixed image artifact

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/docker_worker.py`
- Modify: `src/asterion/applications/prime_agent/operator/docker_cli.py`
- Modify: `tests/test_prime_docker_worker.py`
- Modify: `tests/test_prime_docker_cli.py`

**Decision:** A local Docker image config ID (`sha256:…`) is the worker image authority. It is operator-private and may not equal a registry repo digest; closed inspection requires the exact config ID and an empty repo-digest tuple for locally built image. `--pull=never` remains mandatory. The former one-shot `attach` deadlocks the launcher barrier because it waits for container exit. The transport instead retains a private, bounded attach channel per opaque container, reads exactly one self-check frame before admission, and writes the one barrier release frame only after the true launcher barrier action.

- [ ] **Step 1: Write failing config-ID and attach lifecycle tests**

Reject a config-ID mismatch, any nonempty/malformed repo-digest value, tag authority, raw or oversized first frame, extra self-check fields, EOF before frame, and attach command that waits for exit. Assert self-check reads exactly one canonical ≤1KiB JSON line, persists the private channel, and release-before-attestation is impossible. Assert a release frame is written exactly once only during the actual barrier action; no socket/path/token/credential/provider/body appears in public values/errors.

- [ ] **Step 2: Implement a closed persistent launcher channel**

Keep channel handles private in the transport by opaque container ID. `launcher_self_check` starts/uses code-owned interactive attach, consumes only the first bounded canonical frame, and returns the typed self-check without awaiting process exit. Add a code-owned post-attestation release method usable only by trusted launcher coordination. Close/reap the channel in verified teardown. Continue to prohibit `exec`, `cp`, `logs`, mounts, network, generic commands, and raw output exposure.

- [ ] **Step 3: Verify and commit**

Run: `uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_docker_cli tests.test_prime_launcher_barrier && uv run ruff check src/asterion/applications/prime_agent/operator/docker_worker.py src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_worker.py tests/test_prime_docker_cli.py && uv run pyright src/asterion/applications/prime_agent/operator/docker_worker.py src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_worker.py tests/test_prime_docker_cli.py`

```bash
git add src/asterion/applications/prime_agent/operator/docker_worker.py src/asterion/applications/prime_agent/operator/docker_cli.py tests/test_prime_docker_worker.py tests/test_prime_docker_cli.py
git commit -m "fix(prime): retain docker launcher channel"
```

### Task 14: Canonical fixed-image artifact and launcher protocol

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/image/Dockerfile`
- Create: `src/asterion/applications/prime_agent/operator/image/launcher.mjs`
- Create: `src/asterion/applications/prime_agent/operator/image/requirements.lock`
- Create: `src/asterion/applications/prime_agent/operator/image/fixture/starter/solution.py`
- Create: `src/asterion/applications/prime_agent/operator/image/fixture/oracle/oracle.py`
- Create: `src/asterion/applications/prime_agent/operator/image/fixture/fixture-lock.json`
- Create: `tools/build_prime_ipython_image.py`
- Create: `tests/test_prime_ipython_image.py`
- Create: `tests/test_prime_ipython_launcher_protocol.py`

**Build context and provenance:** The tool verifies the absolute pinned Prime root using `verify_prime_source_lock`, then writes a temporary canonical tar context containing only the locked source tree/package lock and Asterion-owned image assets. It normalizes ordering/path/mode/uid/gid/timestamps, excludes `.git`, `node_modules`, `.env`, caches and unrelated files, and exposes a `build_input_sha256` plus source/base/asset provenance. It must not modify or copy upstream into the repository. The operator-only build command is explicit and never invoked by unit tests; image config ID is recorded only in an external `0600` operator configuration, never manifests or `.env`.

**Launcher protocol:** Its exact first stdout line is the canonical ≤1KiB self-check JSON required by Task 13, then it blocks for exactly one release frame. Before release it checks UID/capabilities/NNP/seccomp/network/mounts/writable paths; it copies immutable starter to the sole writable workspace and requires a locked initial oracle failure. After release it runs only the fixed Prime/IPython sequence, compaction, locked final oracle, and emits normalized evidence only. No credentials/provider/socket/path/transcript/source text enters frames.

- [ ] **Step 1: Write failing static contract tests**

Test source lock before context creation, tar membership/normalization/digest determinism and exclusions, Dockerfile policy (digest-pinned base; no `ARG`, remote `ADD`, tags, secrets), external-only `0600` config target, fixture initial failure/final pass and immutable oracle/starter hashes, canonical self-check/release parser, redaction, cap and one-release rules. Unit tests must not call Docker/Node/network/provider.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_ipython_image tests.test_prime_ipython_launcher_protocol`

Expected: FAIL before artifacts/tool exist.

- [ ] **Step 3: Implement fixed, static artifacts**

Implement only static artifact construction and a launcher whose executable upstream session invocation stays behind the release barrier. Pin every package input. Do not claim an upstream API/command works until the separate real-process provider-free compatibility test exists; annotate unproven operations as incomplete rather than bypassing them.

- [ ] **Step 4: Verify GREEN**

Run: `uv run python -m unittest -v tests.test_prime_ipython_image tests.test_prime_ipython_launcher_protocol && uv run ruff check tools/build_prime_ipython_image.py tests/test_prime_ipython_image.py tests/test_prime_ipython_launcher_protocol.py && uv run pyright tools/build_prime_ipython_image.py tests/test_prime_ipython_image.py tests/test_prime_ipython_launcher_protocol.py`

Expected: PASS provider-free and Docker-free; no image build/probe/evidence upgrade.

- [ ] **Step 5: Commit**

```bash
git add src/asterion/applications/prime_agent/operator/image tools/build_prime_ipython_image.py tests/test_prime_ipython_image.py tests/test_prime_ipython_launcher_protocol.py
git commit -m "feat(prime): define fixed ipython image artifact"
```

### Task 15: Real Prime/IPython provider-free compatibility process

**Files:**
- Create: `tests/fixtures/prime_gateway/v1/prime-ipython-coding-compat.mjs`
- Create: `tests/test_prime_ipython_coding_compat.py`

**Boundary:** This test uses the pinned source's existing `dist` in a temporary workspace and a deterministic local framed provider. It may run `node` and local Python/IPython only; it must never invoke Docker, network, credentials, `.env`, package installation, builds, or write within `3th-party/prime-agent`. It is compatibility evidence only and cannot emit a `PrimeEvidenceReceipt` or any sandbox PASS.

- [ ] **Step 1: Write failing real-process receipt test**

Spawn the fixture with absolute pinned source/temp workspace paths. Require a redacted normalized JSON receipt proving imports of `createAgentSession`, `SessionManager.inMemory`, `ModelRegistry`, the deterministic custom `streamSimple` provider, exact advertised/allowed tool set `("ipython",)`, an actual IPython execution, actual `session.compact()`, same session/kernel generation witnesses before/after compaction, event subscription, and `session.dispose()`. Assert command/environment excludes provider/credential inputs and all output remains public-safe.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_ipython_coding_compat`

Expected: FAIL before fixture exists.

- [ ] **Step 3: Implement the deterministic local compatibility fixture**

Import only exact paths from the pinned `dist`, use temporary dirs and the existing local kernel prerequisites, and verify the upstream APIs/events directly rather than stubbing them. Reject missing API/unsupported platform/prerequisite as a fixed `External-limited` compatibility classification; never substitute a fake positive receipt. Dispose all session/kernel resources and ensure temporary workspace cleanup.

- [ ] **Step 4: Verify GREEN or record exact External-limited result**

Run: `uv run python -m unittest -v tests.test_prime_ipython_coding_compat`

Expected: a passing provider-free compatibility command only if exact upstream API plus local IPython works; otherwise the test records an exact non-PASS classification without building/running Docker or a model.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/prime_gateway/v1/prime-ipython-coding-compat.mjs tests/test_prime_ipython_coding_compat.py
git commit -m "test(prime): exercise ipython coding compatibility"
```

### Task 16: Closed offline Prime kernel material lock

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/image_input_lock.py`
- Create: `tools/materialize_prime_ipython_inputs.py`
- Create: `tests/test_prime_image_input_lock.py`
- Create: `tests/test_prime_image_materializer.py`

**Decision:** Real IPython is supplied only by a frozen, Linux-targeted artifact
set. A closed `image-input-lock/v1` binds the existing exact Prime source lock,
the target platform, pinned base OCI manifest/config/layers, Node archive,
canonical Linux `node_modules`, every binary Python wheel, the local
`prime-agent-runtime` wheel, fixture assets, and build frontend. Standard
tests validate static inputs only. A separately explicit release materializer
may download missing inputs, never changes the pinned checkout, and must
produce the locked artifact set before an offline build can be attempted.

- [ ] **Step 1: Write failing closed-lock tests**

Require a closed/sorted schema with no URLs, versions ranges, tags, sdist,
editable/VCS requirements, duplicate digests, or missing required kernel
dependencies. Require exact source-lock equality and platform
`linux/amd64`. Verify artifact records contain only relative safe paths,
sizes, and SHA-256 values. Test that static validation never calls network,
Docker, Node, pip, npm, uv, or reads `.env`.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_image_input_lock tests.test_prime_image_materializer`

Expected: FAIL before the lock/materializer exists.

- [ ] **Step 3: Implement static lock verification and explicit materializer boundary**

Use frozen Python values, exact canonical JSON, no-follow file reads, and
public-safe errors. The materializer must require an explicit operator selected
external output root, reject repository/source targets and pre-existing paths,
and expose only a command plan until a separately authorized release workflow
adds network materialization. It must never silently fall back to package
manager/bootstrap behavior.

- [ ] **Step 4: Verify and commit**

Run: `uv run python -m unittest -v tests.test_prime_image_input_lock tests.test_prime_image_materializer && uv run ruff check src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_input_lock.py tests/test_prime_image_materializer.py && uv run pyright src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_input_lock.py tests/test_prime_image_materializer.py`

```bash
git add src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_input_lock.py tests/test_prime_image_materializer.py
git commit -m "feat(prime): lock offline kernel image inputs"
```

### Task 17: Authorized release materialization and immutable lock proposal

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/image_input_lock.py`
- Modify: `tools/materialize_prime_ipython_inputs.py`
- Create: `tests/test_prime_image_release_materializer.py`
- Modify: `tests/test_prime_image_input_lock.py`

**Authorization boundary:** This is the only P1 action permitted to use the
network. It runs only when an operator explicitly invokes an exact CLI with a
fresh, repository-external output root. It must never modify the pinned Prime
checkout, repository files, manifests, or existing target. It stages all bytes
under the selected root, emits a proposed canonical lock plus provenance only
after every expected object is independently hashed, and leaves the proposal
untrusted until a human reviews and promotes it in a separate commit. Standard
tests use a local fake fetcher and never call the network, Docker, Node, pip,
npm, uv, `.env`, or a package manager.

- [ ] **Step 1: Write failing authorization and staging tests**

Create a fake injected fetch transport. Require materialization to reject
absent explicit authorization, existing/repository/source/symlink targets,
unexpected URL schemes or redirects, non-HTTPS origins, path traversal,
wrong content length/hash, archive entries outside their assigned destination,
and duplicate downloads. Require the fake successful path to write only a
fresh `0700` external staging root, use no-follow/exclusive files, generate a
canonical proposal separate from `PRIME_IPYTHON_IMAGE_INPUT_LOCK`, and never
return `VerifiedImageInputArtifactSet` or a build/PASS receipt.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_image_release_materializer tests.test_prime_image_input_lock`

Expected: FAIL because the release-only authorization, transport and proposal
types do not exist.

- [ ] **Step 3: Implement a release-only, proposal-producing workflow**

Accept only an injected exact release specification whose URLs, target relative
paths, expected lengths, SHA-256 values, target `linux/amd64`, and source lock
are closed/sorted. Fetch using a narrow HTTPS transport with redirects disabled
and a bounded byte cap. Store each byte stream through `O_EXCL|O_NOFOLLOW`,
hash while writing, then re-read via no-follow descriptor before including it
in the proposal. Do not invoke container engines or package managers. The
public result contains only target ID/count/digests; private local provenance
may retain URLs. A later explicit human promotion replaces the unmaterialized
static lock; this task must not do that automatically.

- [ ] **Step 4: Perform the operator-authorized materialization**

Only after static tests and independent review are green, invoke the exact
release command against `/tmp/asterion-prime-release-artifacts-20260903`.
Record the command identity and public-safe outcome in the journal. If any
real required object, upstream hash, release prerequisite, or target-platform
condition is unavailable, preserve the root for inspection, classify the exact
failure `External-limited`, and do not promote any lock/build claim.

- [ ] **Step 5: Verify and commit code (not external artifacts)**

Run: `uv run python -m unittest -v tests.test_prime_image_release_materializer tests.test_prime_image_input_lock tests.test_prime_image_materializer && uv run ruff check src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_release_materializer.py tests/test_prime_image_input_lock.py && uv run pyright src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_release_materializer.py tests/test_prime_image_input_lock.py`

```bash
git add src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_release_materializer.py tests/test_prime_image_input_lock.py
git commit -m "feat(prime): stage authorized offline image inputs"
```

### Task 17.1: Exact promoted target catalog and platform-scoped staging

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/image_input_lock.py`
- Modify: `tools/materialize_prime_ipython_inputs.py`
- Modify: `tests/test_prime_image_input_lock.py`
- Modify: `tests/test_prime_image_release_materializer.py`
- Modify: `tests/test_prime_image_materializer.py`

**Correction:** `linux/amd64` is an initial exact release target, not an
Asterion Prime product constraint. Each lock is bound to one exact OCI platform
descriptor `{os, architecture, variant}`; missing variant is distinct from any
present variant. A sorted code-owned promoted catalog resolves an explicit
requested descriptor to exactly one lock. No host detection, range, architecture
fallback, engine fuzzy selection, or emulation fallback is permitted. Staging
is target-byte validation and may run cross-host; it cannot become runtime or
worker evidence.

- [ ] **Step 1: Write failing descriptor/catalog tests**

Require exact descriptor validation, canonical sorting, unique catalog entries,
exact `linux/amd64` initial resolution, and failure for unknown target,
variant omission/mismatch, duplicate descriptor, cross-lock substitution, and
implicit host selection. Require materialization specification/proposal/result
to carry the exact requested descriptor and reject a target different from its
selected promoted lock. Existing static tests remain provider-free.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_image_input_lock tests.test_prime_image_release_materializer`

Expected: FAIL because the singleton platform string provides neither an exact
descriptor nor explicit catalog resolution.

- [ ] **Step 3: Implement closed platform resolution**

Introduce frozen descriptor/catalog types with only one currently promoted
candidate (`linux/amd64`, absent variant). Preserve all source-lock,
no-follow, parser and verifier-only-proof controls. Change release
specification/materialization APIs to require the caller-provided exact
descriptor and resolve it before target validation/fetch; do not make staging
depend on the machine's host architecture. Do not add arm64 as promoted until
it has its own reviewed real artifact proposal and lock.

- [ ] **Step 4: Verify and commit**

Run: `uv run python -m unittest -v tests.test_prime_image_input_lock tests.test_prime_image_release_materializer tests.test_prime_image_materializer && uv run ruff check src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_input_lock.py tests/test_prime_image_release_materializer.py && uv run pyright src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_input_lock.py tests/test_prime_image_release_materializer.py`

```bash
git add src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_input_lock.py tests/test_prime_image_release_materializer.py
git commit -m "feat(prime): resolve exact image target locks"
```

### Task 17.2: Proposal-only release-spec generation boundary

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/release_spec_generation.py`
- Create: `tools/generate_prime_ipython_release_spec.py`
- Create: `tests/test_prime_release_spec_generation.py`

**Boundary:** An acquisition/release proposal is not a promoted lock or image
evidence. Generation requires an explicit exact target descriptor and an
operator-selected fresh external work root. Every observation carries its
substate class (`native-linux`, `desktop-vm`, or `emulated`) and target match.
Only a non-emulated native-Linux observation of the exact target may be marked
`candidate-native`; all other successful technical observations are
`External-limited` and cannot be promoted. The generator must never invoke
network/package engines itself; it consumes injected discovery/capture records
and emits only canonical untrusted proposal data for human review.

- [ ] **Step 1: Write failing substrate/proposal tests**

Test frozen exact substrate descriptors, target/substrate mismatch, emulation,
desktop VM classification, duplicate/unsorted capture records, missing raw
metadata hashes, artifact URL/size/digest mismatch, and absence of the pinned
Prime source triple. Require canonical untrusted acquisition lock, artifact
inventory, release proposal and provenance outputs. Assert no output can be
parsed as a promoted `ImageInputLock`, verified artifact set, image identity,
or scenario PASS.

- [ ] **Step 2: Run RED**

Run: `uv run python -m unittest -v tests.test_prime_release_spec_generation`

Expected: FAIL before generator types and verifier exist.

- [ ] **Step 3: Implement pure proposal validation/classification**

Use closed frozen records only: exact target descriptor; exact Prime source;
metadata/object digest/size/HTTPS identity; deterministic generator revision;
and explicit platform/substrate/emulation state. Return a public-safe result
whose highest success is `candidate-native`, never a verified/released image.
Do not read `.env`, host architecture, Docker engine state, package locks, or
network. The CLI serializes injected private input to a caller-selected
external target only in a separate later authorization step.

- [ ] **Step 4: Verify and commit**

Run: `uv run python -m unittest -v tests.test_prime_release_spec_generation tests.test_prime_image_input_lock && uv run ruff check src/asterion/applications/prime_agent/operator/release_spec_generation.py tools/generate_prime_ipython_release_spec.py tests/test_prime_release_spec_generation.py && uv run pyright src/asterion/applications/prime_agent/operator/release_spec_generation.py tools/generate_prime_ipython_release_spec.py tests/test_prime_release_spec_generation.py`

```bash
git add src/asterion/applications/prime_agent/operator/release_spec_generation.py tools/generate_prime_ipython_release_spec.py tests/test_prime_release_spec_generation.py
git commit -m "feat(prime): classify release specification proposals"
```
