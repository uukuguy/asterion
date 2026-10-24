# Next-Session Handoff

> Updated: 2026-10-24 13:04 end of session.

## TL;DR

- `make native-dci-example` completed. The captured public run is `native-dci-23b1b537ac504926bd2fb253e4c6d72b`, status `completed`, exit 0. Exit 0 is not a judged answer.
- `native.dci-complete` and the provider conversion are written specs. They are not built. No plan exists.
- Do not start a plan, an implementation, a dataset run, or another live retrieval from this handoff.

## Verified facts

- `main` matched `origin/main` at `18808a14` before this handoff commit. No `native-dci` process was running.
- Native entry and the retrieval example are on `main`: `2b77c81f`, `4d9bdf93`, `bd4d8db4`, `b8069cc3`, `929e83a3`. Door is `prepare_native_application`. Provider `native` keeps `native.packages@1.0.0` first, then `native.dci-research@1.0.0` and `native.controlled-code@1.0.0`.
- The live command is `make native-dci-example`. It runs `examples/applications/native_dci.py --live` with `python-dotenv`. The Pi command includes `--mode rpc` [`0a96a31e`]. The one-shot stdout line cap is 1MB and matches `PiRpcSession` [`18808a14`].
- Captured stdout in `/tmp/native-dci-example/run.log` is `{"application_id": "native.dci-research", "run_id": "native-dci-23b1b537ac504926bd2fb253e4c6d72b", "status": "completed"}`, exit 0. Evidence for that run ends at `run.completed`.
- A later evidence directory, 2026-10-22 23:22, run `native-dci-f4c9df9acea44c419e76c21a666f9532`, also ends at `run.completed`. Its tools are one `read` with `is_error` true and two `grep` results with `is_error` false. No stdout log was kept for that run.
- Specs are committed: complete example `0fca6e23` (amended by `396f0489` and `ee0e0ef3`) and provider conversion `ee0e0ef3`. `dci-agent-lite` is still the live product provider. `asterion-dci` still selects `dci.complete-application@1.0.0`.
- The peer-foundation worklist stays done. `P-PI-1`, `P-NATIVE-1`, and `P-CITE-1` are done. Decision D-2026-10-20-04. No package is pending.
- P1 facts from the previous handoff stay in force. `make asterion-prime-p1-run` exits 0 only when status is `completed`. Recorded samples: `oracle.pass` on `p1-f8f0aa6dfe5cb466d2c64e79`; `recovery-required` on `p1-e822af327220e58ba4c6c43d` and `p1-cf6c9ddd449a9710bd968e21`.

## Current judgment

- The retrieval preset is a runnable Native DCI example. A `completed` status means the chain returned. It does not certify the answer. This application has no Judge.
- The two 2026-10-22 specs are the review documents. They do not authorize code, a plan, or a model call.
- `dci-agent-lite` remains load-bearing until the conversion is implemented. It is the provider id, the entry-point name, the module path, and the Judge identity check.

## Historical archive

- Do not remove `--mode rpc`. Without it, Pi print mode waits for stdin EOF and the example waits for JSONL.
- Do not return the one-shot stdout line cap to 64KB. One default grep event is larger than that cap. The public failure was `status: failed`.
- Do not treat `dci-agent-lite` as unused code. Do not delete it outside the conversion spec.
- Do not reset `7fc5f39e`, `0a96a31e`, or `18808a14`. Those commits are already on `origin/main`.
- Do not rewrite the 2026-10-21 research spec or plan. The running command now adds `--mode rpc`. The plan text does not.
- An earlier `corpus is unavailable` result was a missing `wiki_dump.jsonl`. The dump is present. Do not create a substitute dump.
- Do not run `make native-dci-complete-example`. That target does not exist.
- The paper ablation row keeps runtime id `dci-agent-lite`. The conversion spec does not rename that row.
- Do not build a second P1–P7 on Native. Prime stays on `prepare_prime_application`.

## Open boundary

- `native.dci-complete@1.0.0`, its Claude assemblies, `native.dci-benchmark@1.0.0`, the operator-module move, the entry-point deletion, and the Judge-factory retarget are not implemented.
- No implementation plan exists. The user has not asked for one.
- `make dci-preflight` still fails on the package root. `asterion-dci run` without `--runtime` still exits 2. Both stay out of scope.
- The example hides the exception text. A failed run prints `status: failed` and `native-dci-example: run failed`.
- D-2026-07-31-02 remains active. A full dataset run still needs a finished executable 50-case, or smaller complete, closure first. Neither spec closes that decision.
- Known research-example minors stay unfixed: host-key operator precedence, the duplicate import, temporary-directory leaks, and the Makefile assertion that does not require one recipe.
- Guest `ubuntu-fusion-control` was running at the 2026-10-21 handoff. This session did not recheck it. Do not stop it from this baton.
- Worktrees `asterion-p1-workload`, `asterion-p2-worker`, and `asterion-p3-real-rlm` remain. They are unrelated.
- This handoff commit stays local until a separate push decision.

## Next action

1. Read this handoff. Do not write a plan. Do not implement either spec. Do not start a dataset run or another live retrieval.
2. If the user asks for a review, read `docs/superpowers/specs/2026-10-22-native-dci-complete-example-design.md` and `docs/superpowers/specs/2026-10-22-native-dci-provider-conversion-design.md`.
3. If the user asks to rerun the shipped example, use the command below. Exit 0 means status `completed`. It does not mean the answer is correct. The command prints nothing until the model call returns.

## Ready-to-paste command

```bash
make native-dci-example
```
