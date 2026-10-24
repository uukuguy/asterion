# Live Session Checkpoint

> Updated: 2026-10-24 16:07. **Session remains active — not a final handoff.**

## TL;DR

- Local research now emits answer, locations, and trajectory from the launched tool stream. A stream with no tool calls still accepts pre-labeled artifacts. No model was called.
- Comparison evaluation is not selected by `native.dci-research@1.0.0`. A missing Judge does not block that retrieval.
- `dci-agent-lite` is still the in-repo product provider. Do not delete it in the same change as the artifact work. Do not run `make native-dci-example`.

## Verified facts

- `main` is local at `e8fa440b` (`Give pi.reference an application context policy.`), parent `39c1d85c`. It is not pushed. No `native-dci` process was started for this change.
- `DciLocalResearchImplementation` pairs each `tool.call` with one `tool.result`. Trajectory records every completed tool name, including an errored result. Locations come from `read` and `grep` argument keys `path`, `file_path`, or `file`, in that order. A pathless `grep` records `.`. `bash` does not contribute a path. Absolute paths and `..` fail closed. Tool output is not copied into the artifacts. Tool calls replace pre-labeled location and trajectory artifacts. The answer still comes from the answer artifact.
- `uv run python -m unittest tests.test_context_policy tests.test_dci_research_capability tests.test_native_application tests.test_default_runtime_factory` passed: 52 tests. Ruff check and format passed on the two edited Python files.
- `native.dci-research@1.0.0` selects `dci.research`, `policy.context-management`, and `policy.local-corpus`. It does not select `dci.evaluation`.
- The complete research implementation and `project_dci_run` still emit only the answer artifact. That was not changed.
- The shipped example still launches `read,grep` and no context policy. `tests/test_native_application.py` still forbids `bash` in that preset.
- Earlier captures stay historical: `native-dci-23b1b537ac504926bd2fb253e4c6d72b` and `native-dci-f4c9df9acea44c419e76c21a666f9532`. Exit 0 is the chain return, not a judged answer.
- `pi.reference` still launches any non-empty canonical subset of `read`, `grep`, and `bash`. `context_policy` is optional numeric bounds. `level0`–`level4` stay in the comparison package.

## Current judgment

- Provider-free tests show one local retrieval can emit the three core artifacts from a Pi-shaped tool stream. They do not show a live Pi session, a judged answer, or a dataset result.
- Removing `dci-agent-lite` is the next product change. It is separate from this evidence change. `native.dci-complete@1.0.0` is still not built, so the removal has to keep command `asterion-dci` working without inventing a comparison application or a grid-regulation application.

## Historical archive

- Do not remove `--mode rpc`. Do not return the one-shot stdout line cap to 64KB.
- Do not reset `7fc5f39e`, `0a96a31e`, or `18808a14`.
- Do not rewrite the paper ablation row name `dci-agent-lite`.
- Do not build a paper replica, a grid-regulation application, or a second retrieval package.
- Do not move `level0`–`level4`, the ablation matrix, judges, or dataset targets onto the public runtime.
- Do not treat the 2026-10-22 conversion specs as the done-definition. They are narrower than this package contract.
- D-2026-07-31-02 remains active. A full dataset run still needs its own authorization.

## Open boundary

- The shipped example does not advertise `shell` until its tool list includes `bash`. Changing the preset is not a license to call the model.
- Claude's static manifest still advertises `shell` when the launched tools are Read, Grep, and Glob.
- The context extension's compaction and summary hooks have not run against a live Pi process. `make promotion-check` has not been run since `context-policy-extension.mjs` was added.
- `native.dci-complete@1.0.0`, its Claude assemblies, `native.dci-benchmark@1.0.0`, the operator-module move, the entry-point deletion, and the Judge-factory retarget are not implemented.
- `make dci-preflight` still fails on the package root. `asterion-dci run` without `--runtime` still exits 2. Both stay out of scope.
- Worktrees `asterion-p1-workload`, `asterion-p2-worker`, and `asterion-p3-real-rlm` remain. They are unrelated.
- This checkpoint stays local until a separate push decision.

## Next action

1. Remove provider `dci-agent-lite`, module `asterion.applications.dci_agent_lite`, and its entry point as its own change. Keep command `asterion-dci`. Leave the paper ablation row name unchanged. Do not build `native.dci-complete` or the grid-regulation application in that deletion.
2. Do not run `make native-dci-example` or any dataset or model call. Do not move `level0`–`level4` onto the public runtime.

## Ready-to-paste command

```bash
uv run python -m unittest tests.test_dci_research_capability tests.test_native_application tests.test_native_package_host
```
