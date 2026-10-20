# Live Session Checkpoint

> Updated: 2026-10-20 15:08. **Session remains active — not a final handoff.**

## TL;DR

- P1 and P3–P6 already have one finite `deepseek/deepseek-flash` preset receipt each. Those receipts stand.
- P2 now has one finite flash inquiry: status `verified`, model calls 2, input 583, output 576, cost 867 micros. Notes revision `sha256:e3831a589eb252d687fadee6d60976a0f500f711775ced6b29e43cd8eeebb11f`. Fragment `6a4c24f668b7140d3d8ac553e61623754f188e1a66944d6b1d6924ee540fb8b4`.
- The zero-token `make asterion-prime-p2-run` path is unchanged. One inquiry is not a stability rate.

## Verified facts

- P1 live preset `p1-cfb3a57972ae762ad83bce81`, receipt `72d3569e7967bfc2ffe31c7baa8710f7d3458634ee8ff1af5f07e9b1d1077841`. Compaction witness `p1-86417a49d97c4a88c6d2466a`, receipt `37a32db7ce65767ea67b25bd6795a7e5192d998826f6c52feaf770e9a70af5ae`.
- P3 `p3-live-4845d3858cc1c526698e5d76`, receipt `c87cda3b8ee4fc432aa274c4eda46d15dc645d5448f8f4d906e3e2bcc25c3899`.
- P4 `p4-live-a5408e515e04808bc100791b`, generation 1→2.
- P5 `p5-live-5856895e1469cbe6e739780f`, receipt `314a419ee3f7158492f209d5f044bbdfe788d2ba6b8736f6d46db7da8e83c69b`.
- P6 `p6-live-4ab28bf1f52682c8`, `rolled-back`, receipt `07004c52690c10ef0e71fe5387d26a4e61a73f0e459f38709f53e526ec94d4a5`.
- Focused P2 tests passed: `tests.test_prime_p2_live` and `tests.test_prime_p2_inquiry`. `ruff check` passed on the new files.
- Guest `ubuntu-fusion-control` was running for the P2 inquiry. Local `main` stays unpushed.

## Current judgment

- P1–P6 each have one completed flash preset on the current application paths. P2's completed path is `make asterion-prime-p2-live`.
- The later P1 run `p1-03801814231299013ad98348` still stopped before `oracle.pass`. Read the `oracle.reject.*` line from commit `aca0fa5b` before changing the continuation prompt.

## Open boundary

- Single runs are not stability rates.
- The P7 low-threshold compaction test, a full benchmark, an official card, and an L9 rerun stay out of scope.
- `make promotion-check` is not a pass on this host.

## Next action

1. Leave the six flash receipts in place.
2. Start another paid run only after a new authorization.
3. Do not push `main` unless the user asks.

## Ready commands

```bash
make asterion-prime-p2-live PRIME_ORB_MACHINE=ubuntu-fusion-control
```

Run this only after a new authorization. In zsh, `status` is read-only; use another variable name.
