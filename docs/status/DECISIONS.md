# Architectural Decisions

## Index

| ID | Status | Decision |
|---|---|---|
| D-2026-07-26-01 | 🟢 active | Anchor explicit operator configuration to the environment-file directory |
| D-2026-07-31-02 | 🟢 active | Complete every DCI instance's 50-case result before considering full datasets |
| D-2026-08-10-03 | 🟢 active | Stage Prime-managed and native kernels as peer control providers |
| D-2026-08-27-04 | 🟢 active | Quiesce host-owned ecosystem projections before cleanup |
| D-2026-09-02-05 | 🟢 active | Keep Prime Smoke Core and Smoke Full evidence as distinct closed claims |
| D-2026-09-02-06 | 🟢 active | Make Prime a full RLM-harness capability program, not a Smoke Full roadmap |
| D-2026-09-05-01 | 🟢 active | Prime and Native remain parallel runtimes; close Prime's seven end-to-end scenarios first |
| D-2026-09-06-01 | 🟢 active | Resume the framework-first integration sequence after Prime closure |
| D-2026-09-06-02 | 🟢 active | Retain closed v1 contracts after W2/W3 integration evidence |
| D-2026-09-06-03 | 🟢 active | Separate provider-free framework gates from release regression |

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

- Status: 🟢 active
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

- Status: 🟢 active
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

- Status: 🟢 active
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
