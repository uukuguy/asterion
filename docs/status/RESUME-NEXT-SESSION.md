# Live Session Checkpoint

> Updated: 2026-10-20 16:08. **Session remains active — not a final handoff.**

## TL;DR

- P2's program-shaped inquiry is verified: `retrieve` bounds `[0, 1]`, model calls 3, input 1128, output 897, cost 1417 micros. Fragment `6a4c24f668b7140d3d8ac553e61623754f188e1a66944d6b1d6924ee540fb8b4`. Notes `sha256:f156051535646c2157b4426cc8a965fed6a588123ac28ff94362c17ad2ac77a5`. The corpus stayed out of the query prompt. The zero-token preset is unchanged.
- P1 continuation `p1-5f194466f4f4077ec270a9e4` printed `oracle.pass` and completed. Receipt `4f7e05f467a8506755b39ebf51147b68d46771f2e9679d4d4c25549c22beeb0c`. Summary hash matches the witness. Prompts and `AsterionPrimeLimits(8, 4, 600000)` stayed in place.
- The writing map is `docs/guides/prime-application-writing.md`. No new P application.
- One pass is not a stability rate. No further paid run is authorized.

## Verified facts

- P1 live preset `p1-cfb3a57972ae762ad83bce81`, receipt `72d3569e7967bfc2ffe31c7baa8710f7d3458634ee8ff1af5f07e9b1d1077841`. Compaction witness `p1-86417a49d97c4a88c6d2466a`, receipt `37a32db7ce65767ea67b25bd6795a7e5192d998826f6c52feaf770e9a70af5ae`. Later continuation `p1-5f194466f4f4077ec270a9e4`, receipt `4f7e05f467a8506755b39ebf51147b68d46771f2e9679d4d4c25549c22beeb0c`.
- P3 `p3-live-4845d3858cc1c526698e5d76`, receipt `c87cda3b8ee4fc432aa274c4eda46d15dc645d5448f8f4d906e3e2bcc25c3899`.
- P4 `p4-live-a5408e515e04808bc100791b`, generation 1→2.
- P5 `p5-live-5856895e1469cbe6e739780f`, receipt `314a419ee3f7158492f209d5f044bbdfe788d2ba6b8736f6d46db7da8e83c69b`.
- P6 `p6-live-4ab28bf1f52682c8`, `rolled-back`, receipt `07004c52690c10ef0e71fe5387d26a4e61a73f0e459f38709f53e526ec94d4a5`.
- P2 program-shaped live receipt: `retrieve` `[0, 1]`, calls 3, fragment `6a4c24f668b7140d3d8ac553e61623754f188e1a66944d6b1d6924ee540fb8b4`, notes `sha256:f156051535646c2157b4426cc8a965fed6a588123ac28ff94362c17ad2ac77a5`.
- Focused P2 tests passed: `tests.test_prime_p2_program`, `tests.test_prime_p2_live`, and `tests.test_prime_p2_inquiry`. `ruff check` passed on the interpreter and live adapter. `tools/check_docs.py` passed before the live receipt.
- Guest `ubuntu-fusion-control` was running for the P2 inquiry. Local `main` stays unpushed.

## Current judgment

- P2's program-shaped receipt is the live evidence for D-2026-10-20-03. The earlier JSON-bounds receipt remains a separate inquiry.
- P1 `p1-5f194466f4f4077ec270a9e4` completed with `oracle.pass`. Before that, `p1-2b2bc38316f672779559bc8e` stopped on tool callback 5 of 4, and `p1-ab9e8b4bb66dc3f2254352f9` printed `oracle.reject.final_result`. The older miss `p1-03801814231299013ad98348` has no clause name. Prompts were not changed.

## Open boundary

- Single runs are not stability rates.
- The P7 low-threshold compaction test, a full benchmark, an official card, and an L9 rerun stay out of scope.
- `make promotion-check` is not a pass on this host.

## Next action

1. Leave the recorded receipts in place. Start another paid run only after a new authorization.
2. Do not push `main`. Do not start a P7 benchmark, an official card, an L9 rerun, or a second P application.

## Ready commands

```bash
make asterion-prime-p2-live PRIME_ORB_MACHINE=ubuntu-fusion-control
make asterion-prime-p1-run PRIME_ORB_MACHINE=ubuntu-fusion-control
```

Run either only after a new authorization, and only one at a time. The same guest cannot host two orb presets together. In zsh, `status` is read-only; use another variable name.
