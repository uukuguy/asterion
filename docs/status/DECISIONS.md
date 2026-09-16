# Architectural Decisions

## Index

| ID | Status | Decision |
|---|---|---|
| D-2026-07-26-01 | 🟢 active | Anchor explicit operator configuration to the environment-file directory |
| D-2026-07-31-02 | 🟢 active | Complete every DCI instance's 50-case result before considering full datasets |
| D-2026-08-10-03 | 🔴 superseded | Stage Prime-managed and native kernels as peer control providers |
| D-2026-08-27-04 | 🟢 active | Quiesce host-owned ecosystem projections before cleanup |
| D-2026-09-02-05 | 🟢 active | Keep Prime Smoke Core and Smoke Full evidence as distinct closed claims |
| D-2026-09-02-06 | 🟢 active | Make Prime a full RLM-harness capability program, not a Smoke Full roadmap |
| D-2026-09-05-01 | 🔴 superseded | Prime and Native remain parallel runtimes; close Prime's seven end-to-end scenarios first |
| D-2026-09-06-01 | 🔴 superseded | Resume the framework-first integration sequence after Prime closure |
| D-2026-09-06-02 | 🟢 active | Retain closed v1 contracts after W2/W3 integration evidence |
| D-2026-09-06-03 | 🟢 active | Separate provider-free framework gates from release regression |
| D-2026-09-12-01 | 🟢 active | Use native P7 as the sole Asterion Prime base and rebuild P1-P6 without Prime Agent |
| D-2026-09-14-01 | 🟢 active | Keep the application layer free of implementation references; the runtime seam carries plain data |
| D-2026-09-14-02 | 🟢 active | Supply research-preset external engines as operator-owned roots plus wheels, never as checkout-relative paths |
| D-2026-09-14-03 | 🟢 active | Inject the Pi runtime as an operator-owned entry path, satisfied by an independently installed upstream Pi |

## D-2026-07-26-01 — Operator configuration root

- Status: 🟢 active
- Decision: The parent directory of an explicit environment file is the root
  for relative Pi, Agent, corpus, and output paths during DCI verification.
  Installed provider resources remain rooted under the package.
- Rationale: Package resources and operator-owned configuration are different
  trust boundaries. Using the package root for both produced false missing
  setup diagnostics and could make preflight disagree with basic execution.
- Consequence: `make doctor` passes the repository `.env` explicitly, and
  preflight/basic resolve the same operator paths without changing generic
  provider discovery or package resource ownership.
- Evidence: commit `2358d49`; `make doctor`; `make check`;
  `make promotion-check`.

## D-2026-07-31-02 — DCI progressive evaluation order

- Status: 🟢 active
- Decision: For every real DCI instance, finish the executable 50-case (or
  smaller complete) run, scoring, and exact-resume closure before starting any
  instance's full dataset run.
- Rationale: This yields comparable, bounded, evidence-backed version results
  across the whole instance list before spending full-dataset budget.
- Consequence: Results are recorded as `50/total`; a full benchmark stays
  deferred until all listed 50-case versions have passed.

## D-2026-08-10-03 — Peer long-running control providers

- Status: 🔴 superseded by D-2026-09-12-01
- Decision: First deliver Prime Agent through a managed TypeScript Gateway, then
  implement an Asterion-native kernel as a peer provider over the same closed
  Python-owned control contracts.
- Rationale: Prime delegation supplies a high-value long-running behavior oracle
  sooner and at lower initial risk. A shared provider-neutral authority,
  execution, recovery, and evidence plane prevents Prime-specific semantics from
  becoming the framework kernel and preserves a later native implementation.
- Consequence: Phase 1 must reach the bounded Prime `Verified-loop` gate before
  it is used as a differential oracle. System parity and native parity remain
  separate named phases and cannot be inferred from provider-free evidence.
- Evidence: `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`;
  commits `75bd6fe`, `ea7a53f`, `7c202ed`.

