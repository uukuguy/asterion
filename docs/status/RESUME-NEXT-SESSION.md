# Live Session Checkpoint

> Updated: 2026-10-24 22:51. **Session remains active — not a final handoff.**

## TL;DR

- The grid regulation desk is one HTML file, `page.html`, served on `127.0.0.1`. It cites a dotted clause and shows the span text to the operator.
- A private probe cited one clause in each of the three untracked DOCX files and three PDFs. The originals stay untracked. No model call ran.
- `native.dci-complete` is not built. Installed provider `dci-agent-lite` stays removed.

## Verified facts

- `tests.test_grid_regulation_page` and `tests.test_grid_regulation` passed: 6 tests. Ruff check passed on the edited Python.
- Headless Chrome opened the desk, submitted one fictional query, and the result contained the marked span. Desktop and a 390px layout were reviewed.
- The fictional demo still cites one `grounding.docx` anchor for `4.1.2` and one `patrol.pdf` anchor for `5.2`.
- A split synthetic clause cites the cover, the heading, and the two spans that join the finding. A child span is cited only when the finding is in that child. A repeated clause id does not keep the earlier section.
- Local probe, text not recorded: each of the six regulation PDF and DOCX files returned 3 or 5 anchors for one dotted clause. The finding span was among them. `.doc` and the dsl file were not read.
- `make promotion-check` was not run. `make native-dci-example` was not run.

## Current judgment

- Citation checks that the version string occurs in the file and that the finding occurs inside the assembled clause. It does not decide legal applicability.
- The 36-point gap remains a reader constant, not a layout proof.

## Historical archive

- Do not remove `--mode rpc`. Do not return the one-shot stdout line cap to 64KB.
- Do not rewrite the paper ablation row name `dci-agent-lite`.
- Do not retarget the Judge factory until `native.dci-complete` exists.
- Do not move `level0`–`level4`, the ablation matrix, judges, or dataset targets onto the public runtime.
- D-2026-07-31-02 remains active. A full dataset run still needs its own authorization.
- The same-span citation rule is retired. A clause id, its version, and its finding may sit on different spans.

## Open boundary

- Scanned pages, CID fonts without a ToUnicode map, OLE `.doc`, and `docs/guodiao_2023_2.0_1.0-utf8.dsl` are not citation anchors.
- The grid application is not registered on provider `native`. The JSON example still uses the fictional corpus. The desk shows span text only to the local operator.
- The shipped retrieval preset still launches `read,grep` and does not advertise `shell`.
- `make promotion-check` has not been run since `context-policy-extension.mjs` was added.
- Worktrees `asterion-p1-workload`, `asterion-p2-worker`, and `asterion-p3-real-rlm` remain. They are unrelated.
- Untracked regulation files under `docs/` stay untracked.

## Next action

1. Do not build `native.dci-complete` unless the user asks. Do not reinstall provider `dci-agent-lite`.
2. Do not run `make native-dci-example` or any dataset or model call.
3. Do not commit the regulation originals. Open the desk with `--corpus` pointed at their directory. A citation still needs a clause, a version string, and a finding.

## Ready-to-paste command

```bash
uv run python -m unittest tests.test_grid_regulation_page tests.test_grid_regulation
```
