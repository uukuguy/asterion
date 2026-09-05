# Prime P3 Development E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close `prime.recursive-workflow/v1` with one installed CLI route that executes real pinned Prime RLM children, Docker-backed IPython work, a retained-child follow-up, a host oracle, and verified cleanup.

**Architecture:** Extend the existing inherited-FD development gateway with a single-reader, nonblocking callback dispatcher and closed nested commands. Build a P3 TypeScript session around the real `runRlmChild` APIs, then connect it to role-bound Python model/Docker adapters and the standard Asterion application/runtime/host path.

**Tech Stack:** Python 3.13, asyncio, canonical framed Unix sockets, TypeScript/Node 22, pinned Prime SDK, Docker/IPython, immutable Asterion manifests, `unittest`.

## Global Constraints

- The authoritative design is `docs/superpowers/specs/2026-09-06-prime-p3-development-e2e-design.md`.
- Keep `3th-party/prime-agent` read-only and use its exact pinned SDK APIs.
- Prime owns root/child sessions; Python owns admission, budgets, Docker, oracle, cleanup, and public trace projection.
- Use exact application `prime.recursive-workflow@1.0.0`, runtime `prime.agent`, fixed input `fixed-small-verification`, host capability `prime.recursive-workflow-development`, scope `p3-development`, and promotion `unpromoted`.
- The fixed success path has two depth-one children, one retained review follow-up, eight model callbacks, and four IPython calls.
- Public output contains only fixed IDs, scope, promotion, and digests. No prompt, source, child identity, path, provider value, model content, worker output, or private exception context may escape.
- Development verification covers the normal path and key identity/depth/count/timeout/cancellation/oracle/redaction boundaries. Do not run promotion or release matrices.

---

### Task 1: Reentrant development gateway transport

**Files:**
- Modify: `src/asterion/applications/prime_agent/operator/development_gateway_transport.py`
- Modify: `src/asterion/applications/prime_agent/operator/p1_development_gateway.py`
- Modify: `src/asterion/applications/prime_agent/operator/p2_development_gateway.py`
- Create: `tests/test_prime_development_gateway_reentrant.py`
- Test: `tests/test_prime_p1_development_gateway.py`
- Test: `tests/test_prime_p2_development_gateway.py`

**Interfaces:**
- Produce: `DevelopmentGatewayTransport.request_nested(kind: str, payload: Mapping[str, object]) -> Awaitable[Mapping[str, object]]`.
- Produce: constructor argument `nested_command_kinds: frozenset[str] = frozenset()`; P1/P2 pass the empty set.
- Preserve: one socket reader, contiguous input/output sequences, exact request-ID routing, existing `open/prompt/cancel/close` behavior and body-free errors.

- [ ] **Step 1: Write failing reentrancy tests.**

Create a fake framed Node child which emits a `tool.request`, waits for a nested
`rlm.spawn` command, emits a model request while that command is active, accepts
both callback responses, and returns the nested and outer results. Assert the
tool hook can await `request_nested("rlm.spawn", {"role": "implementation"})`
without deadlock. Also assert an unlisted kind, duplicate response, unknown
request ID, callback exception, and cancellation close the transport.

```python
async def tool_hook(_: Mapping[str, object]) -> object:
    nested = await gateway.request_nested(
        "rlm.spawn", {"role": "implementation"}
    )
    return {"content": [{"type": "text", "text": nested["status"]}]}

self.assertEqual(await gateway.prompt("fixed"), {"lifecycle": "completed"})
```

- [ ] **Step 2: Run the new test and verify RED.**

Run:

```bash
uv run --with-editable . python -m unittest -q tests.test_prime_development_gateway_reentrant
```

Expected: FAIL because `request_nested` and closed nested-kind routing are absent.

- [ ] **Step 3: Implement one-reader asynchronous callback dispatch.**

Add a dedicated write lock, exact nested request counter/map, and the closed
kind set. When `_receive_until` observes a model/tool request, schedule this
coroutine on the registered event loop and immediately continue reading:

```python
async def invoke() -> object:
    value = hook(payload)
    return await value if inspect.isawaitable(value) else value
```

The future's completion callback sends the exact response under the write lock.
On callback failure it records one fixed transport failure and shuts down the
socket to wake the sole reader. `request_nested` validates the kind/payload,
registers one `concurrent.futures.Future`, sends the command under the write
lock, and awaits it with `asyncio.wrap_future`. `_receive_until` resolves only
the matching registered nested future; unknown or duplicate command results
fail closed. Cancellation removes the pending future and fails the transport.

- [ ] **Step 4: Verify the new behavior and P1/P2 regression.**

Run:

