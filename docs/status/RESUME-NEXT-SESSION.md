# Live Session Checkpoint

> Updated: 2026-09-16 12:30. **Session remains active — not a final handoff.**
> Supersedes the 2026-09-15 05:40 handoff for Phase 4 state; Phase 1–3 records
> in that handoff remain accurate.

## TL;DR

1. **Phase 4's launch path is built and verified** (gate 0, P1 targeted set 83
   pass / 0 skip). P1 no longer resolves itself out of the published provider,
   so it composes while still unpublished.
2. **The live witness run FAILED**, and the failure is fully located: the
   context witness required compaction functions that only exist in Prime
   Agent's own Pi build. This is plan risk 1 surfacing, exactly as predicted.
3. **The fix is in flight.** An implementation subagent (`p1-compaction-native`)
   is giving Asterion prime its own summarization construction and supplying it
   over the witness protocol, replacing the Prime-coupled injection.

## 已验证事实

- **P1 launch path rebuilt** in `src/asterion/applications/prime/p1/operator.py`:
  `_Preflight`, `_preflight`, `_build_resources`, and `main`'s invoke body. All
  values Asterion-owned: Pi from the operator-owned `ASTERION_PRIME_PI_ENTRY`
  (P7 shape, D-2026-09-14-03), extension from the packaged
  `resources/ipython-extension.mjs` (generated at build time by `hatch_build.py`
  into a staging dir — never written to the source tree), compaction from
  Asterion's `PrimeContextWitnessSession`.
- **Makefile `asterion-prime-p1-run` now exports `ASTERION_PRIME_PI_ENTRY`**; it
  was missing, so preflight could never have passed.
- **The provider coupling is removed.** `provider.py` gained
  `prime_ipython_coding_application()` and `create_prime_ipython_coding_provider()`;
  P1's operator composes from its own record. The public list is unchanged (P7
  only) — P1 is still unpublished. This is why the 34 test skips dropped to 0.
- **P1 targeted set: 83 pass, 0 skip** (was 38 pass / 34 skip). P7 set: 24 pass,
  unaffected. Lint: same 4 pre-existing errors, none in changed files.
- **Live run `p1-debe34e5b246017abaae2e27` FAILED** with `status=recovery-required`
  ~30-60s in, at the first model turn after `stage1.setup.start`.
- **Root cause, traced link by link:** the Pi child refused to load the
  extension (`Asterion pinned Pi extension is invalid`), because the extension's
  `register()` called `registerContextWitnessFromEnvironment` with
  `deps === undefined`, and `new ContextWitness(undefined, ...)` fails its
  `dependencies()` validator. The loader's catch-all masked the real error.
  P7 passes the same chain only because its binding carries no context fd, so
  the witness branch returns early.
- **The missing three names are Prime Agent's own.** `npm view` shows upstream
  `@earendil-works/pi-coding-agent` has **no 0.7.x release at all** (earliest is
  0.74.0), while `prime-artifact-lock.json` records `package_version: "0.7.1"`
  with `source_commit a18809e0`. The locked tree was therefore Prime Agent's own
  modified Pi build. The deleted `PiExtensionDependencies` seam was a disguised
  runtime import of it.
- **Nothing uses the injection mechanism any more.** `ExtensionBinding(dependencies=...)`
  has no caller anywhere in `src/`; `ExtensionDependencies` is referenced only by
  its own module, a re-export, and its tests. It is removable Prime-era scaffolding.
- **The protocol already carries the summary requests.** `_validate_proposal`
  validates `main_summary_request` / `turn_prefix_summary_request` as canonical
  Asterion-encoded bodies bounded to 4096 units. Asterion owns the shape; only
  the prompt text was Prime's.

## 当前判断

- **The remaining Phase 4 work is small and well-scoped**: Asterion owns the
  summarization text (native constants), the extension gets it over the
  protocol, and the extension adapts to upstream Pi 0.85.1's actual API.
- **Upstream Pi 0.85.1 does export** `prepareCompaction`
  (`dist/core/compaction/compaction.js`), `serializeConversation`
  (`dist/core/compaction/utils.js`), `buildSessionContext`
  (`dist/core/session-manager.js`), `convertToLlm` (`dist/core/messages.js`) —
  and it has its own summarization machinery in
  `dist/core/compaction/branch-summarization.js` under different names.
- **The extracted principle** (for the implementation): a summarization system
  prompt; initial and update user templates sharing one fixed section format
  (Goal / Constraints & Preferences / Progress{Done, In Progress, Blocked} /
  Key Decisions / Next Steps / Critical Context) with "preserve exact file
  paths, function names, and error messages"; a kernel-persistence note that is
  the reason P1 exists; a turn-prefix template; assembly as
  `<conversation>…</conversation>` + optional `<previous-summary>` + template;
  `maxTokens = floor(0.8 * reserveTokens)`. Cross-check: `0.8 * 4096 = 3276`,
  matching the fixture's `output_cap`.

## 未完成边界

- **Phases 4-9 unstarted. P1-P6 have no native implementation reachable.
  P1-P7 native implementations: 1 of 7** — P7 only.
- **The P1 witness has NOT passed.** P1 stays unpublished. Do not publish it
  without the witness.
- **No commit yet for this session's work.** 6 files are modified in the working
  tree (`Makefile`, `docs/status/JOURNAL.md`,
  `src/asterion/applications/prime/__init__.py`,
  `src/asterion/applications/prime/p1/operator.py`,
  `src/asterion/applications/prime/provider.py`,
  `tests/test_asterion_prime_p1_operator.py`).
- **The in-flight subagent's result is unreviewed.** Review it before treating
  any of it as verified.
- `.asterion-private/p1-diagnose.py` is a temporary diagnostic probe (gitignored).
  Remove it when the diagnosis is no longer needed.

## 下一动作

1. Review the `p1-compaction-native` subagent's work when it reports.
2. Then re-run the witness:
   `make asterion-prime-p1-run ASTERION_PRIME_PI_ENTRY=/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js`
3. Then, and only if it passes, publish P1 and remove the unpublished-state
   assertions in `tests/test_asterion_prime_p1_installed.py`.

## Workspace boundary

- **Asterion prime must never import or depend on Prime Agent.** Reading
  `3th-party/prime-agent.git` read-only to extract a design principle is the
  authorised exception (given 2026-09-16); every shipped line must be Asterion's
  own. The detachment gate must stay 0.
- Do not restore Prime launch, Prime locks, or Prime compaction imports.
- On the DeepSeek backend, pass no `model` to any subagent (see AGENTS.md).
- **Run `date` — never estimate a timestamp.**
- **Search `PATH` and the real environment before concluding a resource is absent.**
- **Research intensity:** review changed code plus boundary assertions, run small
  targeted regressions. Do not re-run full suites or harden tooling.
