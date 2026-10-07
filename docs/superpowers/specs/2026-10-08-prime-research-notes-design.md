# Prime research memory and P7 NOTES design

## Authority and intent

The user approved implementing P7 NOTES after reviewing actual ARC NOTES and P7 context evidence, and explicitly requires generic and P7-specific layers. The LLM chooses useful facts, hypotheses, counterexamples, questions and plans. Entering L5 must not require carrying the full L1–L4 execution transcript. Existing raw evidence remains queryable. This document concretizes that approved direction; software and a bounded deployment check do not establish BP35 L1–L6 solving ability.

## Selected approach

Use the existing Prime extension's native `on("context")` hook for a model-only projection, and retain immutable raw session/evidence. A standalone NOTES file would not change LLM history. Earlier generic compaction alone would not implement model-selected research memory. No new runner or public runtime protocol is introduced.

### Generic Python memory

Add `agents/prime/memory.py`: immutable, scoped, content-addressed free-text snapshots. Text is nonblank and at most16KiB UTF-8; this is a finite boundary, not a target length or mandatory template. No game/level/RESET imports. Snapshot storage has no independent mutable current pointer: the application adopts a snapshot by its existing atomic workspace revision pointer. Interrupted writes may leave unreachable blobs, never active memory. Historical references are immutable and scope-checked.

### Generic model context

Add a pure TypeScript projector and narrow controller in the packaged Prime extension. Input is a trusted `{revision, anchorToolCallId, content}` checkpoint, with optional same-revision refreshes. Model-owned NOTES remain ordinary content, never system instructions or execution authority.

The model view consists of one host-built memory message plus the accepted assistant/tool-result group and all subsequent messages. Cutting requires locating the actual accepted tool call, all sibling results, an unambiguous complete boundary and no pending/unknown effect. Preserve the complete retained group and tool pairs. Raw messages and session entries are never mutated. Pi-owned system prompt/tool declarations stay under Pi's context-hook contract.

Missing/ambiguous anchors cause no destructive cut. When native compaction has removed the anchor, inject the current checkpoint while preserving the compacted messages. Recover accepted receipts from the trusted raw session branch. Do not infer an anchor from prose, observation sequence or a compaction summary. Context handler exceptions may be swallowed by Pi, so conservative behavior and explicit public-safe outcome metadata are required; never count a skipped cut as success.

### Cross-language private envelope

Only a trusted application method result may carry:

```json
{"context_memory":{"version":"asterion.prime-context-memory/v1","revision":"<immutable note revision>","content":"<complete task instructions and current research snapshot>","commit":true}}
```

`commit:true` is emitted only after successful current-observation NOTES adoption. The extension derives the anchor from the actual tool callback ID. Later responses may refresh content using `commit:false` and the same accepted note revision. The extension removes this envelope from model-visible tool text and retains validated metadata in tool details. Arbitrary IPython stdout cannot establish a checkpoint. This is a private host/extension envelope, not a new public protocol/manifest.

### P7 adapter

Keep the existing three tools. Add `p7_workspace` request `{op:"notes",base_revision,observation_ref,text}`. Require the exact current workspace parent and current observation reference; reject empty/oversize/stale input before adoption. Store the generic snapshot link inside the existing ResearchWorkspace revision and use its existing current pointer as sole commit authority. Plans continue to bind `workspace_revision` and real observation identity.

In the notes learner profile, accepted current notes satisfy the existing revision/calibration requirement without a second full WorldMap submission. They do not bypass pause, uncertainty, blocked processing, finite action budget, current grounding, complete prediction grading or mismatch stopping. Legacy Solver default and explicit historical cognition paths preserve their contracts. The modern P7 operator selects notes for solve/witness/autonomy; no operator-facing extra knob is required.

Retain WorldMap/program exports/read/history for optional detailed work. NOTES is free text, not an additional mandatory structured schema. Preserve note links through optional legacy revisions; explicitly selected old evidence remains readable with optional-note compatibility and scope/hash checks. Archived snapshots remain available through existing workspace/research retrieval.

P7 supplies game observations, task/level boundaries and RESET flags. RESET retains knowledge but requires current-observation calibration; a level edge marks earlier local state stale and prompts the model to carry useful learning forward. Generic memory sees only opaque scope/references.

### Prompt and projection integrity

The current initial user prompt combines invariant instructions and an initial board. Do not preserve that stale board indefinitely or drop instructions while cutting. Before appending initial research JSON, the operator calls `research_host.set_memory_instructions(prompt)`. Each trusted checkpoint contains those actual invariant instructions and the current notes/observation/control context. The generic projector does no P7 prompt parsing. Current task authority and cancellation/budget remain host-owned.

## Validation and scope

Focused tests cover generic non-ARC memory replacement, immutable history, stale/corrupt/scope rejection and atomic adoption; P7 notes acceptance across level/RESET/kernel calibration and retained action guards; TS complete sibling-tool groups, missing/ambiguous anchors, refresh/recovery after compaction, unchanged raw history, forged stdout rejection, and a non-ARC checkpoint fixture. An actual installed Pi provider-free probe verifies the real context event, not just mocked callbacks.

Run TypeScript extension tests, affected Python unittest suites, then `make promotion-check`, in that order. Sync and verify the packaged extension. Finally run one finite `make asterion-prime-p7-level-witness GAME=r11l LEVEL=1` with an isolated operator root, model gpt-6.1-sol/high and existing900-second witness bound to verify wheel/extension/tool/NOTES integration. Record actual outcome and cleanup; do not infer six-level performance or start a new90-minute benchmark. Never stop the pre-existing user console.
