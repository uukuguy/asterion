# Current State

## Project Snapshot

- Project: Asterion
- Active branch: local `main`; implementation verification is scoped to its
  named boundaries. Phase 1 removal work advances local `main` ahead of
  `origin/main`; the remote is no longer the canonical head for this work.
- Theme-level focus: remove every Prime Agent execution edge from the Asterion
  distribution, revalidate native P7, then rebuild P1-P6 on that implementation.
- Project route: managed
- Canonical worklist:
  `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`
  — 9-phase program roadmap in the spec's mandated order; Phase 1 detailed to
  task level. Phases 3-9 receive their own plans when reached.
- Active work package: **Phase 4** — rebuild P1 (`prime.ipython-coding`).
  **Phase 3 is complete: native P7 is revalidated end to end.** Run
  `p7-live-20260914141314` solved Level 1 of `ls20-9607627b` in 20 primitive
  actions and 40 persistent IPython cells, `partial_game_score` 3.571429,
  terminal reason `level-completed`, with the trace sealed, replay verified and
  cleanup complete — driven by the **independently installed upstream Pi**,
  with no Prime Agent and no Prime checkout anywhere in the path. Phases 1-3 are
  complete.
  Phase 1 (legacy release-surface removal and the semantic source-detachment
  gate): 11/11 tasks, gate 1881 → 0, entry points 3/5/2. Phase 2 (P7 research
  preset as an installed-wheel invocation, D-2026-09-14-02): the preset builds a
  wheel, unsets `PYTHONPATH`, and supplies the ARC engine as an operator-owned
  root plus pure-Python wheels. Native P7 remains the implementation anchor.
  **P1-P7 native implementations: 0 of 7 — all unavailable by design.** P1-P6
  never had native implementations; P7 does, but it is not yet proven to run
  end-to-end from the installed route, so it too stays unavailable until Phase 3
  closes. Full benchmarking and production promotion remain separately
  authorized work.
- W0 inventory alignment, W1a executable-kind consistency, W1b exact source
  preparation, W1c runtime-provider separation, W1d core-only isolation, and
  W2 public extension reference, W3a cross-package evidence, W3b
  cross-runtime evidence, W4 protocol review, and W5 layered gates are complete.
  The public SDK's `research` kind now reaches its exact implementation through
  provider, assembly, and runner. Package sources now share one prepare/load
  lifecycle with exact lock and authorization binding. Prime now owns its exact
  runtime binding and P1-P7 routes; the domain-neutral default registry contains
  no Prime routing. The dependency-free wheel gate imports the complete core
  allowlist without product modules. The external Acme reference wheel now uses
  only `asterion.capability_sdk` and `asterion.application_sdk`, owns its exact
  application resources and runtime binding, and executes through the installed
  CLI outside the source tree. Two independently built Acme and Contoso wheels
  now compose and execute in either installation order with exact per-package
  ownership derived from one prepared catalog snapshot. The same installed
  Acme capability now preserves exact public outputs through Acme and Contoso
  runtime adapters, including two cancellation timings and shared preflight
  rejection boundaries. W4 found no demonstrated need for v2 and retains all
  four closed v1 contracts. The framework integration worklist is complete at
  its named development boundary.
- Git recovery closure: one clean local `main` branch and one primary worktree
  remain. A verified complete-history bundle preserves every audited committed
  head, and separate patches/archive preserve accepted uncommitted source
  state. Phase 1 detachment work advances local `main` beyond `origin/main`.

## Current Architecture

- Asterion is a composable multi-runtime framework. DCI is a reference product;
  generic framework layers remain domain-neutral.
- Python owns orchestration, exact resolution, authority, admission, budgets,
  canonical journal/state, application execution, and public-safe evidence.
- TypeScript validates shared contracts and may own Asterion Pi extension or
  Node integration code. The Prime Gateway execution surface has been removed
  from the distribution. Rust remains limited to controlled execution.
- `asterion.prime` and `asterion.native` are peer agent integrations over the
  shared Asterion framework. P1–P7 are applications, not the base agent kernel.
  Neither integration may authorize itself or bypass runners and injected host
  services.
- **P1-P7 are application-level: nothing Pi-related may appear there.** The
  application layer names only Asterion abstractions; the Pi implementation
  lives below it. Enforced by
  `grep -rnE 'Pi[A-Z]|pi_extension|pi_rpc|runtimes\.pi' src/asterion/applications/prime/`
  returning nothing.
