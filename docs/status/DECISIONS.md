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
| D-2026-09-17-01 | 🟢 active | Denominate the compaction reservation in tokens and convert at the call site |
| D-2026-09-17-02 | 🟢 active | Treat `retained_message_count` as nullable; Pi states retention by entry id |
| D-2026-09-17-03 | 🟢 active | Keep Pi's compaction reserve at upstream's default |
| D-2026-09-17-04 | 🟢 active | Keep the witness rebuild equality; drop the byte shrink bound |
| D-2026-09-18-01 | 🟢 active | Cross-process continuity inherits runtime-binding SHAs from prior identity |
| D-2026-09-18-02 | 🟢 active | P3 child-runner is in-process by default; subprocess is fallback-only |
| D-2026-09-19-01 | 🟢 active | P5 bounded-autonomy is one loop controller host service; limits-path has 3 refusal scenarios (cancellation folds in) |

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
  every position, bound or not. A single-underscore name is admitted only where
  the cell provably bound it first, in the scope where the read happens: a plain
  bind-then-use in the same block, a `with ... as` name inside its own body, a
  loop target inside its own body, a parameter inside its own function. A
  binding inside an `if`, a `try`, a loop body or a comprehension never counts
  for code outside it, and a read before the binding is not admitted either.
  `forbidden_names`, the `.attr` underscore rule and the underscore
  function-name rule are unchanged. IPython's own names — `_`, `_i`, `_ii`,
  `_iii`, `_ih`, `_oh`, `_dh`, `_exit_code`, and the per-cell `_i1`..`_iN` —
  are denied outright, bound or not. That last part is what makes counting a
  `with` body's bindings outside it sound instead of fail-open: a `with` body
  can suppress its own exception through `__exit__`, so a name it never bound
  can still be read afterwards, and the only thing such a read could reach is
  precisely those names. A name the cell invents has nothing behind it, so an
  unbound read of it is a `NameError`, not a disclosure. Cost, recorded
  rather than hidden: `_i` is a common loop variable, so `for _i in range(n)`
  is now refused.
- Rationale: the rule exists to stop a cell reaching interpreter state, and that
  part is worth keeping — an unbound `_ih` reads IPython history, and
  `__builtins__`, `__import__` and `__loader__` reach interpreter internals
  whether or not a cell rebinds them. What was over-broad is treating a
  model-defined `_f` as the same thing. Binding a single-underscore name is
  ordinary Python with no reach beyond the cell's own namespace.
- Consequence: the fail-closed property is unchanged for every case the rule was
  written for; only cell-local naming is freed. The cost is that the rule is now
  two-part and needs its own boundary matrix — a nineteen-case check was built
  (six admitted, thirteen denied). An automated security review then found that
  the first implementation's exemption was tree-wide rather than order- and
  scope-aware, admitting four shapes whose binding never runs: `if False: _ih =
  1` then reading `_ih`, `for _ih in (): pass` then reading `_ih`, a
  comprehension target, and a read placed before the binding. Each left the read
  falling through to the IPython namespace, which is exactly what the rule
  exists to stop. Fixed at `b096e589`, and the four shapes are now regression
  cases. The finding is why the rule reads "provably bound first" rather than
  "binds it somewhere".
- Rejected — removing the underscore rule: it would admit `_ih`, `_oh` and the
  rest of the IPython surface outright.
- Rejected — fixing it in the task statement instead: the model would still be
  free to name a local `_x`, and the failure mode is a whole run lost to a
  naming choice, not a cell that misbehaves.

## D-2026-09-16-03 — Poison the worker only for a cell that actually ran