## D-2026-08-27-04 — Quiescent ecosystem cleanup boundary

- Status: 🟢 active
- Decision: The host owns the ecosystem private namespace and must quiesce all
  projection consumers before rollback or close. Cleanup detects pre-existing
  drift and fails closed, but does not claim protection from hostile same-UID
  code retaining write-capable descendant directory descriptors during cleanup.
- Rationale: Darwin/Python exposes name-relative deletion but no portable
  conditional unlink or rmdir by held target descriptor. The stronger
  concurrent retained-fd guarantee cannot be implemented honestly without a
  new native or helper-process isolation boundary.
- Consequence: Cleanup keeps explicit retry-safe phases through tree removal and
  parent fsync. Missing or mismatched names retain ownership. Ambiguous
  descriptor-close failures are terminal and the numeric fd is never retried.
- Evidence: approved option 1 on 2026-08-27; H-024 Task 2 feasibility audit;
  `docs/superpowers/specs/2026-08-23-asterion-prime-ecosystem-parity-design.md`.

## D-2026-09-02-05 — Closed Smoke Core evidence boundary

- Status: 🟢 active
- Decision: Treat the passing `prime-smoke-core` receipt as evidence only for
  its named two-child, active-reconnect application scenario. Smoke Full is a
  separate bounded typical-application validation scope.
- Rationale: A passing narrow workflow cannot establish broader application
  coverage or promote any Prime or Asterion-native parity row.
- Consequence: Full validation needs its own exact acceptance matrix and
  public-safe receipts; Core results remain cited only within the Core scope.
- Evidence: commits `6886d1b`, `72e448f`, `bdd5576`, `56defa9`, `2b59dd6`,
  `ecb06ef`; `make prime-smoke-core` PASS;
  `docs/superpowers/specs/2026-09-02-prime-smoke-core-full-research.md`.

## D-2026-09-02-06 — Prime RLM-harness capability program

- Status: 🟢 active
- Decision: Reproduce Prime's persistent IPython, RLM, and Continual Harness
  semantics through seven exact end-to-end acceptance products, culminating in
  ARC-AGI-3. Smoke Core remains a narrow regression gate, not the product
  roadmap.
- Rationale: The Prime source and paper center a programmatic long-horizon
  harness rather than general client-surface parity or an ARC-only product.
- Consequence: Formal evidence requires an injected restricted worker/sandbox;
  trusted-local runs cannot satisfy capability acceptance.
- Evidence: user-approved review on 2026-09-02;
  `docs/superpowers/specs/2026-09-02-asterion-prime-capability-program-design.md`.

## D-2026-09-05-01 — Close Prime's seven scenarios before broad framework adjustment

- Status: 🔴 superseded by D-2026-09-12-01
- Decision: Prime and Native are parallel runtimes. Preserve the unified
  capability-package framework objective, but first close the existing seven
  Prime end-to-end reproductions. Native parity is not a dependency.
- Rationale: The seven-scenario program already contains substantial workload,
  worker, receipt and compatibility implementation; integrate and verify that
  work before redirecting effort to broad framework refactoring.
- Consequence: `PRIME-TYPICAL-APPLICATIONS.md` is the canonical active worklist,
  beginning with P1's real execution spine and full semantic proof. The earlier
  assessment's framework-first implementation ordering is superseded; its
  technical findings remain valid backlog candidates or blocking fixes.
- Ownership: Astra handles the hardest contract decisions; Terra implements
  explicit tasks; Luna performs mechanical checks; Sol independently reviews
  material security/contract changes.
- Evidence: explicit user correction and model-routing instruction on
  2026-09-05. This does not promote fake/compatibility evidence or authorize
  ARC full-suite reproduction, global activation or publication.

## D-2026-09-06-01 — Resume the framework-first integration sequence after Prime closure

