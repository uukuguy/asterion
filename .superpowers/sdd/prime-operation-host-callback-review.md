# Prime Operation Host Callback — Task 6 Review

Date: 2026-08-30

Reviewed range: design and implementation through `2d486f6`

Verdict: **APPROVE**

## Scope

The review covered the operator-owned Python operation dispatcher, the private
Python callback server, TypeScript callback client and production assembly,
managed sidecar lifecycle, root/child/grandchild composition, uncertain
reconciliation and cancellation, real-process coverage, identity locks, and
distribution behavior.

The review explicitly checked dependency direction, exact dispatcher identity,
callback framing and EOF, absolute deadlines, token and socket safety, startup
and close races, single-call/no-retry behavior, deterministic fail-closed
validation, redaction, evidence inflation, and the boundary between verified
system parity and still-missing native parity.

## Independent review and fix loop

The first cross-cutting review examined 26 changed files and requested changes
for one HIGH lifecycle issue and one LOW typing issue:

1. A first sidecar request could acquire a PID and then fail before the managed
   startup path completed, leaving the callback live until a later explicit
   close.
2. `ControlHost` nominally accepted `OperationManager` even though child
   composition intentionally supplies the narrower structural
   `OperationDispatcher` boundary.

The lifecycle issue received a RED reproduction:

```text
callback.start -> process.request
```

The focused fix in `2d486f6` closes the first failed transport through the
normal idempotent process-then-callback path. The same reproduction is now:

```text
callback.start -> process.request -> process.close -> callback.close
```

A second request does not reach the process. Calls that observed an existing
PID before delegation retain the established-process lifecycle behavior. The
typing fix changes `ControlHost` to accept `OperationDispatcher | None` and
removes the child-side nominal cast.

The original reviewer independently re-reviewed the five modified files,
reran the minimal reproducer and focused checks, reported zero remaining
findings, and changed the verdict to APPROVE. No CRITICAL, HIGH, MEDIUM, LOW,
or unclassified uncertainty remains open.

## Final verification evidence

All commands below were rerun after `2d486f6`:

- `npm --prefix packages/typescript/prime-gateway run build` — PASS.
- `npm --prefix packages/typescript/prime-gateway test` — 340/340 PASS.
- Task 6 focused Python operation matrix — 142/142 PASS with
  `ResourceWarning` promoted to error.
- Prime ledger/checker/Climb matrix — 35/35 PASS.
- `tools/check_prime_parity.py --claim verified-system-parity --provider
  asterion.prime-gateway` — PASS with 61 passed, 0 blocking, 2 excluded,
  0 provider operations, and 0 application operations.
- `make test` — 2335/2335 PASS.
- `make lint` — PASS.
- `make docs-check` — 113 Markdown files and 57 local links checked.
- `make check` — PASS, including 2335 Python tests, TypeScript, Rust tests,
  `cargo fmt`, `cargo clippy -D warnings`, lint, docs, and package build.
- `make promotion-check` — `promotion full PASS commands=28
  provider_operations=0 full_dataset=no`.
- `uv build .` — source distribution and wheel built successfully.
- `git diff --check` — PASS.

Focused review checks also passed ruff and pyright with zero errors, warnings,
or information messages.

## Boundary conclusion

The Prime operation callback production path is implemented and verified at
the system-parity boundary. The review does not promote any native continual
harness or native ecosystem row, does not claim Phase 3 or Phase 4 completion,
and does not authorize provider, application, model, network, or full-dataset
work. Task 6 is complete and H-037 may be created and executed exactly once.