- Status: 🟢 active (decided 2026-09-16; implemented at `e4fbb1ea` and verified)
- Context: `_validate` refuses a cell before `run_code` is ever called, so a
  refused cell has executed nothing. A bare `except BaseException` merged that
  case with a failure inside `run_code`, and any failed cell poisons the
  worker, whose close path SIGTERMs its own process group. One exploratory
  cell therefore ended the entire run — including when that turn's work was
  already finished. A live run did exactly that: the setup cell wrote the
  file, a second cell opened with `import os` to check its size, was correctly
  refused, and killed the session. Five consecutive witness runs died this way
  or by one of the three sibling defects, none of them reaching compaction.
- Decision: the frame carries `executed`, true only once the cell has been
  handed to `run_code`. The host poisons when a cell that ran failed or was
  cancelled, and keeps the poison when the frame's shape was rejected outright
  (`observation is None`). A cell refused before execution is still denied,
  still reported `uncertain`, and still counts its audit denial; the worker
  simply stays usable. `P1CellObservation.executed` defaults to True so an
  older shape is treated conservatively, and it is included in the observation
  digest so a frame cannot understate it without detection.
- Rationale: the poison protects against continuing on a worker whose state is
  unknown, and that reason only applies once a cell has run. A cell stopped at
  the AST stage leaves the namespace, the file root and the accumulator object
  exactly as they were, so there is nothing to protect. Applying the same
  penalty to both cases buys no safety and costs the entire run.
- Consequence: the fail-closed property is unchanged for every case the poison
  was written for — anything that executed may have left a side effect and
  remains fatal. The cost is a second cell state to reason about, and the
  boundary is now asserted from both sides in the worker tests.
- Rejected — keep poisoning on every failure: it makes the witness fragile to
  any model mistake, refused or not, and an AST refusal is provably
  side-effect-free.
- Rejected — isolate failures at the turn level: the next turn could then
  build on an unfinished predecessor, and stage one's whole point is the
  cross-turn object surviving intact.

## D-2026-09-17-01 — The compaction reservation is denominated in tokens

- Status: 🟢 active
- Context: `quote_compaction_reservation` names its constants
  `_..._TOKENS_MAX` and prices cost per million tokens, but the caller in
  `context.py` fed it `len(request.encode())` — byte counts. Cost was
  overstated roughly fourfold and every cap was silently four times tighter
  than its own name, which is why a real 6.9 KB request was refused.
- Decision: Convert at the call site, with a four-bytes-per-token ceiling, and
  keep the arithmetic in tokens. Derive `_INPUT_CAP_MAX` from the reservation
  total rather than leaving it independent: the two branches are asymmetric by
  construction (the main request carries the whole serialized conversation,
  the turn-prefix request only a fragment), so a symmetric per-branch cap
  contradicts the total and can never be approached.
- Rationale: The tell was that the operator's own
  `_COMPACTION_INPUT_CAPS = (4096, 4096)` is the same number as the old
  `_INPUT_CAP_MAX` — those constants were always tokens, so only the call site
  was wrong. A ceiling over-states the reservation, which is the fail-closed
  direction for a budget.
- Consequence: The total reservation remains the binding limit and the cost
  ceiling is unchanged. What changes is which inputs are admissible.
- Evidence: commit `2f744bf5`; the host approved a proposal for the first time
  (`host-quote caps=(1740, 261) approved=True`); `test_asterion_prime_context`
  and `test_asterion_prime_p1_operator` boundary assertions.

## D-2026-09-17-02 — `retained_message_count` is nullable

- Status: 🟢 active
- Context: The extension's `preparedMaterial` read
  `summary.retainedMessageCount`, which Pi never emits — the name appears zero
  times in Pi's bundle, and `createCompactionSummaryMessage` produces only
  `{role, summary, tokensBefore, timestamp}`. The field appears in no spec or
  plan, entered with the witness feature, and the only thing that ever supplied
  it was the extension test's own fake.
- Decision: Treat the field as nullable end to end, matching what
  `projectPrimeContext` and the host's message validator already tolerated. The
  host's lower bound applies only when a producer actually supplies a value —
  the takeover shape of D-2026-09-16-01.