- Status: 🔴 superseded by D-2026-09-12-01
- Decision: Use `FRAMEWORK-INTEGRATION-WORKLIST.md` as the canonical mainline.
  Repair existing v1 cross-layer inconsistencies before adding protocol
  versions, product parity features, registries, or execution engines.
- Rationale: Prime P1–P7 now provide bounded development evidence for one
  product spine, but do not prove independent package composition or runtime
  substitution. The framework requires separate public integration evidence.
- Consequence: W1 fixes executable kinds, source preparation, and
  framework/product ownership; W2/W3 then prove an external extension,
  cross-package composition, and shared semantics across runtime adapters.
  Native continues in parallel and its existing control provider is not
  presented as an AgentRuntime until that contract is implemented.
- Supersedes: the post-Prime execution order in D-2026-09-05-01. Historical
  Prime and Native evidence remains valid at its named boundary.
- Evidence: Prime 7/7 closure `025bc025`, framework assessment, public inventory,
  and independent Sol contract review on 2026-09-06.

## D-2026-09-06-02 — Retain closed v1 after integration evidence

- Status: 🟢 active
- Decision: W2 and W3 require no new portable protocol version. Retain the four
  closed v1 contracts unchanged and keep source authority, implementation
  binding, runtime construction, and private services in host/provider APIs.
- Rationale: Independent installed extension, cross-package ownership, and
  cross-runtime lifecycle evidence all compose through existing exact refs,
  event/artifact edges, runtime events, and host preflight boundaries.
- Consequence: No v2 artifacts or compatibility paths are added. A future
  version requires a concrete case that v1 cannot express and complete schema,
  Python, TypeScript, fixture, authority, and migration parity.
- Evidence: `docs/architecture/protocol-evolution-decision.md`;
  `make test.public-extension`; `make test.cross-package-extension`;
  `make test.cross-runtime-extension`; commits `598f01f8`, `aa6730ff`, and
  `ad8db896`.

## D-2026-09-06-03 — Separate provider-free framework gates from release regression

- Status: 🟢 active
- Decision: Use `make test.framework-provider-free` for ordinary framework
  development. It composes core-only, cross-language contracts, installed
  extension wheels, and fixed provider acceptance as separate failure layers.
- Rationale: Whole-repository and promotion checks include product, executor,
  packaging, or external-source concerns that obscure framework integration
  failures and cost too much for the normal development loop.
- Consequence: Bounded product presets and operator-authorized run/benchmark
  commands remain explicit and outside the aggregate. Existing `make check`
  and `make promotion-check` retain their full regression behavior.
- Evidence: `docs/architecture/layered-framework-gates.md`;
  `make test.framework-provider-free`; commit `62c56284`.

## D-2026-09-12-01 — Native P7 is the sole Asterion Prime base

- Status: 🟢 active
- Decision: P7's Asterion-owned `asterion.prime` implementation is the only
  formal base for P1-P7. Rebuild P1-P6 on it. Remove Prime Agent provider,
  runtime, SDK, Gateway execution, checkout locators, and source locks from the
  distribution and formal entry points.
- Rationale: Prime-backed P1-P6 wrappers reproduce behavior but violate the
  approved P7 reset. Keeping them selectable allowed a source-coupled P1 path
  to be mistaken for native implementation and acceptance.
- Consequence: P1-P6 are unavailable until their native selectors return.
  Prime Agent may supply only exported neutral baseline logs outside execution.
  Verification stays research-weight: focused boundaries, one provider-free
  installed-wheel witness, P7 regression, then one bounded live run.
- Evidence: explicit user decisions on 2026-09-11 and 2026-09-12;
  `docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`;
  commit `49dad716`.

## D-2026-09-14-01 — Application layer free of implementation references

