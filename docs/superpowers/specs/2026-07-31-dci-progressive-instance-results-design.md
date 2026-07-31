# DCI Progressive Instance Results Design

## Goal

Make every DCI benchmark instance fully executable against its complete local
dataset, while allowing a bounded, clearly labelled `min(50, total)` run to
publish a useful version result before the complete run is performed.

## Decisions

- An executable instance has an exact full dataset count and accepts both an
  explicit `--case-limit` and the full-range selection.  Execution authority
  controls whether a run starts; it does not remove the full-range code path.
- A result from fewer than all cases is a **阶段性结果**, never a paper result
  or a full-instance result.  Its public record must show `已跑/总量`.
- The first implementation target is
  `dci.qa.bamboogle.paper-full125@1.0.0`.  Its 125-row data file and shared
  Wikipedia corpus are operator-owned local inputs already mapped by the DCI
  binding layer.
- Each row in `docs/status/DCI-BENCHMARK-INSTANCES.md` records implementation
  state, run coverage, score, Agent model, Judge model, cost, evidence path,
  and whether a complete run has been performed.

## Implementation Shape

1. Expose a dedicated full125 suite and mark the Bamboogle paper instance as
   implemented with an all-case count of 125.
2. Generalize the real DCI executor from one hard-coded Bamboogle sample50
   contract to the two exact Bamboogle contracts.  It validates each contract's
   own finite maximum (50 or 125) before any Agent/Judge work.
3. Cover the full125 instance, its 50-case bounded plan, full-range plan,
   acceptance-host selection, and executor rejection boundaries with unittest
   tests before implementation.
4. Update the Chinese instance list and runbook with the new result vocabulary.
   Populate factual run fields only after a real authorized run finishes.

## Non-goals

- A 50/125 run does not claim reproduction of the paper's 125-case score.
- This change does not run the model or incur provider cost by itself.
- Other DCI task families remain separate follow-on instances using the same
  result-record convention.