- Rationale: Pi states retention by `firstKeptEntryId`, not by a count, so
  under the witness shape the field has no possible producer. Deriving a count
  locally was rejected: it would make the host's `declared >= actual` bound a
  predicate that can never fail.
- Consequence: `countRebuiltContext` does not use the field, so size accounting
  is unaffected. The field keeps its slot for the takeover implementation.
- Evidence: commit `c03eecad`; measured `q1-summaryKeys` and
  `q4-rawRetained=undefined`; Pi bundle search returning zero occurrences.

## D-2026-09-17-03 — Pi's compaction reserve stays at upstream's default

- Status: 🟢 active
- Context: Pi caps a compaction summary at
  `min(floor(0.8 * reserveTokens), model.maxTokens)`. Asterion set
  `reserveTokens: 4096`, a quarter of Pi's default of 16384, giving a 3276
  cap; Pi reported `generation hit the token cap and the summary is
  incomplete` (`stopReason === "length"`), so compaction never completed and
  the witness waited out its 60 s.
- Decision: Restore `reserveTokens: 16384` on both sides — the operator's
  written `settings.json` and the extension's `SETTINGS`, which the extension
  asserts are exactly equal.
- Rationale: This restores upstream's value rather than inventing one. Measured
  both ways, twice each: 4096 fails, 16384 completes.
- Consequence: **Measured, not witness-confirmed** — the witness still does not
  pass. `compaction_budget` now under-reserves for the larger ceiling and is
  deliberately left that way rather than silently widened.
- Evidence: commit `0f1a7d98`; `compaction_end` carrying a full result with no
  `errorMessage` at 16384, and the token-cap error at 4096.

## D-2026-09-17-04 — Keep the witness rebuild equality; drop the byte shrink bound

- Status: 🟢 active
- Context: The witness's `persisted()` required both that the rebuilt context
  equal the expected projection and that `countRebuiltContext(post) <
  pre_units`. Pi reports its own compaction as shrinking
  (`tokensBefore: 1863 → estimatedTokensAfter: 1353`), but the metric compared
  canonical-JSON **bytes**, and a markdown-heavy summary costs more bytes per
  token than the conversation it replaces. Five measured live runs landed on
  both sides of the bound with the projections equal every time, the closest
  refusing by 23 bytes (`post=9952 pre=9929`).
- Decision: Drop the byte bound on both sides — the extension's `persisted()`
  and the host's `validate_compaction_witness`. The projection equality is the
  invariant; the summary's own size is Pi's to choose.
- Rationale: The equality already binds the rebuild to Pi's retained tail plus
  the summary, so the only free quantity is the summary's size. A bound on it
  refused legitimate compactions rather than catching a pathology, which makes
  it a mis-refusal rather than a guard.
- Consequence: `pre_units` stays validated against the pre-context projection
  (`pre_units == count_rebuilt_context(pre)`) and `after_context_tokens` is
  still reported as evidence; only the bound is gone. A replacement in Pi's own
  token unit was rejected for this pass: the after-count lives in the
  compaction *result*, not the entry, so the persisted path has no producer for
  it. `context.py` used the same metric and moved with it.
- **Applied at all six enforcement points.** The clause also sat in
  `P1WorkerCheckpoint.__post_init__` (`p1/worker.py`), `P1StageTwoRelease`
  (`capabilities/prime_ipython_coding_native/host.py`, the gate that authorizes
  stage two), the oracle's `verify_stage_two`, `P1OracleReceipt`, and the native
  receipt. Live runs were refused at the checkpoint (`7608 → 8657`, which is
  why the stage-two milestone never arrived) and at the oracle (`8260 → 8596`).
  The operator ruled the sites one decision, not several. Both counts remain
  required in every structure and are still carried as evidence.
- Evidence: commits `97c309e4`, `0672e420`, `4f891d66`; the five measured
  witness pre/post pairs and the two live refusals above; decision taken by the
  operator on 2026-09-17.