```bash
uv run --with-editable . python -m unittest -q \
  tests.test_prime_development_gateway_reentrant \
  tests.test_prime_p1_development_gateway \
  tests.test_prime_p2_development_gateway
uv run ruff check \
  src/asterion/applications/prime_agent/operator/development_gateway_transport.py \
  tests/test_prime_development_gateway_reentrant.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 5: Commit exact files.**

```bash
git add \
  src/asterion/applications/prime_agent/operator/development_gateway_transport.py \
  src/asterion/applications/prime_agent/operator/p1_development_gateway.py \
  src/asterion/applications/prime_agent/operator/p2_development_gateway.py \
  tests/test_prime_development_gateway_reentrant.py \
  tests/test_prime_p1_development_gateway.py \
  tests/test_prime_p2_development_gateway.py
git commit -m "feat(prime): support nested development callbacks"
```

### Task 2: Real Prime P3 session and bridge

**Files:**
- Create: `packages/typescript/prime-gateway/src/p3-development-session.ts`
- Create: `packages/typescript/prime-gateway/src/p3-development-bridge.ts`
- Create: `packages/typescript/prime-gateway/src/p3-development-main.ts`
- Modify: `packages/typescript/prime-gateway/src/index.ts`
- Create: `packages/typescript/prime-gateway/test/p3-development-session.test.mjs`

**Interfaces:**
- Consume: nested frame kinds `rlm.spawn`, `rlm.wait`, `rlm.follow_up`, `rlm.list`, and `rlm.delete`.
- Produce: `PrimeP3DevelopmentSession.open(options)` and one final result with exact `lifecycle`, role-partitioned `usage`, and `observations`.
- Produce: actual observations `child_count=2`, `max_depth=1`, `retained_follow_up_count=1`, `model_callback_count=8`, `tool_call_count=4`, `remaining_child_count=0`.

- [ ] **Step 1: Write failing TypeScript session tests.**

Use the pinned SDK test seam to assert two calls to `runRlmChild`, SDK-issued
distinct IDs, depth one, implementation/review role binding, the same retained
review session for follow-up, exactly two `deleteRlmSubagent` calls, and an
empty final `listRlmSubagents`. Reject a third child, depth two, duplicate ID,
review replacement, extra tool, and missing terminal usage.

```ts
expect(observations).toEqual({
  child_count: 2,
  max_depth: 1,
  model_callback_count: 8,
  remaining_child_count: 0,
  retained_follow_up_count: 1,
  tool_call_count: 4,
});
```

- [ ] **Step 2: Run the focused TypeScript test and verify RED.**

Run `npm run build && node --test test/p3-development-session.test.mjs` from
`packages/typescript/prime-gateway`.

Expected: FAIL because the P3 session and bridge do not exist.

- [ ] **Step 3: Implement the P3 session with a real `SubagentRuntimeHost`.**

Load the same pinned SDK modules as P2 plus the session APIs. Create the root
session with only `ipython` active. Install a `SubagentRuntimeHost` whose
`createRlmSubagentRuntime` validates the SDK-provided child ID, depth, parent,
model, tool lists, and session directory, then creates and publishes one child
session using those exact values. Retain only the review child, route its
follow-up to that same session, and dispose/delete all child sessions in reverse
order. Count model/tool callbacks at their actual role-bound wrappers.

- [ ] **Step 4: Implement the closed P3 bridge.**

Copy the canonical framing and identity validation pattern from P2, change the
protocol to `asterion.prime-p3-development-gateway/v1`, and permit only the five
nested RLM kinds while phase is `prompt`. Every nested result uses its original
request ID. Model and tool callbacks include only the fixed role selector plus
the existing private SDK payload; no child ID enters Python model content.

- [ ] **Step 5: Build and run focused tests.**

Run:

```bash
npm run build
node --test test/p3-development-session.test.mjs
```

Expected: focused test and TypeScript build pass.

- [ ] **Step 6: Commit exact files.**

```bash
git add packages/typescript/prime-gateway/src/index.ts \
  packages/typescript/prime-gateway/src/p3-development-session.ts \
  packages/typescript/prime-gateway/src/p3-development-bridge.ts \
  packages/typescript/prime-gateway/src/p3-development-main.ts \
  packages/typescript/prime-gateway/test/p3-development-session.test.mjs