- Status: 🟢 active
- Decision: P1-P7 are application-level and must name only Asterion
  abstractions. No Pi reference — type, import, module path or capability name
  — may appear in `src/asterion/applications/prime/**`. The runtime seam carries
  **plain data**: approved argv, environment, and the extension resource's
  identity plus its already-acquired pinned file descriptors. Implementation
  types stay below the seam in `runtimes/`; neutral abstractions live in
  `asterion.runtime/`.
- Rationale: `prime.pi-extension` was a host capability named after an
  implementation whose payload carried live Pi objects (`PiRpcSession`,
  `PiExtensionBinding`, `PiExtensionLease`) behind exact-type assertions. The
  `agent-runtime/v1` envelope was framework-neutral, but that seam made any
  non-Pi runtime unable to satisfy a P1 or P7 assembly — substitutability was
  blocked at the capability vocabulary rather than at the protocol. The fault
  was building P1/P7 host-first and pushing the *implementation* across the
  seam, not merely the *authorization*.
- Consequence: the seam is `prime.launch`. The pinned-resource lease machinery
  moved to `asterion.runtime.pinned_extension` (it was already generic — stdlib
  plus `asterion.immutable` only), and `asterion.runtime.native_rpc` re-exports
  the RPC session under a neutral name. **Known limit:** the RPC half is neutral
  by name, not by type — `RpcSession` *is* `PiRpcSession`, so a second runtime
  would still require editing that module. Abstracting further is deferred until
  a second runtime actually exists, because abstracting against no second
  implementation tends to pick the wrong shape.
- Preserved deliberately: the extension resource stays pinned by inherited file
  descriptor and validated by `st_dev/st_ino/st_mode/st_rdev` plus loader digest,
  **never re-resolved by path**. `ExtensionLease` crosses the seam as the single
  owner of those descriptors; replacing it with a plain snapshot would either
  re-open by path (TOCTOU) or create a second descriptor owner.
- Evidence: commits `d89e48dd`, `94bfe017`;
  `grep -rnE 'Pi[A-Z]|pi_extension|pi_rpc|runtimes\.pi' src/asterion/applications/prime/`
  returns nothing; 70 targeted tests pass; detachment gate 0.

## D-2026-09-14-02 — Research-preset external engines

- Status: 🟢 active
- Context: the removed `asterion-prime-p7-solve` preset reached its ARC engine
  by running `../external-prime/arc-agi-3/venv/bin/python` over Asterion
  *source* (`PYTHONPATH=$(CURDIR)/src tools/run_asterion_prime_p7.py`). The
  driver resolved its engine root as `root.parent / "external-prime" / ...` — a
  checkout layout baked into application code — and resolved the IPython
  worker's interpreter from that same sibling venv.
- Decision: a research preset supplies an external engine as **two separate
  operator-owned things** — a root value in the environment, and pure-Python
  wheels through the isolated environment's `--with` set. P7 uses
  `ASTERION_PRIME_ARC_ROOT` plus the `arc_agi`/`arcengine` wheels, mirroring the
  existing `ASTERION_PRIME_OPERATOR_ROOT` and `ASTERION_PRIME_NODE` scalars. The
  IPython worker runs on the isolated environment's own interpreter.
- Rationale: the preset is a public surface. An operator-owned root keeps the
  external resource a configuration input rather than a compiled-in layout, and
  the `--with` set keeps the invocation installed-wheel-shaped. Baking a
  `root.parent` traversal into application code is exactly the coupling the
  Phase 1 gate exists to catch; a sibling venv interpreter additionally made the
  worker's provenance depend on a directory Asterion does not own.
- Consequence: the preset asks the operator for no provider, model, cost or
  deadline knob — only for where the external engine lives. An unset root fails
  closed at preflight (status 2) before any build or Orb entry.
- Rejected: a cross-process ARC host service. `ArcBroker` already takes its
  engine as the `_ArcEngine` Protocol, so it is architecturally reachable, but
  it rewrites P7 application logic, which the detachment spec forbids. Revisit
  only if a second consumer of the ARC engine appears.