## D-2026-09-18-01 — Cross-process continuity inherits runtime-binding SHAs from prior identity

- Status: 🟢 active
- Decision: When the P4 operator opens a private_root across a process
  boundary (FilePrimeSessionStore.open_continued), the next identity MUST
  inherit the prior identity's pi_command_sha256,
  extension_binding_fingerprint, and ceilings_sha256 field values.
  Only generation, worker_identity_sha256, and private_root_identity are
  allowed to differ between prior and next; every other identity field
  is enforced equal by _enforce_continuation_rules and the rules do not
  negotiate.
- Rationale: The continuation rules already fail closed on drift; the
  recover-mode next identity constructed from hardcoded literal SHAs only
  matched same-build commit+recover pairs (a single operator invocation).
  A pre-baked prior sealed by a different build (the fixture scenario, or
  any real cross-version deployment) was rejected at the rules with no
  recoverable cause. The hardcoded literals were a same-build convenience
  that became a cross-build correctness gap. The fix preserves the
  same-build convenience as the default for commit-mode (where no prior
  exists) and copies the prior values in recover-mode.
- Consequence: _build_identity accepts the three runtime-binding SHAs as
  keyword args with the same literals as defaults; _recover_mode passes
  prior_identity.pi_command_sha256,
  prior_identity.extension_binding_fingerprint, and
  prior_identity.ceilings_sha256. The commit-mode path is unchanged.
  A fixture-based in-process test pins the cross-build recovery invariant
  so a future literal-restoration regression is caught at unit-test speed.
- Evidence: commit 048078d3 (Task 14 fixture + secondary fix);
  tests/test_asterion_prime_p4_operator.py::P4OperatorRecoverFromFixture;
  prior checkpoint digest 35af5974...ba72 matches fixture's sealed
  checkpoint; _enforce_continuation_rules no longer rejects the cross-build
  recover path; decision taken by the operator on 2026-09-18.

## D-2026-09-18-02 — P3 child-runner is in-process by default; subprocess is fallback-only

- Status: 🟢 active
- Decision: `prime.child-runner` (the new host service introduced by
  Phase 7 / P3) uses an in-process child session factory as its
  default path. Admitted children share the parent's process and
  compose `PrimeSessionBackend.attach(next_identity)` for budget /
  cancellation gating. Subprocess supervisor is reserved as an
  application-explicit fallback (e.g., to isolate a child that has
  consumed a large context, or to enforce a per-child cost ceiling)
  and is **not** implemented in Phase 7.
- Rationale: P1–P7 are applications that demonstrate Asterion Prime's
  capabilities and architecture, not new runtimes or parallel agent
  kernels. P3's witness (detachment spec L342–L344) is about depth /
  concurrency / budget / cancellation limits under recursive
  composition — limits that the existing Asterion control / session
  backend already enforces. An in-process child session factory
  composes those framework primitives directly; a subprocess supervisor
  would re-introduce the cross-process supervisor pattern that Phase 6
  (P4) introduced specifically for cross-generation recovery, which
  P3 does not need (P3 has no recovery semantics). The closed-enum
  refusal reasons (`depth-exceeded`, `concurrency-exceeded`,
  `budget-exceeded`, `cancelled`, `session-backend-rejected`) are the
  public contract — keeping them at the application layer makes them
  visible to the operator and the limits-witness without coupling
  them to a runtime seam.
- Consequence: `prime.child-runner` is implemented as a thin
  application-level host service that delegates admission to the
  existing `PrimeSessionBackend` budget gate. The child identity is
  constructed by the operator via
  `root_identity.bump_generation()` (preserving the runtime-binding
  SHAs per D-2026-09-18-01). The four refusal scenarios are exercised
  by `make asterion-prime-p3-run-limits` against the same operator in
  `mode=limits`. If a future P5 / P6 phase requires subprocess
  isolation, the fallback path is reserved by design but
  un-implemented and un-promoted.
