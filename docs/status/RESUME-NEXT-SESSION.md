# Live Session Checkpoint

> Updated: 2026-10-25 23:47. **Session remains active — not a final handoff.**

## TL;DR

- The grid regulation desk is one HTML file, `page.html`. POST `/api/measures` calls `answer_fault`. `page.main` passes `LiveGridResearch`. `serve` with no research object still returns 422 and does not start Pi. `make grid-regulation` stays on `127.0.0.1`. It was not run. Submitting the form would start Pi.
- A private probe cited one clause in each of the three untracked DOCX files and three PDFs. The originals stay untracked. No model call ran.
- `native.dci-complete` is not built. Installed provider `dci-agent-lite` stays removed.

## Verified facts

- `tests.test_document_tools`, `tests.test_dci_research_capability`, `tests.test_grid_regulation`, `tests.test_grid_regulation_page`, and `tests.test_native_application` passed: 57 tests. Ruff check passed on the edited Python. Commit `98dfed8a` is local and not pushed. The same five modules passed at 52 tests for `3a41d145`. Headless Chrome opened the empty page, one scripted hit, and a miss. The server used a temporary fictional file, not `docs/`. No model call.
- The removed word chain opened a paragraph or a whole table row that contained the situation words, then one passage whose label was a clause number written in that row. On the 2023 stability file, one spaced fault query opened two unlabeled paragraphs of 78 characters each. `主变 冷却` and `冷却 全停` missed that chain because those characters do not occur in one passage. That chain is not the page.
- A span that is only a clause number does not start a clause. A titled cell still does. On the 2023 stability file the one bare cell stays inside clause 28.1.1 (1753 characters). Clause 5.8 is not opened. The older clause assembler for that spaced fault query is unchanged: 6.2.5 (546 characters) and 26.1 (1427 characters). The page does not return those clauses.
- DOCX reader: when nonempty TOC1–TOC3 levels equal heading styles 1–3, the clause number is prefixed to the heading and the TOC paragraphs are omitted. Paragraph indexes of the remaining paragraphs stay the original indexes. Public position keys are unchanged. A mismatch does not rewrite the file.
- Private re-probe of the 2023 stability DOCX, sentence text not recorded: 8539 nonempty spans. Clause 1.17 is 30 characters. The older clause assembler returned 6.2.5 (546 characters) and 26.1 (1427 characters) and was not limited. `主变 冷却`, `冷却 全停`, and the unspaced form missed. Parent sections 4.2 and 2.4 remain 10697 and 9298 characters because they still include descendants. That assembler is not the page reply.
- Headless Chrome opened the empty desk, one fictional measures hit, and a miss. A 390px layout was reviewed.
- The fictional demo still cites one `grounding.docx` anchor for `4.1.2` and one `patrol.pdf` anchor for `5.2`.
- A split synthetic clause cites the cover, the heading, and the two spans that join the finding. A child span is cited only when the finding is in that child. A repeated clause id does not keep the earlier section.
- Local probe, text not recorded: each of the six regulation PDF and DOCX files returned 3 or 5 anchors for one dotted clause. The finding span was among them. `.doc` and the dsl file were not read.
- `make promotion-check` was not run. `make native-dci-example` was not run.

## Current judgment

- Citation checks that the version string occurs in the file and that the finding occurs inside the assembled clause. It does not decide legal applicability.
- A model-written grid answer uses native-dci through `prepare_native_application` inside `LiveGridResearch.run`. Tests do not call `run`. `serve` with no research object does not start Pi. `page.main` would start Pi when the form is submitted. That run is not authorized. The desk does not open another model client. `prepare_prime_application` stays the Prime door.
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
2. Do not run `make native-dci-example`, `make grid-regulation`, or any dataset. Do not start Pi. The live option builder exists: tools `read,bash`, `max_turns` `"32"`, a 300-second cancel, and canonical L2 JSON. Tests inspect those options and must not call `run` or `prepare_native_application`. Submitting the form through `make grid-regulation` would start Pi. That run is not authorized.
3. Do not commit the regulation originals. Desk bounds stay `max_turns` `"32"` and a 300-second cancel. Live evidence is `outputs/grid-regulation`, mode `0700`, retained for the operator, and kept off HTTP, logs, and git. A real run against a regulation file needs a separate authorization.

## Ready-to-paste command

```bash
uv run python -m unittest tests.test_document_tools tests.test_dci_research_capability tests.test_grid_regulation tests.test_grid_regulation_page tests.test_native_application
```
