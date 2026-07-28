# Next-Session Handoff

> Updated: 2026-07-28 end of session.

## TL;DR

- `feature/capability-package-architecture` branch worktree is clean.
- Plans 1–3 are implemented and verified.
- Plan 3 closed the generic benchmark subsystem; no provider, Agent/Judge, or
  full-dataset benchmark execution occurred.
- The next action is Plan 4 / Task 1: establish the complete portable DCI
  capability-package payload.
- `docs/status/CURRENT-STATE.md` remains the pre-Plan 1 snapshot. Do not use it
  as the current progress record.

## Where things stand

Plan 3 completion checkpoint:

`175fad9 docs: checkpoint completed benchmark subsystem`

Completed:

1. Plan 1: Asterion capability protocol foundation.
2. Plan 2: source-neutral package sources, SDK, CLI, and promotion boundary.
3. Plan 3: domain-neutral generic benchmark subsystem.

Plan 3 now provides:

- immutable, redacted benchmark values;
- metadata-only suite resolution;
- exact package, task, and source-lock bindings;
- deterministic bounded planning;
- descriptor-bound private evidence;
- a sequential fail/cancel-stop runner;
- authorized direct process execution and process-group cancellation;
- `asterion benchmark plan`;
- `asterion benchmark run ... --execute`;
- `asterion benchmark resume ... --execute`;
- provider-free and evidence-free planning;
- explicit execution authorization before provider loading;
- no DCI datasets, corpora, launchers, prompts, providers, or amount fields in
  the generic layer.

Amount remains omitted by default.

## What this session delivered

Final verification:

- Plan 3 focused tests: 62/62 PASS.
- Full Python suite: 709/709 PASS.
- `make lint`: PASS.
- `make docs-check`: PASS.
- `make check`: PASS.
- TypeScript runtime: 20 tests PASS.
- TypeScript extension: 16 tests PASS.
- Rust tests, fmt, and clippy: PASS.
- sdist and wheel builds: PASS.
- `make promotion-check`:
  `promotion full PASS commands=24 provider_operations=0 full_dataset=no`.
- Pyright: `0 errors, 0 warnings, 0 informations`.
- Independent final review: APPROVE, with no Critical, High, or Medium
  findings and one Low finding.

End-of-phase fixes:

- eliminated the PID readiness race in the process-tree cancellation test;
- fixed nine benchmark Pyright diagnostics without ignores or broad casts;
- required an exact and complete installed-package closure for benchmark plans;
- completed AST, package, wheel, and distribution boundary tests.

## Next steps (immediate, action-level)

1. Open
   `docs/superpowers/plans/2026-07-27-dci-capability-package-migration.md`.
2. Execute Plan 4 / Task 1: establish the complete portable DCI payload.
3. First write and run the failing payload contract test:
   `uv run python -m unittest -v tests.test_dci_capability_payload`.
4. Create:
   - `src/asterion/capabilities/dci/capability-package.json`;
   - `src/asterion/capabilities/dci/capabilities/`;
   - `src/asterion/capabilities/dci/benchmark-suites/github.json`;
   - `src/asterion/capabilities/dci/benchmark-suites/paper-main.json`;
   - `src/asterion/capabilities/dci/benchmark-suites/all.json`;
   - `src/asterion/capabilities/dci/__init__.py`.
5. Move the old `dci_research/manifests` into DCI package-owned artifacts.
6. Keep the suite task identities equal to the planned 12/13/15 task sets.
7. Keep portable manifests free of launchers, `.env` keys, dataset paths,
   prompts, providers, private paths, and amount values.
8. After Task 1 passes, commit:
   `feat: define portable DCI capability payload`.
9. Update the stale `docs/status/CURRENT-STATE.md` after Plan 4 establishes the
   new structural snapshot.
10. Do not run provider-backed or full benchmarks without separate explicit
    authorization.

## Don't go down these paths again (ruled out)

- Do not move DCI benchmark orchestration back into the generic Asterion layer.
- Do not give built-in packages privileged loading or composition paths;
  built-in is only one source form.
- Do not put commands, executable paths, credentials, environment values,
  provider configuration, or mutable state in manifests.
- Do not add version ranges, registries, directory scanning, hidden precedence,
  or symlink traversal.
- Do not infer execution authority from `.env`, caches, existing evidence, or
  already-downloaded data.
- Do not promote bounded evidence to paper/full reproduction PASS.
- Do not revisit runtime cancellation as the cause of the former process-tree
  test failure. The test exposed its PID file before content was complete; the
  fixture now uses a pending file and atomic replacement.
- Do not bypass final review with Pyright ignores, broad casts, or an incomplete
  installed-package closure.

## Ready-to-paste commands / configs

```bash
cd .worktrees/capability-package-architecture

git status --short
git log --oneline -5

sed -n '1,220p' \
  docs/superpowers/plans/2026-07-27-dci-capability-package-migration.md

uv run python -m unittest -v tests.test_dci_capability_payload
```

Phase completion gates:

```bash
make test
make lint
make docs-check
make check
make promotion-check
uv run pyright src/asterion/benchmarks src/asterion/cli.py
```

## Carried review findings

- Low: direct use of `AuthorizedProcessTaskExecutor` can expose a raw
  progress-callback exception to its caller. The supported `BenchmarkRunner`
  path already redacts it. Revisit during final branch review.
- Low: the protocol ownership scanner broadly excludes `.superpowers/sdd`.
  Narrow the rule or prove tracked protocol files cannot be hidden there
  during final branch review.
