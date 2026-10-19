# Prime application completion

**Goal:** Finish P1–P6 as Prime applications, and lift only the generic research record out of P7.

**Approved scope:** The user confirmed `P-NOTES-1`, then `P-P2-1`, then the existing finite presets in `P-LIVE-1`. A full benchmark or official card is not authorized.

## Packages

| ID | Status | Outcome | Depends on | Acceptance |
|---|---|---|---|---|
| P-NOTES-1 | done | Prime accepted-note epoch; P7 is the first consumer | P7 milestone `aca76ed7` | Decision D-2026-10-20-01. `ResearchNotes` commits history separately from saved documents. P7 game fields stay in `p7/research.py`. Provider-free tests pass. No model run. |
| P-P2-1 | done | P2 model-owned corpus retrieval on the same epoch | P-NOTES-1 | Operator-owned corpus. The injected model writes the query and the answer. The cited fragment digest must match the slice P2 returned. A mismatch does not commit a note. No corpus scanner in Prime. Provider-free tests only. |
| P-LIVE-1 | in progress | Current-main finite re-verification of P1, P3, P4, P5, P6 | P-P2-1 | Existing presets only. Guest `ubuntu-fusion-control` has root `uv` 0.13.1 and managed CPython 3.12.15. One `asterion-prime-p1-run` on 2026-10-20, run `p1-cbf17566ec1bdd98a2d6c0ab`, reached compact and resume, then stopped `recovery-required`: model callbacks limit 8, observed 9, `prime-model-callback-limit`, phase execution, `receipt_sha256` null. Not a completed P1 verification. P4, P3, P5, and P6 have not run. P5 still needs one real repair. P6 still needs one real rollback. |
| P-COMPOSE-1 | blocked | P1 kernel continuity across a P4 process handoff | P-LIVE-1 P1 and P4 passes | Identity match stays strict. The receipt states which kernel objects resume. |
| P-COMPACT-1 | blocked | Dedicated code-aware compaction in Prime, witnessed by P1 | separate from P7 game runs | Live low-threshold summary on the P1 preset. A native generic summary does not count. |

## Boundary

Prime owns document bytes, the accepted-note pointer's read rules, and the passive evidence index. The application owns the pointer's persistence, domain evidence checks, goals, tools, and effect rules. Effectful probe admission stays under D-2026-10-13-03 until a later package extracts only the authority hook, without game mechanics.