- **The runtime seam is `prime.launch`** — plain data only (approved argv,
  environment, extension resource identity and its already-acquired pinned file
  descriptors). It replaced `prime.pi-extension`, which was named after an
  implementation and carried live Pi objects across the seam. Neutral
  abstractions live in `asterion.runtime` (`pinned_extension`, `native_rpc`);
  `runtimes/pi_*` remains the Pi implementation.
- **Runtime selection is a configuration decision, not application logic.** The
  CLI resolves `runtime_id` from `--runtime` or the application's single
  declared runtime, then selects the matching assembly. Upper layers execute
  runtime-level semantics (`RunRequest`/`RunEvent`/`RuntimeManifest`) and must
  not construct a specific kernel invocation.
- **`./pi/` is Prime Agent's modified Pi**, gitignored and untracked. Asterion
  never depended on it: `runtimes/pi_rpc.py` takes its Pi command by injection.
  Asterion's own Pi extension resources live at `capabilities/dci/resources/pi/`.
- The selected P7 solving route uses native `asterion.prime` plus Asterion's Pi
  integration. It does not import Prime Agent source or SDK. The former P7 SDK
  provider, gateway, CLI host, TypeScript bridge, seeded command, and package
  artifacts have been removed.
- Provider-neutral ledgers keep implemented, provider-free, bounded-provider,
  system-parity, and native-parity claims distinct. Evidence promotes only the
  exact scenario and domain it proves.
- All client surfaces must consume one validated public event stream and one
  private-value service. They may not introduce alternate composers or runners.
- The approved design places a new closed `asterion.agent-client/v1`
  projection above `ControlHost`; existing control/runtime v1 contracts remain
  unchanged. `agent-client/v1` is a framework-level contract consumed by the
  surviving `asterion.client` surface, not a Prime-Gateway-backed projection;
  its schema is retained unconditionally.
- Prime Agent may exist only as an external black-box baseline whose exported
  neutral logs are read outside execution. Credentials, provider configuration,
  private content, and generated evidence remain operator-owned.

## Verified Boundary

- W5 is complete. `make test.framework-provider-free` separates and passes the
  core-only import gate, Python/TypeScript contract gate, three installed-wheel
  extension gates, and fixed `dci-agent-lite` acceptance. It ran no provider
  operation, model, Docker, external Prime source, general run, benchmark, or
  full release regression. `make check` and `make promotion-check` retain their
  prior full-regression roles. Sol approved the final dependency closure.

- W4 is complete. `docs/architecture/protocol-evolution-decision.md` maps every
  demonstrated W2/W3 requirement to an existing v1 field or host/provider API.
  No schema, closed Python validator, or TypeScript contract changed across the
  evidence range. Sol approved retaining v1 and the explicit future-version
  triggers.

- W3b is complete. `make test.cross-runtime-extension` builds and installs the
  core, Acme, and Contoso wheels, executes the same Acme capability through
  `acme.inline` and `contoso.inline`, and compares its exact public events and
  artifacts. Its isolated installed probe verifies normal lifecycle shape,
  cancellation before and after `run.started`, missing-service rejection, and
  crossed-runtime rejection. Sol approved the closed-v1 boundary.

- W3a is complete. `make test.cross-package-extension` builds the core, Acme,
  and Contoso wheels, installs them in both extension orders, and executes the
  exact Contoso application outside the source tree with byte-identical output.
  Four tests also reject missing Acme, raw multi-package injection, swapped
  bindings, and hostile catalog ownership before runtime or implementation
  execution. Sol approved the single-snapshot ownership boundary.

- W2 is complete. `make test.public-extension` built the core and reference
  extension wheels, installed both without dependencies into a clean external
  virtual environment, proved metadata-only and selected-only provider loading,
  and executed `acme.research-application@1.0.0` through `acme.inline`. Eight W2
  tests and 95 related runtime, provider, Prime, DCI, and core boundary tests
  passed; Sol approved the implementation with no remaining material findings.

- **Historical (Prime Gateway-backed, pre-detachment).** The following were
  PASS against the now-removed Prime Gateway execution surface and are recorded
  as historical compatibility evidence, not native Asterion closure:
  - Prime Gateway `ecosystem.capabilities` 10/10 provider-free;
  - H-035 client-interface parity (nine `interface.*` rows 9/9);
  - H-036 operational parity (`operation.*` six rows 6/6), closed at the pinned
    Prime source `a18809e00ea30638584d87b3afea7285a9d7296c`;
  - `interfaces.operations` 15/15 Prime Gateway rows;
  - H-037 `Verified-system-parity` 61 passed, zero ledger blockers, two excluded
    rows.
  - Climb cycles 35 through 38 (`check.client-interfaces-closure`,
    `check.operational-parity-closure`,
    `prime-system-parity-operation-host-callback`,
    `check.native-controller-core-provider-free`) each occurred once under the
    removed Prime Gateway surface.
