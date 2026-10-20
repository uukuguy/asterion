# Next-Session Handoff

> Updated: 2026-10-20 13:04 end of session.

## TL;DR

- The completion worklist is done: `P-NOTES-1`, `P-P2-1`, `P-LIVE-1`, `P-COMPOSE-1`, and `P-COMPACT-1`.
- Dedicated compaction has one completed P1 witness: run `p1-86417a49d97c4a88c6d2466a`, receipt `37a32db7ce65767ea67b25bd6795a7e5192d998826f6c52feaf770e9a70af5ae`.
- A later run of the same preset stopped before `oracle.pass`. Commit `aca0fa5b` prints the failed clause. Do not start a paid run from this handoff.

## Verified facts

- Canonical worklist: `docs/superpowers/plans/2026-10-20-prime-application-completion.md`.
- `P-LIVE-1` used the existing presets and cap `AsterionPrimeLimits(8, 4, 600000)`. Receipts: P1 `p1-cfb3a57972ae762ad83bce81` / `72d3569e7967bfc2ffe31c7baa8710f7d3458634ee8ff1af5f07e9b1d1077841`; P4 `p4-live-a5408e515e04808bc100791b`, generation 1→2; P3 `p3-live-4845d3858cc1c526698e5d76` / `c87cda3b8ee4fc432aa274c4eda46d15dc645d5448f8f4d906e3e2bcc25c3899`; P5 `p5-live-5856895e1469cbe6e739780f`, one repair and one failed verify, receipt `314a419ee3f7158492f209d5f044bbdfe788d2ba6b8736f6d46db7da8e83c69b`; P6 `p6-live-4ab28bf1f52682c8`, `rolled-back`, receipt `07004c52690c10ef0e71fe5387d26a4e61a73f0e459f38709f53e526ec94d4a5`.
- `P-COMPOSE-1` receipt `94492ade19a0feb87a29da3d2b8424c3c6b16f6a801d76a3779cde04d440f943`, continuation `compose-cont-11d50ba880c20ded`, `identity_match` strict. Probe `(40, 58)` stayed. Commit `ea91a888`.
- The compact hook returns the code-aware summary. Pi persists that text with `fromHook` true. A native Goal or Constraints summary on that result is refused. A dedicated summary does not spend the two summarizer callback slots. A native KERNEL-NOTE compact still spends them. Compact still stops when fewer than 2 callbacks remain.
- Closing witness `4e4f175e`: status `completed`, summary kind `asterion.prime-code-summary/v1`, sha256 `e7fb9c3c83f6e95401b59874a6556cf02f63a850d369ea81b7c8f155c8201841`, `keep_recent_tokens` 256 below the native automatic 20000. Bindings are `AffineAccumulator`, `accumulator`, `input_tuple`, `task_statement`, plus the seeded task body. `compact.persist` came before `oracle.pass`. `resource_alarms` was empty.
- `aca0fa5b` prints one closed stage from `verify()` when stage two rejects: `oracle.reject.final_result`, `oracle.reject.final_read`, `oracle.reject.final_verified`, `oracle.reject.final_call`, and also `snapshot`, `prefix`, `checkpoint`, `objects`, `receipt`, and `effect`. An unknown stage still raises `P1OperatorError`. A pass still prints only `oracle.pass`. The focused run was 21 tests OK, including the previous success stage list.
- After `4e4f175e`, the operator reran the same preset. Run `p1-03801814231299013ad98348` ended `recovery-required`, `receipt_sha256` null, the same summary sha256, stages through `stage2.complete`, and no `oracle.pass`. That output has no clause name because it predates `aca0fa5b`.
- `make promotion-check` did not pass here. The offline `node@22` cache missed, and `/opt/homebrew/bin/node` is a Node 24 symlink. `tests.test_prime_extension_build` passed, 9 tests. Do not record promotion-check as PASS.
- Local `main` is ahead of `origin/main`. This work is not pushed. Milestone tags are unchanged.
- No preset process remains. Guest `ubuntu-fusion-control` is running. The editor `ruff` server was left in place.

## Current judgment

- The dedicated summary text is stable. The one continuation cell is not. The completed run and the later miss share summary sha256 `e7fb9c3c…`.
- Read the new clause label before any change to the continuation prompt, the oracle pass condition, or the cap.
- `P-COMPACT-1` stays done. The later miss does not replace receipt `37a32db7…`.
- Effectful probe admission stays in P7 under D-2026-10-13-03.

## Superseded

- The 02:44 handoff is stale. `P-LIVE-1` is not open on the 9/8 stop, and P4–P6 have run.
- Side-channel receipt `f492701eadcca74cb720efc2cf92f5ed46b7e7028435120f5dc286654c762a35`, run `p1-38239462474f1feeb9a85a64`, is not the compaction witness. Commit `3141322e` stored that name list.
- These `recovery-required` runs are not witnesses: `p1-cbf17566ec1bdd98a2d6c0ab` (9/8 before the dedicated path), `p1-d0f6b4b65a79102349fb89e4`, `p1-eb870ddb40ff162d09044a6e` (9/8 after persist), `p1-06eb2b5b68f4a92dbf3cdc36`, `p1-81b7ed492edb58a04d7b05af`, `p1-038392b67b6bbb50d0b1d86e` (tool cap 5/4), `p1-ff6e8d7509f7302b34f4490d` (combined final clause), `p1-03801814231299013ad98348`.
- Do not restore the open `failure.*` stage prefix. It was removed before `4e4f175e`.
- Do not follow `docs/status/climb/session-state.json`.
- Do not treat `P-P2-1` as a live model-retrieval proof.
- The Orb machine name `ubuntu` is absent. Use `PRIME_ORB_MACHINE=ubuntu-fusion-control`.

## Open boundary

- One completed witness is not a stability rate.
- The P7 low-threshold compaction test in D-2026-10-10-02 has not run.
- `make promotion-check` is not a pass on this host.
- A live P2 model preset, moving probe admission into Prime, Prime CLI purpose, a full benchmark, an official card, and an L9 rerun stay out of scope.
- Token totals are throughput. `pi_sdk_estimate` is not a bill.

## Next action

1. Do not launch a paid run from this handoff.
2. After a new authorization, rerun the same P1 preset once. Read the single `oracle.reject.*` line between `stage2.complete` and `host2.close`. Keep the cap and the `(40, 58)` probe. Leave the continuation prompt unchanged until that clause is known.
3. Do not push `main` unless the user asks.

## Ready commands

```bash
make asterion-prime-p1-run PRIME_ORB_MACHINE=ubuntu-fusion-control
```

Run this only after a new authorization. The guest is already running. A shell line `echo EXIT:$?` hides the make status. Read the recipe `EXIT:` line. In zsh, `status` is read-only; use another variable name.
