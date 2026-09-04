# Prime P1 Real End-to-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` task-by-task with independent review.

**Goal:** Deliver one fixed, real LLM-driven Prime/IPython coding task through `asterion verify --provider prime-agent --level basic`.

**Architecture:** Use the standard selected-provider → assembly → package → runner → runtime → injected host-service route. Prime application code owns model configuration and restricted-worker framing; framework modules remain domain-neutral. Provider-free tests cannot mint bounded evidence.

**Global constraints:** One action surface: `ipython`. `.env`, credentials, prompts, raw model/tool data, and private paths never enter manifests or public output. Basic runs one fixed bounded preset with no user model/cost/deadline knobs. No deterministic patch, fake broker, or manually issued cell can pass bounded P1.

### Task 1: Prime executable package and runtime

**Files:** Create Prime capability package payload/manifest/implementation; add `prime.agent` runtime factory; update exact registry, assembly, and tests.

- [x] Write failing package-resolution and runtime tests proving `prime-agent@1.0.0`, `prime.ipython-coding@1.0.0`, and only `prime.tool.ipython` resolve through the standard composition path.
- [x] Implement one exact package binding and a frame-only runtime adapter; reject alternate tools, ambiguous bindings, and undeclared runtime IDs before execution.
- [x] Run focused package/runtime/assembly tests, Ruff, Pyright, and commit.

### Task 2: Bounded model-session service and private operator integration

**Files:** Create narrow bounded model-session protocol/receipt and Prime application host factory; update host-service registration and tests.

- [x] Write failing tests for fixed request/token/byte/cost/deadline ceilings, cancellation, terminal receipt, sentinel redaction, and missing private configuration.
- [x] Implement application-only dotenv resolution and a revocable model session. It returns framed bytes plus body-free usage receipts; worker receives no credential/environment provider configuration.
- [x] Run focused tests/static checks and commit.

### Task 3: Real Prime/IPython worker protocol

**Files:** Replace deterministic P1 launcher path; extend worker/image framing and oracle fixture; add protocol/worker tests.

- [ ] Write failing tests requiring initial oracle failure, nonzero host-model operations, Prime tool set exactly `("ipython",)`, model-caused IPython mutation, final oracle success, cleanup, and rejection of deterministic/manual/fake paths.
- [ ] Implement duplex closed frames: control, model request/response, and terminal completion. Pin real Prime SDK session and relay model frames only via the host service; perform oracle checks in launcher.
- [ ] Run provider-free protocol/image tests and commit. Do not execute a live model in this task.

### Task 4: Prime product verifier and CLI basic preset

**Files:** Modify Prime provider/product integration and CLI-facing verifier; add integration tests.

- [ ] Write failing tests that `preflight` is side-effect free, `acceptance` is provider-free, and `basic` resolves the P1 installed closure with no user-facing provider/model/cost/runtime switches.
- [ ] Implement exact Prime verification levels. `basic` invokes the standard runner once; its public result has only safe status/counts/digests/opaque references. `complete` contains P1 once pending later scenarios.
- [ ] Run CLI/integration tests, Ruff, Pyright, and commit.

### Task 5: Bounded evidence and operator execution

**Files:** Create P1 bounded receipt/reducer/evidence-root contract; extend docs and tests.

- [ ] Write failing reducer tests requiring identity closure, causal model→IPython→workspace ordering, pre/post oracle states, bounded usage, and worker/broker destruction.
- [ ] Implement atomic body-free evidence publication and rejection of fixture/fake/manual paths.
- [ ] Run all P1 provider-free checks. With a separately recorded finite operator authorization, run the one `basic` preset once and record its actual PASS/FAIL/External-limited result; do not claim a live result without it.

## Completion evidence

P1 is complete only after a real authorized `basic` CLI run emits a bounded PASS meeting Task 5. P2–P7 begin only after this shared spine is proven.