- Evidence: commit `9a38405a`; `make -n asterion-prime-p7-solve` expands with
  `PYTHONPATH` unset; `tests/test_prime_make_presets` pins the shape and forbids
  `PYTHONPATH=src`, `ASTERION_PRIME_WORKER_PYTHON`, `external-prime` and
  `venv/bin/python` literals; detachment gate 0 before and after.

## D-2026-09-14-03 — Pi runtime injection

- Status: 🟢 active
- Context: the removed `run_asterion_prime_p7.py` reached into
  `pi/packages/coding-agent/dist/rpc-entry.js` — Prime Agent's modified Pi
  checkout, gitignored and off-limits to Asterion code. Its removal left the
  question the detachment spec had deferred: is there a *separately pinned* Pi
  runtime, or does none exist in detached form?
- Decision: the Pi runtime is an **operator-owned entry path**
  (`ASTERION_PRIME_PI_ENTRY`, paired with `ASTERION_PRIME_NODE`), and the
  operator satisfies it with the independently installed upstream package
  `@earendil-works/pi-coding-agent` from the npm global root. Asterion owns the
  fixed RPC flag set; the operator owns only where the binary lives.
- Rationale: the upstream package is a genuinely separate artifact — MIT,
  published from `github.com/earendil-works/pi`, with no prime-agent dependency
  in its manifest and a different build hash from the `./pi/` checkout. The
  spec's "separately pinned Pi runtime" is therefore real, not a relabeling.
- Consequence, and the parts that are easy to get wrong:
  - The installed Pi lives outside the repository, and the preset runs inside an
    Orb Linux VM. It is reachable there **only** through OrbStack's Mac mount,
    i.e. `/mnt/mac/opt/homebrew/...`; the host path `/opt/homebrew/...` does not
    exist inside the VM.
  - Orb's system node is v20 and the Pi imports `node:fs.globSync` (Node 22+),
    so the preset's own `npm exec --package=node@22` resolution is load-bearing
    and must not be "simplified" to the system node.
- Evidence: run `p7-live-20260914141314` PASSED — Level 1 of `ls20-9607627b` in
  20 primitive actions and 40 cells, trace sealed, replay verified, cleanup
  complete, `promotion: unpromoted`; detachment gate 0; the Pi answers
  `--version` with 0.85.1 inside Orb under node v22.23.2.

## D-2026-09-16-01 — Asterion owns compaction summarization through Pi's extension hook

- Status: 🟢 active (decided 2026-09-16; implementation pending)
- Context: P1 (`prime.ipython-coding`) exists so an IPython kernel survives context
  compaction. That only holds if the summarization prompt actually tells the model
  to record the live names, because the cells that defined them disappear from the
  context. Prime Agent achieved this by **owning a forked Pi**: its
  `buildSummarizationPrompt` appends a kernel-persistence note unconditionally, and
  its runtime's `generateSummary` calls it. Upstream
  `@earendil-works/pi-coding-agent` never published that version (there is no 0.7.x
  release at all; earliest is 0.74.0), so the note is Prime's own modification of
  the runtime. Asterion's Pi is operator-owned upstream (D-2026-09-14-03) and must
  not be forked, so it cannot modify Pi's prompt function.
- Decision: Asterion owns the summarization semantics by using Pi's sanctioned
  extension point. The extension registered on `session_before_compact` returns
  `{compaction: CompactionResult}` — producing the compaction itself — and makes
  the out-of-band model call through `ctx.modelRegistry.runtime.complete()`, which
  is Pi's own runtime, so provider routing and auth stay Pi's. Pi continues to
  supply `preparation` (what to compact, the turn-prefix split, `firstKeptEntryId`).
