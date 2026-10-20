# Next-Session Handoff

> Updated: 2026-10-20 16:15 end of session.

## TL;DR

- The showcase follow-up is closed. P2 has one program-shaped `deepseek/deepseek-flash` receipt. P1 has one later `oracle.pass` on the unchanged prompt and cap. The writing map points at the seven existing applications.
- No preset process remains. Guest `ubuntu-fusion-control` is running. Local `main` is ahead of `origin/main` and is not pushed.
- Start another paid run only after a new authorization.

## Verified facts

- P2 program-shaped inquiry: status `verified`, operation `retrieve`, bounds `[0, 1]`, model calls 3, input 1128, output 897, cost 1417 micros. Fragment `6a4c24f668b7140d3d8ac553e61623754f188e1a66944d6b1d6924ee540fb8b4`. Notes `sha256:f156051535646c2157b4426cc8a965fed6a588123ac28ff94362c17ad2ac77a5`. The query prompt did not contain the corpus body. The zero-token `make asterion-prime-p2-run` path was not changed.
- Focused tests passed before that receipt: `tests.test_prime_p2_program`, `tests.test_prime_p2_live`, and `tests.test_prime_p2_inquiry`. `ruff check` passed on the interpreter and live adapter. `tools/check_docs.py` passed on the writing-map commit.
- P1 continuation `p1-5f194466f4f4077ec270a9e4` completed and printed `oracle.pass`. Receipt `4f7e05f467a8506755b39ebf51147b68d46771f2e9679d4d4c25549c22beeb0c`. Summary `e7fb9c3c83f6e95401b59874a6556cf02f63a850d369ea81b7c8f155c8201841`, the same hash as witness `p1-86417a49d97c4a88c6d2466a`.
- The same cap stayed `AsterionPrimeLimits(8, 4, 600000)`. `P1_CONTINUATION_PROMPT` and the stage-two prompt were not edited.
- Earlier flash receipts still stand: P1 `p1-cfb3a57972ae762ad83bce81` receipt `72d3569e7967bfc2ffe31c7baa8710f7d3458634ee8ff1af5f07e9b1d1077841`; P3 `p3-live-4845d3858cc1c526698e5d76` receipt `c87cda3b8ee4fc432aa274c4eda46d15dc645d5448f8f4d906e3e2bcc25c3899`; P4 `p4-live-a5408e515e04808bc100791b` generation 1→2; P5 `p5-live-5856895e1469cbe6e739780f` receipt `314a419ee3f7158492f209d5f044bbdfe788d2ba6b8736f6d46db7da8e83c69b`; P6 `p6-live-4ab28bf1f52682c8` `rolled-back` receipt `07004c52690c10ef0e71fe5387d26a4e61a73f0e459f38709f53e526ec94d4a5`.
- Commits on local `main`: `efb326b1`, `2770be70`, `7041e530`, `47374132`.

## Current judgment

- D-2026-10-20-03 is the P2 statement contract. The host reads one `retrieve` or `transform` statement with `ast` and does not execute arbitrary Python. `P2ContextService` performs the call. `ResearchNotes` still commits only after the fragment digest matches.
- The P2 model needed one replacement ask on the successful run. The first prompt shape, before `2770be70`, did not produce a public receipt.
- The P1 `oracle.pass` shows the kernel can finish the continuation after the dedicated summary. The tool-callback stop and `oracle.reject.final_result` in the same authorization show that one pass is not a rate.
- The expected continuation value remains the oracle computation from `P1_INPUT_TUPLE`: setup 40, continuation call 58, `final_result` 98. The public pass does not print that triple.

## Historical archive

- The earlier P2 JSON-bounds inquiry remains a separate receipt: calls 2, input 583, output 576, cost 867 micros, notes `sha256:e3831a589eb252d687fadee6d60976a0f500f711775ced6b29e43cd8eeebb11f`.
- Two program-shaped attempts on the first query prompt failed closed. The model emitted a bash tool call, then an empty turn at the 512-token output cap.
- P1 `p1-2b2bc38316f672779559bc8e` stopped `recovery-required` after `stage2.release`: tool callbacks observed 5, limit 4, `prime-tool-callback-limit`, receipt null.
- P1 `p1-ab9e8b4bb66dc3f2254352f9` reached `stage2.complete` and printed `oracle.reject.final_result`. Receipt null.
- P1 `p1-03801814231299013ad98348` stopped after `stage2.complete` before commit `aca0fa5b`, so that miss has no clause name.
- The completion worklist packages `P-NOTES-1`, `P-P2-1`, `P-LIVE-1`, `P-COMPOSE-1`, and `P-COMPACT-1` stay done. Their closure does not authorize a run.
- Adding another P application was not the showcase fix. P3–P6 remain the existing text-pattern demos. P7 remains the domain demo.

## Open boundary

- Single runs are not stability rates.
- The P7 low-threshold compaction test, a full benchmark, an official card, an L9 rerun, moving probe admission into Prime, and Prime CLI positioning stay open.
- `make promotion-check` is not a pass on this Node 24 symlink host.
- Preset machine name `ubuntu` is absent. Use `ubuntu-fusion-control`.
- Old wheel directories under `.asterion-prime-*-wheel.*` predate this session. They are not a running preset.

## Next action

1. Read INDEX, CURRENT-STATE, this handoff, and the 2026-10-20 JOURNAL tail. Do not start a paid run from this file.
2. Do not push `main` unless the user asks. Do not add a P application, a P7 benchmark, an official card, or an L9 rerun from this closeout.

## Ready commands

```bash
make asterion-prime-p2-live PRIME_ORB_MACHINE=ubuntu-fusion-control
make asterion-prime-p1-run PRIME_ORB_MACHINE=ubuntu-fusion-control
```

Run either only after a new authorization, and only one at a time. The same guest cannot host two orb presets together. In zsh, `status` is read-only; use another variable name.
