# Live Session Checkpoint

> Updated: 2026-10-24 21:12. **Session remains active — not a final handoff.**

## TL;DR

- Installed provider `dci-agent-lite` is gone (`34027537`). `asterion-dci` describes and verifies the product. `native.dci-complete` is not built.
- The PDF reader decodes Identity-H ToUnicode maps and cites one baseline as one span. A DOCX paragraph with inactive numbering stays readable.
- The untracked regulation PDFs and DOCX files now yield CJK spans. OLE `.doc`, the dsl file, and scanned pages stay unread. No model call ran.

## Verified facts

- `tests.test_document_tools` and `tests.test_grid_regulation` passed: 6 tests. Ruff check passed on the edited Python.
- A synthetic Identity-H file cites `条款甲` as one span, keeps a distant glyph apart, and reads both a scalar and an array `bfrange`.
- A DOCX `numId` of 0, and a `numPr` with only `ilvl`, keep the paragraph text and omit numbering fields.
- Local probe, text not recorded: three DOCX files and three PDFs produce CJK spans. Body lines of about 30 characters are present. Median lines are shorter because of labels and cells.
- `make promotion-check` was not run. `make native-dci-example` was not run.

## Current judgment

- Baseline spans can cite a phrase that sits on one line. A sentence that wraps, or a clause id and a finding on different lines, is more than one span.
- The 36-point gap splits the sampled column gaps. It is a reader constant, not a layout proof.

## Historical archive

- Do not remove `--mode rpc`. Do not return the one-shot stdout line cap to 64KB.
- Do not rewrite the paper ablation row name `dci-agent-lite`.
- Do not retarget the Judge factory until `native.dci-complete` exists.
- Do not move `level0`–`level4`, the ablation matrix, judges, or dataset targets onto the public runtime.
- D-2026-07-31-02 remains active. A full dataset run still needs its own authorization.

## Open boundary

- Scanned pages, CID fonts without a ToUnicode map, OLE `.doc`, and `docs/guodiao_2023_2.0_1.0-utf8.dsl` are not citation anchors.
- The grid demo is still the fictional corpus. It is not registered on provider `native`.
- The shipped retrieval preset still launches `read,grep` and does not advertise `shell`.
- `make promotion-check` has not been run since `context-policy-extension.mjs` was added.
- Worktrees `asterion-p1-workload`, `asterion-p2-worker`, and `asterion-p3-real-rlm` remain. They are unrelated.
- Untracked regulation files under `docs/` stay untracked.

## Next action

1. Do not build `native.dci-complete` unless the user asks. Do not reinstall provider `dci-agent-lite`.
2. Do not run `make native-dci-example` or any dataset or model call.
3. A citation over a real regulation file needs an explicit file and clause. Do not commit those files.

## Ready-to-paste command

```bash
uv run python -m unittest tests.test_document_tools tests.test_grid_regulation
```
