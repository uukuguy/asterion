# Prime application completion

**Goal:** Finish P1–P6 as Prime applications, and lift only the generic research record out of P7.

**Approved scope:** The user confirmed `P-NOTES-1`, then `P-P2-1`, then the existing finite presets in `P-LIVE-1`. A full benchmark or official card is not authorized.

## Packages

| ID | Status | Outcome | Depends on | Acceptance |
|---|---|---|---|---|
| P-NOTES-1 | done | Prime accepted-note epoch; P7 is the first consumer | P7 milestone `aca76ed7` | Decision D-2026-10-20-01. `ResearchNotes` commits history separately from saved documents. P7 game fields stay in `p7/research.py`. Provider-free tests pass. No model run. |
| P-P2-1 | done | P2 model-owned corpus retrieval on the same epoch | P-NOTES-1 | Operator-owned corpus. The injected model writes the query and the answer. The cited fragment digest must match the slice P2 returned. A mismatch does not commit a note. No corpus scanner in Prime. Provider-free tests only. |
| P-LIVE-1 | done | Current-main finite re-verification of P1, P3, P4, P5, and P6 | P-P2-1 | Existing presets only, cap `AsterionPrimeLimits(8, 4, 600000)`. P1 `p1-cfb3a57972ae762ad83bce81` completed, receipt `72d3569e7967bfc2ffe31c7baa8710f7d3458634ee8ff1af5f07e9b1d1077841`. P4 continuation `p4-live-a5408e515e04808bc100791b` generation 1→2; commit checkpoint `7d53feef4a2c6712108ac47e39012ece4fe184fc151bef093087d03951b6c07b`, recover receipt `5a8a75778406eb38fc021b144b21bf173f6abc3ffceff0fd75a24acbca8ea725`. P3 `p3-live-4845d3858cc1c526698e5d76`, `model_call_count` 2, receipt `c87cda3b8ee4fc432aa274c4eda46d15dc645d5448f8f4d906e3e2bcc25c3899`. P5 `p5-live-5856895e1469cbe6e739780f`, repair 1, failed verify 1, receipt `314a419ee3f7158492f209d5f044bbdfe788d2ba6b8736f6d46db7da8e83c69b`. P6 `p6-live-4ab28bf1f52682c8`, `rolled-back`, rollback 1, receipt `07004c52690c10ef0e71fe5387d26a4e61a73f0e459f38709f53e526ec94d4a5`. |
| P-COMPOSE-1 | done | P1 kernel continuity across a P4 process handoff | P-LIVE-1 P1 and P4 passes | Live receipt `94492ade19a0feb87a29da3d2b8424c3c6b16f6a801d76a3779cde04d440f943`, continuation `compose-cont-11d50ba880c20ded`, generation 2, `identity_match` strict, resumed `AffineAccumulator` and `accumulator`, kernel identity `5c3bb0d24a6d7fc3d01306f162ce675805067616a60f8a0eea609bacc88fbdeb`. Commit worker `fb31c036946178d7bb6ff15f9b3e190f5d780ac87e613b67eeaf098a07d47da0` differs from resume worker `7263e215172986212f1ee30a0289261a3d4adbed9850b04496e910789750132c`. `model_call_count` 1, `input_tokens` 159. |
| P-COMPACT-1 | done | Dedicated code-aware compaction in Prime, witnessed by P1 | separate from P7 game runs | Live P1 `p1-86417a49d97c4a88c6d2466a` completed inside cap `AsterionPrimeLimits(8, 4, 600000)`, receipt `37a32db7ce65767ea67b25bd6795a7e5192d998826f6c52feaf770e9a70af5ae`. The persisted summary kind is `asterion.prime-code-summary/v1`, sha256 `e7fb9c3c83f6e95401b59874a6556cf02f63a850d369ea81b7c8f155c8201841`, `keep_recent_tokens` 256 below the native automatic 20000, bindings `AffineAccumulator`, `accumulator`, `input_tuple`, `task_statement`, and the seeded `task_statement` body. The summary text has no native Goal or Constraints sections. `compact.persist` preceded `oracle.pass`. No resource alarm. The earlier side-channel receipt `f492701eadcca74cb720efc2cf92f5ed46b7e7028435120f5dc286654c762a35` is not this witness. |

## Boundary

Prime owns document bytes, the accepted-note pointer's read rules, and the passive evidence index. The application owns the pointer's persistence, domain evidence checks, goals, tools, and effect rules. Effectful probe admission stays under D-2026-10-13-03 until a later package extracts only the authority hook, without game mechanics.