- Native controller core is PASS at H-038. The exact provider-free receipt
  reports 10 common scenarios, five differential cases, eight crash points, all
  six prohibited operation counters at zero, and `promoted_feature_ids=[]`.
  Every one of the 61 compound `asterion.native` parity rows remains Missing.
- `OperationManager` now exposes immutable dispatcher identity, and the
  reviewed Python callback server accepts only exact identity-bound frames over
  a private `0600` Unix socket.
- The reviewed TypeScript callback client now issues one exact request per Unix
  connection with write-side EOF, strict response validation, no retries, and
  an absolute deadline. The sole production descriptor path assembles that
  client into `PrimeOperationGateway`.
- The reviewed Python factory now snapshots one exact injected dispatcher,
  supplies a fresh 256-bit callback descriptor, and shares one callback-first,
  process-then-callback managed transport across both Prime clients.
- Root and nested child sessions now bind distinct identity-exact managers to
  both provider context and `ControlHost`. The real Node sidecar proves
  execute, reconcile, cancel, missing-callback, failure/no-retry, body-free
  frames, cleanup, and zero Prime effects. Task 6's repository,
  cross-language, promotion, distribution, and independent review gates pass.
- H-038 passed canonical execution exactly once after clean pre-H gates:
  focused Native target, exact verifier, `make check`, `make promotion-check`,
  and `git diff --check`. Canonical state routes to
  `phase-3.2-native-verified-loop-design`; no compound Native row was promoted.
- Phase 3.2 provider-free receipt evidences nine Native Verified-loop rows
  with zero external counters. A parameter-free operator-owned host reads the
  existing `.env` configuration. Its second bounded run passed Gateway
  descriptor validation, lifecycle acceptance, and the checkpoint manager.
  Its current exact boundary is the manager idle barrier before the main RLM
  probe; the two bounded rows remain
  `External-limited`. Native `Verified-loop` and all compound Native rows
  remain Missing.
- Prime Smoke Core is closed: the real `make prime-smoke-core` receipt is
  PASS with one completed terminal and proves generated-program admission,
  depth policy, two-child work, causal messaging, active reconnect,
  application/oracle, healthy observations, budget, cleanup, and public
  privacy. This evidence is not Smoke Full or parity promotion evidence.
- Historical P1-P7 development runs used Prime Agent SDK/Gateway execution.
  Their traces remain behavioral history only and prove no native Asterion
  Prime application closure. Formal legacy selectors and packaged execution
  surfaces are pending removal; P1-P6 remain unavailable until rebuilt.
- Native Asterion Prime P7 is live verified independently of that historical
  four-action reproduction. Run `p7-live-20260909065351` used
  `deepseek-v4-flash` to complete Level 1 of `ls20-9607627b` in 23 primitive
  actions and 43 persistent IPython cells, with partial score `3.267621`, a
  sealed 25-entry trace, verified replay, and complete cleanup. No answer or
  action sequence was seeded. Exact digests and unrecorded-stat boundaries are
  in `docs/status/ASTERION-PRIME-P7-EVIDENCE.md`.

## Open Problems

- Phases 1 and 2 are complete: the Prime Agent provider/runtime/SDK/Gateway
  execution surface is removed from entry points, package data, Make targets,
  tools, and acceptance tests, and the P7 research preset is an installed-wheel
  invocation.
- **`tests/test_prime_p7_native_installed` was red and is now fixed** (Phase 3,
  2026-09-14). Root cause, found by capturing the exception that two catch-alls
  discarded: commit `26519254` (2026-09-11) made `agent_end` the native prime
  round terminal and stopped recognizing `agent_settled`, and it updated five
  test files but not the shared fixture. The fixture kept emitting the old
  terminal, so the validator rejected it as an invalid event type. Fixed at
  `tests/fixtures/asterion_prime/fake_pi_rpc.py` (only user of that fixture).
- **Why the rot went unseen — stated precisely.** The test is *not* excluded
  from discovery: `make test` runs `unittest discover -s tests`, whose default
  `test*.py` pattern collects it. It is absent from every *targeted* gate, and
  the full suite is not run routinely under this project's research-intensity
  rule, so no focused run after 2026-09-11 executed it. An earlier note here
  said it was "in no gate"; that was an overstatement and is corrected.