git commit -m "feat(prime): run real P3 RLM children"
```

### Task 3: P3 workload, workers, model adapter, oracle, and CLI host

**Files:**
- Create: `src/asterion/applications/prime_agent/operator/p3_development_workload.py`
- Create: `src/asterion/applications/prime_agent/operator/p3_development_gateway.py`
- Create: `src/asterion/applications/prime_agent/operator/p3_development_sdk_provider.py`
- Create: `src/asterion/applications/prime_agent/operator/p3_development_docker.py`
- Create: `src/asterion/applications/prime_agent/operator/p3_development_host.py`
- Create: `src/asterion/applications/prime_agent/operator/p3_cli_host.py`
- Create: `src/asterion/applications/prime_agent/operator/p3_development_image/Dockerfile`
- Create: `src/asterion/applications/prime_agent/operator/p3_development_image/asterion_rlm.py`
- Create: `src/asterion/applications/prime_agent/operator/p3_development_image/resources.json`
- Create: `tests/test_prime_p3_development_workload.py`
- Create: `tests/test_prime_p3_development_gateway.py`
- Create: `tests/test_prime_p3_development_sdk_provider.py`
- Create: `tests/test_prime_p3_development_docker.py`
- Create: `tests/test_prime_p3_development_host.py`
- Create: `tests/test_prime_p3_cli_host.py`

**Interfaces:**
- Produce: `run_prime_p3_development(...) -> PrimeP3DevelopmentTrace`.
- Produce: `PrimeP3DevelopmentGateway`, with `request_nested` enabled only for the five P3 RLM kinds.
- Produce: a role-multiplexed provider admitting exactly root 2, implementation 2, and review 4 callbacks under one total input/output/cost/deadline ceiling.
- Produce: three exact Docker worker identities sharing only one validated host workspace; only the root worker receives the local RLM socket.

- [ ] **Step 1: Write failing Python boundary tests.**

Assert exact workload bytes/digests, fixed roles and counts; provider role/history
partitioning and total ceiling; exact Docker argv and cross-role rejection;
nested gateway kinds; host oracle success; missing follow-up, depth/count/usage,
wrong patch/test, cancellation cleanup, and public sentinel isolation failures.

```python
self.assertEqual(
    trace.observations,
    {
        "child_count": 2,
        "max_depth": 1,
        "model_callback_count": 8,
        "remaining_child_count": 0,
        "retained_follow_up_count": 1,
        "tool_call_count": 4,
    },
)
```

- [ ] **Step 2: Run tests and verify RED.**

Run:

```bash
uv run --with-editable . python -m unittest -q \
  tests.test_prime_p3_development_workload \
  tests.test_prime_p3_development_gateway \
  tests.test_prime_p3_development_sdk_provider \
  tests.test_prime_p3_development_docker \
  tests.test_prime_p3_development_host \
  tests.test_prime_p3_cli_host
```

Expected: FAIL because the P3 development modules do not exist.

- [ ] **Step 3: Implement the fixed workload and role-multiplexed provider.**

Define canonical source, initial test, expected fixed source, missing boundary
test, child/follow-up schemas, prompt digests, and oracle cases. Adapt the P2
killable provider so each callback carries one fixed role; maintain independent
history for root, implementation, and review, with review admitting four turns.
Require exact `toolUse/text` pairs and expose terminal usage only when all eight
callbacks finish within the shared ceiling.

- [ ] **Step 4: Implement workers and restricted root RLM RPC.**

Create three restricted containers with distinct names/labels and one exact
bind-mounted temporary workspace. Install `asterion_rlm.py` only in the root
image path. It connects to one mode-0600 Unix socket and supports the fixed
spawn/wait/follow-up/list/delete request schemas; payloads cannot select a
provider, model, depth, path, command, or budget. The Python socket handler maps
those requests to `gateway.request_nested` and validates each result before
returning it to the root cell. Child containers cannot connect to this socket.

- [ ] **Step 5: Implement lifecycle, oracle, cleanup, and CLI factory.**

Start all workers, open the P3 gateway, execute the fixed prompt, validate actual
role callback/tool/usage observations, read the workspace, run the independent
oracle, close the gateway, delete/list children, remove all containers in
reverse order, and assert every container/process absent. On every exception or
cancellation, perform bounded cleanup with a fresh cleanup control. Raise new
body-free public errors outside `except` suites so `__context__` and `__cause__`
are `None`.

- [ ] **Step 6: Run focused tests and lint.**

Run the six test modules from Step 2, then:

```bash
uv run ruff check \
  src/asterion/applications/prime_agent/operator/p3_*.py \
  tests/test_prime_p3_*.py
