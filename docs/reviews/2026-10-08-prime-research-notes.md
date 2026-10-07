# Prime research memory and P7 NOTES

## Implementation

The LLM now owns a replaceable free-text research note. A successful current-observation update also establishes a checkpoint for the model's next request. This closes the previous gap between small external WorldMap records and an independently growing model conversation. It does not by itself prove better BP35 solving.

| Layer | Responsibility | Deliberately outside this layer |
| --- | --- | --- |
| Generic Python `agents/prime/memory.py` | Immutable text revisions, opaque scope/evidence, bounded history, hash verification | Games, levels, RESET and choosing useful knowledge |
| Generic TS `context-memory.ts` | Replace obsolete model-view prefix at a complete accepted tool boundary; preserve raw history and later messages | Parsing P7 observations or deciding task progress |
| P7 workspace/runtime | Bind NOTES to exact current observation and workspace parent; apply level/RESET/kernel/mismatch calibration; build current snapshot | A second model runner or game-specific solving rules |
| Operator and packaged extension | Preserve actual task instructions; carry trusted receipts; use Pi's existing context hook | New tool registries or prompt-only pretend tools |

The application keeps the same three tools. `p7_workspace` accepts:

```javascript
{
  op: "notes",
  base_revision: currentWorkspaceRevision,
  observation_ref: currentObservationReference,
  text: "Useful findings, counterexamples, uncertainties and current intent"
}
```

The model chooses the note structure and replaces its entire content. The16KiB UTF-8 limit is a finite safety boundary, not a target length. `notes_read` and `notes_history` retrieve accepted versions. Raw observations, plans, feedback and explicit Python exports remain queryable. WorldMap/program authoring remains optional; notes-mode calibration does not require duplicating a note in a full structured model.

The immutable note blob is written before the existing atomic workspace pointer adopts it. There is no second active-memory pointer. Failed adoption may leave an orphan blob, but cannot make it current or insert it into accepted history.

## What the model sees

After an accepted NOTES update, the view contains the actual task instructions, current notes and observation/control state, the complete accepted assistant/tool-result group, and every later message. Pi retains system instructions and tool declarations. The initial board and obsolete execution prefix leave this view; the raw session remains intact.

The cut requires a successful native tool result with a matching trusted receipt and complete sibling results. Merely finishing a callback is insufficient. Later host responses can refresh the current board without moving the accepted anchor. A missing or ambiguous boundary causes conservative retention; native compaction recovery injects the checkpoint without guessing which compacted messages to delete. Note text remains ordinary content and grants no execution authority.

P7 interprets level changes and RESET. Knowledge survives; exact old state does not provide current calibration. Observation identity, workspace revision, action budgets, uncertainty, prediction grading, mismatch stopping and pause/cancel controls remain enforced. These game semantics are absent from the generic memory/projector.

## Verification

- Affected Python suites:228 passing tests, covering generic non-game memory, atomic adoption, exact identity, notes-mode action gates, lifecycle, historical compatibility and actual prompt wiring.
- `npm --prefix packages/typescript/asterion-prime-extension test`:43 pass,6 existing external witness skips. These skips are not converted to passing evidence.
- `npm --prefix packages/typescript/asterion-prime-extension run test:installed-pi`:actual Pi1.0.0 extension loader, context handler and model-message conversion pass with zero provider calls. Fixture14 raw messages become6 model messages; obsolete chapter sentinels disappear while system/tools, current notes, complete siblings and subsequent user text remain. Raw branch is unchanged; restart after compaction is tested.
- Independent implementation review has no blocking finding; targeted Ruff and `git diff --check` pass. Final independent audit recomputes source/wheel identities, raw trace hash chain/seal, actions, notes, usage and native cuts, and checks actual inactive unit/removed credentials; no discrepancy.
- `make promotion-check`:full PASS across25 commands, zero provider operations and no full dataset. The first run found an obsolete installed-official actor fixture; `44091934` updated it to commit current NOTES before action. Its standalone installed test passes while retaining real computation, exports,13 actions and closure checks. Production remains frozen at `ebcefec9`.
- Packaged `make asterion-prime-p7-level-witness GAME=r11l LEVEL=1`:PASS,1 completed level/7 paid actions/0 RESET; no failure, replay verified and trace sealed. The isolated run used gpt-6.1-sol/high, target1 and the existing900-second preset. Launcher through cleanup took266.997seconds; this includes packaging/startup and is not pure inference time.
- Seven accepted NOTES revisions:684,943,1101,1159,1121,787,810 UTF-8 bytes, at observation sequences0,1,2,3,4,6,7. The actual Pi stderr is untruncated and records17 successful `cut` outcomes; the last removes41 obsolete messages and retains the current2-message tool group before adding the memory snapshot. Repeated cut counts must not be summed as distinct deleted history.
- The22 recorded model usage events have input range6115–10625 tokens, last7747; normalized total input187827/output8610. These short-run usage figures do not establish BP35 context savings or measured cost; cache/timing decomposition was not collected.
- Wheel423 Python/MJS files match the frozen source, all578 frozen tracked source/resource files remain unchanged, and the packaged extension hash matches. Owned unit is inactive/dead with MainPID0; temporary environment removed, launcher exits0, runtime cleanup reports complete. The pre-existing user console PID52024 remains running.

Frozen production:`ebcefec9`; installed-fixture follow-up:`44091934`. Wheel SHA256:`7a599c0139e35c043329179f3d8badea8cee7a95f2767480a6944337cc0250a3`. Extension SHA256:`09340e21f6894a3a39dd02d8d33c38e52a0560e92acd9249b42d51b06730491e`. Run:`p7-live-20261007232229-db3aa154958447f9ac48e501`.

Private test/review evidence is retained under `.asterion-private/p7-notes-preparation-20261008/`. The [design](../superpowers/specs/2026-10-08-prime-research-notes-design.md) and [implementation plan](../superpowers/plans/2026-10-08-prime-research-notes.md) define the accepted scope.

## Remaining evidence boundary

No new BP35 L1–L6 comparison is established here. Message counts in a provider-free fixture are not provider token counts or latency savings. The earlier ARC NOTES byte measurements are not its complete context size. This successful short deployment witness establishes tool/package/context integration, not six-level reasoning quality. A further frozen comparison must measure actual context growth, useful note content, model wait time, actions and completion together.
