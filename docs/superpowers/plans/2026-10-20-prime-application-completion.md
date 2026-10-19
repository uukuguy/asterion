# Prime application completion

**Goal:** Finish P1–P6 as Prime applications, and lift only the generic research record out of P7.

**Approved scope:** The user confirmed package `P-NOTES-1` on 2026-10-20. Later packages stay listed and unstarted. No paid model run, full benchmark, or official card is authorized by this worklist.

## Packages

| ID | Status | Outcome | Depends on | Acceptance |
|---|---|---|---|---|
| P-NOTES-1 | done | Prime accepted-note epoch; P7 is the first consumer | P7 milestone `aca76ed7` | Decision D-2026-10-20-01. `ResearchNotes` commits history separately from saved documents. P7 game fields stay in `p7/research.py`. Provider-free tests pass. No model run. |
| P-P2-1 | done | P2 model-owned corpus retrieval on the same epoch | P-NOTES-1 | Operator-owned corpus. The injected model writes the query and the answer. The cited fragment digest must match the slice P2 returned. A mismatch does not commit a note. No corpus scanner in Prime. Provider-free tests only. |
| P-LIVE-1 | blocked | Current-main finite re-verification of P1, P3, P4, P5, P6 | preset host | Existing presets only. On 2026-10-20 the named machine `ubuntu` was absent. Guest `ubuntu-fusion-control` can see the repo and Pi entry, and has no `/root/.local/bin/uv`. No preset launched and no model call was made. P5 still needs one real repair. P6 still needs one real rollback. |
| P-COMPOSE-1 | blocked | P1 kernel continuity across a P4 process handoff | P-LIVE-1 P1 and P4 passes | Identity match stays strict. The receipt states which kernel objects resume. |
| P-COMPACT-1 | blocked | Dedicated code-aware compaction in Prime, witnessed by P1 | separate from P7 game runs | Live low-threshold summary on the P1 preset. A native generic summary does not count. |

## Boundary

Prime owns document bytes, the accepted-note pointer's read rules, and the passive evidence index. The application owns the pointer's persistence, domain evidence checks, goals, tools, and effect rules. Effectful probe admission stays under D-2026-10-13-03 until a later package extracts only the authority hook, without game mechanics.