- Evidence: commit 602d5971 (Phase 7 design-first pass — spec +
  plan); docs/superpowers/specs/2026-09-18-asterion-prime-p3-native-design.md
  §"Newly introduced in Phase 7"; docs/superpowers/plans/2026-09-18-asterion-prime-p3-native.md
  §"Components" Task 3 / Task 8 / §"Out-of-scope" / §"Open risks" 1.

## D-2026-09-19-01 — P5 bounded-autonomy is one loop controller; limits-path folds cancellation

- Status: 🟢 active
- Decision: `prime.bounded-autonomy` is implemented as a **single
  host service** (one new `HostServiceFactoryBinding` in
  `src/asterion/applications/prime/services.py`), not as three
  separate `prime.proposer` / `prime.verifier` / `prime.repairer`
  services. Inside the controller, `_propose_step()` /
  `_verify_step()` / `_repair_step()` are private methods, not
  separate host-service injection points. The default path is
  **in-process** (mirror D-2026-09-18-02); subprocess supervisor is
  not implemented in Phase 8. The limits-path Makefile target
  (`make asterion-prime-p5-run-limits`) asserts **three** refusal
  scenarios in fixed order — `iteration-cap-exceeded`,
  `duration-cap-exceeded`, `no-progress` — and cancellation is
  folded into the closed enum rather than emitted as a fourth
  witness record.
- Rationale: P1–P7 are applications that demonstrate Asterion
  Prime's capabilities and architecture, not new runtimes or
  parallel agent kernels. P5 demonstrates **bounded autonomy** at
  the application level — the framework already exposes
  `PrimeSessionBackend` budget / cancellation gates that the loop
  composes through; a separate proposer / verifier / repairer
  triple would multiply host-service surface area without
  adding capability, and would split a single tight invariant
  (`terminal_reason`) across three injection points. In-process
  default mirrors D-2026-09-18-02's reasoning for the P3
  child-runner: the loop has no recovery / cross-process
  semantics, so the cross-process supervisor pattern that P4
  introduced for `prime.continuity-store` does not apply.
  Cancellation folds into the closed enum because it is a
  *side-effect* of the duration gate, not an independent limit;
  P3's four scenarios (depth / concurrency / budget /
  cancellation) correspond to four independent limits, but P5's
  limits set is three (iteration / duration / no-progress), and
  emitting a fourth cancellation record would add cost without
  adding coverage that the closed-enum contract doesn't already
  give us. A future caller can still observe cancellation
  through `terminal_reason = "cancelled"` in any single-record
  receipt.
- Consequence: The loop controller's public surface is
  `BoundedAutonomyLoop` (async context manager with
  `public_identity`, `run_loop(...)`, `last_step_timed_out`) and
  `create_bounded_autonomy_host_service(context)`. The
  `terminal_reason` field on `P5NativeReceipt` is the closed
  5-element enum, and the closed-enum contract is enforced at
  the type level (`Literal[...]`). The Phase 5/7 fixture /
  capability-package / Makefile patterns are reused unchanged.
  The provider gate stays closed until `make
  asterion-prime-p5-run` AND `make asterion-prime-p5-run-limits`
  both exit 0; a single Task-16 commit then publishes P5 to
  `create_provider()` (5 → 6 apps) and `asterion.application_index`,
  mirroring the Phase 6 P4 closure and the Phase 7 P3 closure.
  If a future P6 phase wants a separate proposer / verifier /
  repairer injection surface, it must not split the closed
  `terminal_reason` enum.
- Evidence: commit 8a3b57cb (Phase 8 design-first pass — spec +
  plan); docs/superpowers/specs/2026-09-19-asterion-prime-p5-native-design.md
  §"Newly introduced in Phase 8" / §"Stopping conditions" /
  §"P5 oracle" / §"Witness strategy"; docs/superpowers/plans/2026-09-19-asterion-prime-p5-native.md
  §"Components" Task 3 / §"Verification" / §"Open risks".