- Rationale: this is the mechanism Pi designed for the purpose, not a workaround.
  Upstream exposes `customInstructions`/`replaceInstructions` ("customInstructions
  replaces the default prompt") on the **tree/branch-summarization** path only; the
  compaction path has no instruction override, which is why Prime needed a fork and
  why takeover is the only route that keeps Asterion on upstream Pi.
- Consequence: `validate_compaction_witness`'s `entry.get("fromHook") is not False`
  requirement must be relaxed — it was written when Prime's Pi already carried the
  semantics and Asterion only witnessed. Under takeover the producer and the
  validator are both Asterion, so the property that check protected ("the runtime
  summarized with the prompt Asterion authorised") becomes true by construction
  rather than by verification. Structural verification is unchanged: Pi still
  chooses the range, and the native side still validates the entry, digests and
  projection reduction.
- Open costs, recorded rather than resolved: the summarization call is out of band,
  so Pi's session token accounting does not see it and Asterion must settle it
  against its own budget (two ledgers); retry, abort and failure paths on that call
  become Asterion's.
- Rejected — appending via `customInstructions`: automatic threshold and overflow
  compaction pass no instructions, and upstream's wrapper is a one-line
  `Additional focus: X`. Retained only as an interim step for P1, which drives
  compaction explicitly over RPC.
- Rejected — forking Pi: D-2026-09-14-03 makes the runtime operator-owned; a fork
  would reintroduce exactly the self-built runtime Phase 1 removed.
- Evidence verified 2026-09-16: `SessionBeforeCompactResult` is
  `{cancel?: boolean; compaction?: CompactionResult}`; `TreePreparation` and
  `SessionBeforeTreeResult` carry `customInstructions` + `replaceInstructions` and
  the compaction path does not; `npm view` shows no 0.7.x release and latest 0.85.1;
  `@ar-llm/pi-custom-compaction` is a published third-party extension doing this via
  `ctx.modelRegistry.runtime.complete()`. **Not yet verified:** Asterion's own
  implementation, and a passing P1 witness.

## D-2026-09-16-02 — A cell may name its own locals with a leading underscore

- Status: 🟢 active (decided 2026-09-16; implemented at `afb2f3b1` and verified)
- Context: the P1 cell validator denied every `ast.Name` starting with an
  underscore, alongside `forbidden_names`. Nothing constrains how the model
  names its locals, so a cell that bound `_stage_one_payload`, `_stage_one_bytes`
  and `_f` was rejected before it ran. A denied cell is reported as `uncertain`,
  which poisons the worker, which SIGTERMs its own process group and ends the
  whole run. One live run failed exactly this way on a cell that was otherwise
  correct. The existing tests never caught it because their cells name their
  locals `stream`, `accumulator` and `verified_bytes`.
- Decision: narrow the rule rather than remove it. Dunder names stay denied in
  every position, bound or not. A single-underscore name is denied only when the
  cell never binds it. `_bound_names` collects binding sites — assignment and
  loop targets, `with ... as`, parameters, comprehension targets and
  `except ... as`. `forbidden_names`, the `.attr` underscore rule and the
  underscore function-name rule are unchanged.
- Rationale: the rule exists to stop a cell reaching interpreter state, and that
  part is worth keeping — an unbound `_ih` reads IPython history, and
  `__builtins__`, `__import__` and `__loader__` reach interpreter internals
  whether or not a cell rebinds them. What was over-broad is treating a
  model-defined `_f` as the same thing. Binding a single-underscore name is
  ordinary Python with no reach beyond the cell's own namespace.
- Consequence: the fail-closed property is unchanged for every case the rule was
  written for; only cell-local naming is freed. The cost is that the rule is now
  two-part and needs its own regression matrix — a six-entry one was added
  alongside the positive case.
- Rejected — removing the underscore rule: it would admit `_ih`, `_oh` and the
  rest of the IPython surface outright.
- Rejected — fixing it in the task statement instead: the model would still be
  free to name a local `_x`, and the failure mode is a whole run lost to a
  naming choice, not a cell that misbehaves.