git diff --check
```

Expected: all focused tests, Ruff, and whitespace check pass.

- [ ] **Step 7: Commit exact files.**

Stage only the files listed by this task and commit:

```bash
git commit -m "feat(prime): execute P3 recursive development workflow"
```

### Task 4: Installed application route and one real CLI verification

**Files:**
- Create: `src/asterion/applications/prime_agent/assemblies/prime-recursive-workflow.json`
- Create: `src/asterion/capabilities/prime_agent/payload/capabilities/recursive-workflow.json`
- Modify: `src/asterion/applications/prime_agent/provider.py`
- Modify: `src/asterion/capabilities/prime_agent/payload/capability-package.json`
- Modify: `src/asterion/capabilities/prime_agent/provider.py`
- Modify: `src/asterion/runtime/defaults.py`
- Modify: `src/asterion/runtimes/prime_agent.py`
- Modify: `src/asterion/runtimes/prime_agent_host.py`
- Modify: `pyproject.toml`
- Create: `tests/test_prime_p3_installed_route.py`
- Modify: `tests/test_prime_application_provider.py`
- Modify: `docs/status/PRIME-TYPICAL-APPLICATIONS.md`
- Modify: `docs/status/CURRENT-STATE.md`
- Modify: `docs/status/RESUME-NEXT-SESSION.md`
- Modify: `docs/status/JOURNAL.md`

**Interfaces:**
- Produce: exact selector `prime.recursive-workflow@1.0.0`.
- Produce: one executable capability implementation bound to host service `prime.recursive-workflow-development`.
- Produce: public artifact `prime.p3-development.trace` with media type `application/vnd.asterion.prime.p3-development-trace+json`.

- [ ] **Step 1: Write failing installed-route tests.**

Assert metadata-only list includes the exact selector without loading its entry
point; exact assembly/package/runtime/host identities compose; wrong version,
runtime, input, host options, duplicate binding, and missing host fail closed;
the fake composed run yields exactly one safe P3 artifact.

- [ ] **Step 2: Run installed-route tests and verify RED.**

Run:

```bash
uv run --with-editable . python -m unittest -q \
  tests.test_prime_p3_installed_route \
  tests.test_prime_application_provider
```

Expected: FAIL because P3 is not installed.

- [ ] **Step 3: Add exact manifests, bindings, runtime profile, and entry point.**

Follow the P2 route shape with the IDs in Global Constraints. Keep arrays sorted
and unique, versions exact, manifests declarative, and all executable/config
values inside the injected host factory.

- [ ] **Step 4: Run focused static verification.**

Run:

```bash
uv run --with-editable . python -m unittest -q \
  tests.test_prime_p3_installed_route \
  tests.test_prime_application_provider \
  tests.test_prime_p3_development_workload \
  tests.test_prime_p3_development_gateway \
  tests.test_prime_p3_development_sdk_provider \
  tests.test_prime_p3_development_docker \
  tests.test_prime_p3_development_host \
  tests.test_prime_p3_cli_host
npm run build --prefix packages/typescript/prime-gateway
git diff --check
```

Expected: focused Python tests, TypeScript build, and whitespace check pass.

- [ ] **Step 5: Build the P3 development image and pin its exact digest.**

Build once in the existing Orb Ubuntu guest with the P3 Dockerfile and operator
context. Inspect the exact image ID and platform, then replace the CLI host's
development image constant with that digest. Run the P3 preflight once.

- [ ] **Step 6: Obtain Sol material review.**

Review the real RLM API use, reentrant transport, role/usage accounting, child
and container cleanup, manifest consistency, and public redaction. Fix every
material blocker and rerun only affected focused checks.

- [ ] **Step 7: Run one exact real CLI command.**

```bash
asterion run \
  --provider prime-agent \
  --application prime.recursive-workflow@1.0.0 \
  --runtime prime.agent \
  --run-id prime-p3-cli-verified-20260906 \
  --input fixed-small-verification
```

Expected: exit 0, one `prime.p3-development.trace`, `scope=p3-development`,
`promotion=unpromoted`, followed by zero P3 Node processes and containers.

- [ ] **Step 8: Commit route and record closure.**

Stage only Task 4 files. Update the status documents with the exact command,
trace digest, focused test counts, review verdict, and zero-residue evidence.
Commit with `feat(prime): install P3 recursive workflow`, followed by the
required one-line project-state journal entry.

## Self-Review

- Spec coverage: Tasks 1–4 cover reentrant framing, real RLM sessions, retained
  follow-up, role-bound model/Docker execution, independent oracle, cleanup,
  installed composition, public trace, review, and one real CLI run.
- Scope: each task has one independently reviewable result; no Native,
  production promotion, arbitrary-depth recursion, or unrelated refactor is
  included.
- Type consistency: the five nested kinds, callback counts, observation keys,
  IDs, scope, and artifact identity are identical across tasks.
- Placeholder scan: every step names its concrete files, interfaces, commands,
  expected evidence, and failure behavior.