- **Diagnosability gap, recorded not fixed.** A capability failure is reported
  publicly as the classified `failure_class` only — `runner/composed.py` raises
  `ApplicationRunError(...) from None` and `lifecycle.fail_capability` records
  just `capability-execution-failed`. The cause is therefore discarded rather
  than captured privately, and locating this one-line fixture defect required a
  temporary probe. The suppression is consistent with the redaction rules and
  should not be loosened; the missing half is a private capture path.
- **The P7/P1 coupling is RESOLVED (2026-09-15).** The resolver was never at
  fault: validating every published application and failing closed is a
  deliberate integrity rule — a published application must be executable. The
  defect was that `create_provider()` published P1, which has no native package
  and no installed-route witness, breaching the spec's omit-unmigrated rule.
  P1 is no longer published and P7 supplies only its own package. Measured
  against a stashed baseline over the 208-test prime set: **zero new breakage,
  one pre-existing failure fixed**. This enforced D-2026-09-12-01; it decided
  nothing new, so it adds no DECISIONS entry.
- **P1's operator resolves itself out of the provider** (it filters
  `create_provider()` down to P1, `p1/operator.py:238`), so while P1 is
  unpublished 15 route tests in `test_asterion_prime_p1_operator.py` **skip with
  an explicit reason** and the 3 that avoid that fixture still run. Phase 4
  restores publication and removes both guards. Note the shared shape: *both*
  operators filter the global provider rather than declaring their own
  application metadata, which is why publication state reaches so far.
- **A pre-existing red test points at the compaction area.**
  `test_python_admits_and_privately_persists_real_locked_pi_compaction`
  (`tests/test_asterion_prime_context.py`) fails on the pristine tree with
  `PrimeContextError: invalid Prime context witness`. Not investigated; its name
  places it in plan risk 1's family, which remains untested.

- **Plan risk #2 is RESOLVED in the affirmative: a detached Pi artifact exists
  and is named.** `@earendil-works/pi-coding-agent@0.85.1`, an MIT npm package
  from the upstream `github.com/earendil-works/pi` project, installed at
  `/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/`. Its RPC
  entry is `dist/bundle/rpc-entry.js`, and its `package.json` names no
  prime-agent dependency. It is a **different build** from the `./pi/` checkout
  the removed driver reached into (distinct SHA-256), so the two are not the
  same artifact and injecting the installed one does not reach into Prime
  Agent's tree. **A first pass here wrongly concluded no detached Pi existed
  after inspecting only `./pi/`; that conclusion was drawn from one `ls` and is
  withdrawn.** Discovered by searching `PATH` (`/opt/homebrew/bin/pi` symlinks
  into the npm global root), which is where an installed Pi actually lives.
- **Verified wiring for the P7 preset (all four values, checked in Orb).**
  OrbStack mounts the Mac at `/mnt/mac` and `/Users` at the same path, so the
  installed Pi is reachable *inside* Orb only via the `/mnt/mac` form:
  `ASTERION_PRIME_PI_ENTRY=/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js`.
  `ASTERION_PRIME_ARC_ROOT=/Users/sujiangwen/sandbox/agentic-2026/external-prime/arc-agi-3`
  (visible in Orb at the same path, with both wheels and `environment_files/ls20/`).
  `ASTERION_PRIME_OPERATOR_ROOT` is the mounted checkout. `DEEPSEEK_API_KEY` is
  present in `.env`.
- **Orb's system node is v20.19.4 and is too old** — the Pi imports
  `node:fs.globSync`, which Node 22 added, so running it under `/usr/bin/node`
  fails with `SyntaxError: ... does not provide an export named 'globSync'`.
  The preset's own `npm exec --offline --yes --package=node@22` resolution
  returns v22.23.2 and works. Do not "simplify" the preset to use the system
  node.
- **Confirmed by running:** inside Orb, under the preset's node@22, the named Pi
  answers `--version` with **0.85.1**. The Pi dependency is therefore no longer
  an open question; only the live solve itself remains unrun.
- **The live P7 run PASSED (2026-09-14, operator-authorized).** Receipt
  `receipt_sha256=c00e3263cb2842dbe854cd4950ea2d2ec75859c21189f2bb101e66efed05c554`,
  replay
  `sha256:5b469c2ab7acfcb61d643d885453f744ef201d2a7765bcac1e04b0ac7afaea1b`,
  `promotion: unpromoted`. Private artifact at
  `.asterion-private/prime-p7-live/p7-live-20260914141314/` (mode 0700, gitignored).
  Compare the earlier Prime-Agent-era run `p7-live-20260909065351`: 23 primitive
  actions, 43 cells, score 3.267621. The detached route reached the same level
  in fewer actions and cells.
