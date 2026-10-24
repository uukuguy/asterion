# Live Session Checkpoint

> Updated: 2026-10-24 19:51. **Session remains active — not a final handoff.**

## TL;DR

- Installed provider `dci-agent-lite` is gone. Command `asterion-dci` describes and verifies the DCI product directly. `list` and `run` on that command fail closed.
- The string `dci-agent-lite` remains the Judge factory key, the unregistered operator composition id, and the paper ablation row. `native.dci-complete` is not built.
- Document tools stay opt-in. The PDF reader was not extended. No model call ran.

## Verified facts

- Entry point `dci-agent-lite` and the three `dci.*__1.0.0` application index rows are removed. Installed providers are `controlled-code`, `native`, and `prime-applications`.
- `operator_provider()` in `src/asterion/applications/dci/acceptance.py` still uses `provider_id="dci-agent-lite"`. It is not exported and not an entry point. `load_application_provider("dci-agent-lite")` fails.
- Acceptance counts one installed provider, `controlled-code`. The in-memory operator object keeps the DCI assembly closure: 7 bound, 8 packaged, 1 unbound local-research file. Capability manifests are 12, including `policy.context-management`.
- `uv run python -m unittest tests.test_asterion_cli tests.test_asterion_dci_verification tests.test_dci_application_adapter` passed: 84 tests. An earlier focused set of discovery, promotion, package ownership, research, and capability execution tests passed aside from the acceptance count, which was then aligned to 12.
- Ruff check passed on the edited Python. No model call. `make promotion-check` was not run. `make native-dci-example` was not run.

## Current judgment

- Removing the installed provider does not finish the provider-conversion spec. `native.dci-complete` and `native.dci-benchmark` are still absent.
- CLI research fixtures now emit a location and a trajectory because the shipped local-research contract rejects an answer-only stream. That is test alignment with the existing contract.

## Historical archive

- Do not remove `--mode rpc`. Do not return the one-shot stdout line cap to 64KB.
- Do not rewrite the paper ablation row name `dci-agent-lite`.
- Do not retarget the Judge factory until `native.dci-complete` exists.
- Do not move `level0`–`level4`, the ablation matrix, judges, or dataset targets onto the public runtime.
- D-2026-07-31-02 remains active. A full dataset run still needs its own authorization.

## Open boundary

- CID-font PDFs, scanned pages, text boxes, and headers are not citation anchors yet.
- The grid demo is not registered on provider `native` and does not satisfy the shipped preset's missing `shell` advertisement.
- Claude's static manifest still advertises `shell` when the launched tools are Read, Grep, and Glob.
- `make promotion-check` has not been run since `context-policy-extension.mjs` was added.
- Worktrees `asterion-p1-workload`, `asterion-p2-worker`, and `asterion-p3-real-rlm` remain. They are unrelated.
- Untracked regulation files under `docs/` stay untracked.

## Next action

1. Keep document tools opt-in. Extend the PDF reader only when a real regulation file is in scope.
2. Do not build `native.dci-complete` unless the user asks. Do not reinstall provider `dci-agent-lite`.
3. Do not run `make native-dci-example` or any dataset or model call.

## Ready-to-paste command

```bash
uv run python -m unittest tests.test_dci_application_adapter tests.test_asterion_dci_verification
```
