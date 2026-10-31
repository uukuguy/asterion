# Next-Session Handoff

> Updated: 2026-10-31 21:14. End of session.

## TL;DR

- The grid regulation desk is the active work. Prime/P7 stays closed. `native.dci-complete` is not built. Another model call is not authorized.
- Local `main` and the recorded `origin/main` are both `1bfe73db`. This handoff did not fetch. Untracked regulation originals under `docs/` stay untracked.
- Nothing is listening on `127.0.0.1:8765`. The last operator search finished on 2026-10-27 00:23 with relative `passages.txt` reads and `run.completed`. It is not an applicability judgment.

## 已验证事实

- The desk is `src/asterion/applications/grid_regulation/page.html`. POST `/api/measures` calls `answer_fault`. `page.main` passes `LiveGridResearch`. `serve` with no research object returns 422 and does not start Pi. Tools are `read,bash`. `max_turns` is `"32"`. The command passes `--thinking off` and canonical L2 `{"tool_result_chars":20000}`. There is no clock cancel and no 60-second cancel. `阅读没有完成 N 秒` is elapsed time. `make grid-regulation` serves `127.0.0.1` and does not pass `--open`.
- stderr prints the turn, the sentence written before a tool, then the file and line window, or the projection file and the search text. The question, the command, the path, the tool result, and the final answer stay off that log [`b6f29c24`, `ab856b5c`].
- A read of the projection's own `passages.txt` or `contents.txt` counts when the path is absolute. The recorded name is the file name. A path outside that directory still fails [`c1525efd`].
- The handling column and bold text are heavier type. There is no yellow fill [`9182ee82`].
- One authorized question on the 2023 stability DOCX ran three times. The first stopped at `Pi runtime turn limit exceeded` after 83.6 seconds. The second wrote bash-only `final.txt` and was not rendered (`d5dda80f234f977549a32dfd4e1651894ad3a646eef00ead8a32e767f673051b`). The third completed in 33.1 seconds: 6 bash, 18 read, 835 anchors, reply 1917 characters (`fea0a888146c18809eef767690e411f05b2acd6756c0b080c4a7c784085a01bf`). That reply is not an applicability judgment.
- Later operator searches, read from event metadata only: `c924eeea5811` at 2026-10-26 03:12 completed with 28 absolute reads and was rejected by the desk process then running. `56aebc056464` at 03:41 completed with 27 relative reads and 0 tool errors, `final.txt` 5633 bytes. `64691eb61365` at 04:04 completed with 8 relative reads and 2 tool errors, `final.txt` 4076 bytes. `64cf15f748f9` at 2026-10-27 00:23 completed with 18 relative reads and 0 tool errors, `final.txt` 3738 bytes. Reply text was not copied into this record. These runs are not applicability judgments. The page status is not stored in those directories.
- At 2026-10-31 21:14 nothing is listening on 8765, and no `grid_regulation.page` process is running.

## 当前判断

- A model-written answer uses native-dci through `prepare_native_application` inside `LiveGridResearch.run`. Tests do not call `run`. The first paragraph is supposed to state what the regulation requires. Clause numbers are citations. Evidence is one paragraph or one table under the section heading. Whether the later completed runs do that has not been judged.
- Do not raise `max_turns`. Do not add a timeout. The operator stops a long search with Ctrl-C. Do not start Pi, `make grid-regulation`, or a dataset unless the user asks. Submitting the form starts Pi.
- `prepare_prime_application` stays the Prime door. The desk does not open a second model client.

## 历史归档

- The 300-second cancel is removed. Thinking stays off. An earlier thinking-on run hit the stdout cap.
- A bash-only stream has no passage anchors, so the desk returns `regulation measures are unavailable` even when `final.txt` exists.
- The word-match chain and `lookup_chain` are removed. `lookup_measures` and POST `/api/cite` stay. The JSON example still uses the fictional corpus.
- Do not build `native.dci-complete`. Do not reinstall provider `dci-agent-lite`. Do not change `examples/applications/native_dci.py` off `read,grep`. D-2026-07-31-02 stays. Do not commit regulation originals. Do not push unless the user asks.

## 未完成边界

- Scanned pages, CID fonts without a ToUnicode map, OLE `.doc`, and `docs/guodiao_2023_2.0_1.0-utf8.dsl` are not citation anchors.
- `make promotion-check` has not been run since `context-policy-extension.mjs` was added. `make native-dci-example` was not run.
- Worktrees `asterion-p1-workload`, `asterion-p2-worker`, and `asterion-p3-real-rlm` remain. They are unrelated.
- Evidence stays under `outputs/grid-regulation`, mode `0700`, off HTTP and off git.

## 下一动作

1. Do not start the desk or Pi. Read this file, then `git status --short` and `git log -1`.
2. Do not commit the regulation originals. Do not treat `64cf15f748f9` or the earlier rendered reply as an applicability judgment.
3. A new search is a new model call and needs a new authorization.

## Ready-to-paste command

```bash
uv run python -m unittest tests.test_document_tools tests.test_dci_research_capability tests.test_grid_regulation tests.test_grid_regulation_page tests.test_native_application
```