- The preset reads four operator-owned values (`ASTERION_PRIME_OPERATOR_ROOT`,
  `ASTERION_PRIME_ARC_ROOT`, `ASTERION_PRIME_NODE`, `ASTERION_PRIME_PI_ENTRY`,
  plus `DEEPSEEK_API_KEY`). Unset, it fails closed at preflight with status 2;
  the passing run supplied all four.
- **Phase 3 completion is bounded to what was run.** It revalidates P7's
  installed route and Level-1 solving on `ls20-9607627b` at seed 0 with
  `deepseek-v4-flash`. It is not a full-game, multi-seed, or multi-game result,
  and `promotion` stays `unpromoted`. Full benchmarks remain separately
  authorized work.
- Revalidate P7 without a Prime checkout (Phase 3), then rebuild P1, P2, P4, P3,
  P5, and P6 on the shared native `asterion.prime` path (Phases 4-9).
- Keep every compound Asterion-native row missing until Phase 3.2+ evidence
  proves the exact mandatory scenarios.
- Prove pinned/next-build compatibility only with separate exact locks and
  reviewed difference records.
- Historical Prime source-lock results are archived evidence only. No Prime
  source lock may remain in an Asterion implementation or release path.
- Keep any real ARC-AGI-3 full-suite or multi-game reproduction behind an exact
  finite operator authorization; production promotion remains separate.

## Key Files

### Loaded every session

- `AGENTS.md`
- `docs/status/INDEX.md`
- `docs/status/RESUME-NEXT-SESSION.md`
- `docs/status/JOURNAL.md`
- `docs/status/DECISIONS.md`
- `docs/status/climb/research-tree.md`

### Canonical program and evidence

- `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-system-parity.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-ecosystem-parity.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-client-interfaces-parity.md`
- `docs/superpowers/plans/2026-08-10-asterion-prime-operational-parity.md`
- `docs/superpowers/specs/2026-08-28-asterion-prime-client-interfaces-design.md`
- `docs/superpowers/specs/2026-08-30-prime-operation-host-callback-design.md`
- `docs/superpowers/plans/2026-08-30-prime-operation-host-callback.md`
- `docs/superpowers/specs/2026-08-30-asterion-native-controller-core-design.md`
- `docs/superpowers/plans/2026-08-30-asterion-native-controller-core.md`
- `docs/superpowers/plans/2026-09-02-prime-smoke-core.md`
- `docs/superpowers/specs/2026-09-02-prime-smoke-core-full-research.md`
- `docs/superpowers/specs/2026-09-02-asterion-prime-capability-program-design.md`
- `docs/superpowers/specs/2026-09-03-prime-ipython-workload-result-design.md`
- `docs/status/PRIME-PARITY-LEDGER.md`
- `docs/status/PRIME-TYPICAL-APPLICATIONS.md`
- `docs/status/ASTERION-PRIME-P7-EVIDENCE.md`
- `docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`
- `.superpowers/sdd/client-interfaces-task-10-report.md`
- `.superpowers/sdd/operational-parity-task-16-report.md`
- `.superpowers/sdd/native-core-task-10-report.md`

### Implementation entry points

- `src/asterion/agents/prime/` — native Asterion Prime session, runtime, trace,
  and source-detachment boundary
- `src/asterion/applications/prime/` — native Asterion Prime application
  provider and P7 operator integration
- `tools/verify_native_controller_core.py` — exact provider-free Native
  controller-core receipt verifier
- `tools/verify_native_verified_loop.py` — exact provider-free/operator-bounded
  Native verified-loop verifier
- `tools/check_prime_parity.py` — neutral parity-ledger reducer; its Prime
  Gateway `--source-root`/`--provider asterion.prime-gateway` paths are removed
- `tools/check_promotion.py` — isolated source/wheel/promotion verification
  against the detached (native/DCI) distribution
- `tools/compare_prime_p7_runs.py` — neutral exported-log comparison; starts no
  process

## Resume Instructions

1. Read this snapshot, `RESUME-NEXT-SESSION.md`, and the generated Climb tree.
2. Inspect `git status --short` and recent commits before staging anything.
3. Preserve unrelated dirty work and use exact partial staging.
4. Select the next framework milestone from current integration needs. Treat
   W0-W5 and the seven Prime development scenarios as closed at their named
   boundaries. Native Phase 3.2 remains parallel; product promotion is separate.
5. Keep credentials, private configuration, and execution authority external.
6. Never promote provider-free or External-limited evidence to a broader PASS.
