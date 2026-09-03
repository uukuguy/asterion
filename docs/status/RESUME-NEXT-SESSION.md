# Live Session Checkpoint

> Updated: 2026-09-03. **Session remains active — not a final handoff.**

## TL;DR

- Smoke Core is closed as a narrow control-chain regression gate; it is not
  the Prime product roadmap.
- The approved Prime capability program is committed at `19c4fb3` and defines
  seven end-to-end products through ARC-AGI-3.
- P0 safety foundation is implemented through `0182822`: a restricted-worker
  profile, exact source lock, closed evidence ladder, metadata-only provider,
  and preflight that verifies an explicit root against its expected lock.
- P0 is closed through `8111fb9`: focused contracts, independent security
  reviews, and a rerun `make promotion-check` all pass. The first long
  promotion attempt exposed a stale global provider-inventory assertion; the
  exact three-provider inventory is now tested while DCI's selected closure
  remains exactly two providers.
- P1 worker-boundary foundation is through `3d478d1`: typed restricted-worker
  and model-session leases, a fixed Docker-only role, pre-start inspection,
  post-start re-inspection, and redacted launcher self-check evidence. Tasks
  1–7 have independent approval, including verified teardown: final
  inspection, forced removal, absence proof, and a tombstone-only cleanup
  receipt. Task 8 has independent approval for real-daemon lifecycle gaps:
  cancellation-safe forced cleanup, absolute deadlines, and no silent
  post-start orphan. Task 9 is independently approved: closed Docker CLI
  translation, including stream-bounded subprocess handling, is covered only
  by fake-process verification. Task 10 is independently approved: fixed
  launcher barrier and Linux-only readiness are contracts only, never sandbox
  evidence. Task 11 is independently approved: the enforcing host broker is
  barrier-gated, budgeted, revocable, and truthful about cleanup uncertainty.
  Task 12 is independently approved: its fixed coding-fixture receipt truth
  table cannot upgrade evidence beyond provider-free. The next work is a
  source-lock-preserving fixed image and launcher contract. Tasks 13 and 14
  are independently approved: real Docker config-ID/attach-channel semantics
  are fail-closed and cancellation-safe, and the fixed image artifact captures
  verified source bytes into a canonical context without invoking Docker. Task
  15's corrective compatibility witness is independently approved. It verifies
  the exact Prime source lock before any spawn; without a pre-provisioned,
  valid kernel it emits only `External-limited/missing-prerequisite` without
  launching Node/Prime or entering upstream bootstrap. With a pre-provisioned
  kernel, child environment controls disable bootstrap/package-network paths;
  timeout preserves an already emitted public observation and `reaped` is set
  only by parent process-group observation. This is compatibility evidence,
  not Prime E2E PASS or sandbox evidence.

## Current decision

- Prime reproduces the semantic RLM-harness core: persistent IPython as the
  sole built-in action surface, recursive `rlm(...)`, and a versioned
  Continual Harness.
- Python remains provider-neutral authority, budget, recovery, and evidence;
  the TypeScript Gateway retains upstream kernel/session/RLM mechanisms.
- The pinned Prime checkout stays read-only.  Do not create broad CLI/TUI or
  provider-catalog parity work.
- Sol's P1 review is conditional: static profile validation is not a sandbox.
  Before `prime.ipython-coding/v1` may claim `bounded-sandboxed`, provide an
  actual restricted-worker lease/attestation and host-side model broker so
  credentials never enter the daemon or kernel.

## Immediate next action

1. Task 18 is independently approved: the release recipe is platform-neutral,
   exact candidate policy contains `linux/arm64` and `linux/amd64`, and the
   promoted image-lock catalog is intentionally empty. Synthetic size-one
   data has no production authority. Lock hashing and full-set verification
   require an explicit reviewed lock; candidate policy can never promote one.
2. Tasks 19–20 completed the first claim/staging split, but their combined
   final review rejected incomplete target graph, recipe identity, private
   metadata parsing, and descriptor-relative staging. Task 21 now adds the
   canonical platform-neutral recipe digest and distinct candidate/promoted
   authority types [858643e, a1a3b35]. Its focused and cross suites pass, but
   independent review is pending because the agent-thread limit was reached.
   Task 22 now has its pure offline parser foundation [9f25bf3], a URL-free
   public-result projection [6a85157], and recipe identity on every public
   candidate record [3086aa8]. It still must derive claims from parser-produced
   metadata declarations and require a complete target-specific closure.
   `make test` is currently red on the pre-existing DCI acceptance expectation:
   it assumes the only packaged unbound assembly is DCI but now sees the Prime
   assembly too; no fix has been applied because that baseline correction is
   outside the active Prime contract work.
3. Darwin arm64/OrbStack may later create an arm64 candidate closure and
   desktop-VM compatibility result, but these remain `External-limited`.
   Native Linux replay on the same descriptor is required for supported-native
   evidence; `bounded-sandboxed` additionally requires the existing worker,
   cleanup, broker, and complete IPython scenario chain.
4. The immediate root cause is recorded: the hermetic compatibility environment
   gives Prime an empty `HOME`, so it attempts its documented first-run network
   bootstrap; the Asterion `.venv` contains neither `ipykernel` nor
   `prime_agent_runtime`. Determine whether the locked static image supplies a
   prebuilt kernel environment; do not permit a test to download dependencies.
   Actual Docker verification remains separate from provider-free tests and
   cannot claim `bounded-sandboxed` on Docker Desktop/OrbStack.
5. No receipt may claim `bounded-sandboxed` until a supported native-Linux
   worker, exact built image, fixed coding fixture, and host broker are all
   exercised together.

## Approved direction for the next P1 subpackage

- Build real Prime/IPython only through **release materialization → fully
  offline image assembly → explicit native-Linux probe**. The material lock
  must bind the existing exact Prime source lock, platform-pinned Python/Node,
  canonical Linux `node_modules`, every hashed binary Python wheel, the locally
  built `prime-agent-runtime` wheel, fixture assets, and build frontend.
- The final image must provide a root-owned read-only
  `/opt/prime-kernel/bin/python` and bind it with
  `PRIME_AGENT_KERNEL_PYTHON`; it must not contain `uv` or allow any startup
  package installation. Docker build uses `--network=none --pull=never`; run
  uses `NetworkMode=none`.
- Only the fourth native-Linux task (actual fixed fixture, framed host broker,
  attestation, cleanup, and persistent-kernel evidence) can claim
  `prime.ipython-coding/v1` `bounded-sandboxed PASS`.

## Recovery commands

```bash
git status --short
git log --oneline -12
uv run python -m unittest -v tests.test_prime_docker_worker tests.test_prime_worker_gate
uv run pyright src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_worker.py
```
