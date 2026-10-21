# Next-Session Handoff

> Updated: 2026-10-21 21:11 end of session.

## TL;DR

- The peer-foundation worklist is complete. `P-PI-1`, `P-NATIVE-1`, and `P-CITE-1` are done. Decision D-2026-10-20-04. No package is pending.
- `make asterion-prime-p1-run PRIME_ORB_MACHINE=ubuntu-fusion-control` exits 0 only when the public status is `completed`. One recorded run passed. Two recorded runs returned `recovery-required`.
- Do not start a new package or a paid run from this handoff.

## Verified facts

- Code `e131e5a0` and docs `6463cc50`: the six `prime-*-native` packages record media type, digest, and run identity. `prepare_prime_application` stays the Prime door. Operators P1 through P6 read that digest from the Prime runtime they already build.
- `tests.test_prime_native_citation` passed. The focused operator, live, runtime, and composed suite ran 195 tests. One failure remains: `test_real_candidate_workflow_oracle_and_rollback_control_result` outcome `regressed` sees `run.completed` where the test expects `run.failed`. That assertion was not changed by P-CITE-1.
- `ruff check` passed on the citation slice. `uv run python tools/check_docs.py` checked 332 markdown files. `make promotion-check` was not run.
- P1 preset `p1-e822af327220e58ba4c6c43d` stopped at `stage1.oracle.start`. Status `recovery-required`. Receipt null.
- P1 preset `p1-f8f0aa6dfe5cb466d2c64e79` printed `oracle.pass`. Status `completed`. Receipt `0c02c5ed03f898758a56fd10c8a0bd7ee31c8ccd8efd7d9d971d5632668fc137`. Summary `e7fb9c3c83f6e95401b59874a6556cf02f63a850d369ea81b7c8f155c8201841`.
- P1 preset `p1-cf6c9ddd449a9710bd968e21` reached `stage2.complete`, printed `oracle.reject.snapshot`, and returned `recovery-required`. Receipt null. The summary hash matches the passing run.
- No preset process remains. Guest `ubuntu-fusion-control` is running.

## Current judgment

- A `recovery-required` result after the wheel installs and stages advance is an oracle rejection of that model sample. It is not an install or machine-selection failure.
- `oracle.reject.snapshot` means the stage-two worker snapshot failed the fixed three-cell check. The public line does not name which cell condition failed.
- Two `oracle.pass` receipts do not establish a stability rate.

## Historical archive

- Do not add a flag or environment value that forces this preset to exit 0.
- Do not treat the peer-foundation commits as authorization for another model run, benchmark, official card, L9 rerun, or `make promotion-check`.

## Open boundary

- The peer-foundation worklist has no pending package. A new package needs a separate decision.
- `tests.test_core_only_install` still reports `asterion.agents.prime.code_summary` missing from `CORE_MODULES`. That gap predates P-CITE-1.
- The P6 composed `regressed` subtest still expects `run.failed` and observes `run.completed`. It predates P-CITE-1.
- This handoff commit stays local until a separate push decision.

## Next action

1. Read this handoff. Do not start a package or a paid run.
2. If the user asks for another completed P1 sample, rerun the command below. Exit 0 only when the JSON status is `completed`.

## Ready-to-paste command

```bash
make asterion-prime-p1-run PRIME_ORB_MACHINE=ubuntu-fusion-control
```
