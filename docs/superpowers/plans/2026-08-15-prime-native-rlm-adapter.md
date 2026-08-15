# Prime Native RLM Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run one fully controlled Prime-native child lifecycle through Asterion admission, delivery, observation, and cleanup.

**Architecture:** Asterion extends its locked Gateway sidecar with exact Prime daemon `create`, prompt, and kill protocol calls for a native child session. The adapter binds the native child identity before lifecycle emission and exchanges only authenticated private bridge frames, while Gateway persists body-free lifecycle evidence. The upstream source remains immutable and artifact-locked.

**Tech Stack:** Python orchestration, TypeScript/Node Prime gateway, locked Prime Agent source, unittest and node:test.

## Global Constraints

- Do not modify `3th-party/prime-agent`.
- Reject unavailable or drifted locked Prime exports before execution.
- Keep prompts, credentials, paths, transcripts, and raw provider output private.
- Emit only closed control events and body-free durable records.
- Every worker is foreground-owned and receives protocol shutdown on cancellation.

---

### Task 1: Define the pinned daemon-child adapter seam

**Files:**
- Create: `packages/typescript/prime-gateway/src/native-rlm-adapter.ts`
- Modify: `packages/typescript/prime-gateway/src/main.ts`
- Test: `packages/typescript/prime-gateway/test/native-rlm-adapter.test.mjs`

**Interfaces:**
- Produces `PrimeNativeRlmAdapter.createChild(proposal): Promise<NativeRlmChild>`.
- Produces `PrimeNativeRlmAdapter.messageChild(proposal): Promise<void>` and `deleteChild(child): Promise<void>`.

- [ ] Write failing tests for exact export allowlist, source-root identity rejection, and opaque failure.
- [ ] Implement exact locked daemon command projections for create, prompt, and kill.
- [ ] Implement calls: admission before create; started after native create; terminal before delete.
- [ ] Run `npm test -- native-rlm-adapter.test.mjs` and commit.

### Task 2: Bind the adapter to Gateway RLM actions

**Files:**
- Modify: `tools/prime_native_rlm_experiment.py`
- Modify: `tools/verify_prime_loop.py`
- Test: `tests/test_prime_rlm_experiment.py`

**Interfaces:**
- Consumes the Task 1 adapter and the existing private descriptor FD.
- Produces an owned daemon plan retaining the locked standard daemon entrypoint.

- [ ] Write failing tests proving child commands use one bound native identity and never leak private goal text.
- [ ] Implement adapter command dispatch through the existing sidecar and credential isolation.
- [ ] Ensure cancellation sends protocol shutdown before process reaping.
- [ ] Run the focused Python tests and commit.

### Task 3: Verify the complete native closed loop

**Files:**
- Modify: `tools/prime_native_rlm_experiment.py`
- Modify: `tools/verify_prime_loop.py`
- Test: `tests/test_prime_rlm_experiment.py`

**Interfaces:**
- Consumes lifecycle observations `started`, `message-delivered`, and terminal `completed`.
- Produces one redacted receipt only when create, message, delete, and root terminal are complete.

- [ ] Write failing acceptance tests for successful lifecycle and foreground cancellation cleanup.
- [ ] Implement terminal evidence reduction without raw transcript exposure.
- [ ] Run TypeScript and Python suites, then a foreground explicit native-RLM probe.
- [ ] Confirm process/socket/run-root cleanup and commit.

## Self-review

- Task 1 covers the missing runtime injection seam.
- Task 2 covers ownership, pinned execution, and cancellation.
- Task 3 covers the requested verifiable long-running closed loop.
- No third-party mutation, placeholder, or public private-data path is permitted.
