# Prime state view and P7 action preconditions

User authorizes design, implementation and one cold BP35 verification after Task23, preserving three layers and autonomous reasoning. This design stays within that scope.

## Evidence and alternatives

Task23 retains all native history while latest snapshot repeats prompt/current board; 56 plan-end boards total170,860 UTF-8 bytes (observation envelopes206,570), early history35,920→215,809 bytes. Full request decomposition is unavailable. L5 seq149 shows wall5 at click coordinates51,39 and45,39; after the prerequisite ascent/camera change they contain14. Data is exact; the actor misapplied its map. L2 unknown lethal motion remains an epistemic boundary, not a proven host bug.

Alternative A: more prose or another pixel reader duplicates existing render/frame and supplies no execution guarantee. Alternative B: mandatory model certificates/safety rules would prescribe cognition or leak game knowledge. Selected C: generic lossless evidence archival with bounded stale-state model views, plus optional literal preconditions in the domain action adapter. Retain all actor reasoning and actual feedback.

## Prime generic layer

A trusted application method result may supply a closed proposal `tool_state_view={version:"asterion.prime-tool-state-view/v1",state_key,replacement_text}`. Extension strips the proposal before forming final model-visible text, then admits a closed native-details envelope containing those three fields plus `original_text_sha256`, `tool_call_id` and `tool_name`. Hashing at this edge binds the actual text and avoids Python/JavaScript JSON formatting differences. The key is bounded to1024 UTF-8 bytes; original/replacement text to128KiB, with replacement strictly smaller. P7 keys include run/attempt identity; generic projection further scopes keys by native tool name. Model-context projection replaces only older matching successful tool results for that key; newest visible result stays complete. Validate exact original text hash and unique current-branch native tool-call/result pairing; malformed/unknown metadata, errors, unpaired/ambiguous identities or uncertain effects leave original content unchanged. Never mutate session messages or archived results. Replacement cannot execute, authorize or conceal an uncertain effect. Preserve all assistant/user messages, tool names/IDs/errors and result order. No dependency on P7 fields in this generic module.

## P7 data layer

Only successful execute_plan result observation frame/animation state is marked replaceable. Archived view keeps observation identity/state/levels and explicit readback hints via r.frame(sequence) and r.animation(observation_ref); all feedback, predictions, costs, stop reason and unexecuted steps stay intact. Latest full state remains available through native latest response and current snapshot. Do not replace code, stdout, raw experiments, NOTES or model hypotheses. No renderer semantics, guessed camera offset or dangerous color table.

## P7 research/action layer

Optional step.before={cells:[{x,y,value}]} asserts1..128 distinct literal current screen pixels, using existing pixel validation. Whole plan validates before dispatch. Immediately before each step, compare against the actual settled observation. A mismatch returns explicit precondition feedback/reference/differences, stops suffix regardless of stop_on_mismatch, adds no action or bill, and leaves the failed step unexecuted. Executed prefix remains counted. Exact plan_id repeat returns the cached result; changed before under sameID rejects. Existing unknown-effect, cancellation, deadline, level/RESET termination and post-expect semantics remain. No-before behavior unchanged. A matched before is not a prediction of future safety.

Prompt and registered schema document optional before and current screen/model-coordinate distinction without BP35 specifics. No mandatory notes, model, BFS or guard.

## Verification and acceptance

Meaningful RED/GREEN tests for state-view replacement/immutable archive/hash mismatch/pairing/latest preservation and P7 pre-dispatch/prefix/whole-plan validation/idempotence/post-policy. Independent code review covers trust boundaries and layer ownership. Rebuild extension resource; TS tests, related Python tests, lint/docs/promotion, then packaged r11lL1 witness under existing deployment contract. After cleanup, freeze source and run one cold BP35 L1–L6 under current.env Solmedium, original5400+180,6round/1000paid/1024model/4096tool. No old notes/routes, outside hints or midrun edits. Capture bounded neutral Pi event receive clocks (not HTTP clocks), compare each level action/time/quality/RESET and mechanism to Task23 and17minute best. Full replay/install/seal/cleanup audit required. Passing unit tests means contract verified, not model adoption or zero death; single trial does not prove causal/stable improvement.

## Task24 interruption revision — explicit budget scope

The user authorized stopping Task24, investigating the regression, fixing supported deficiencies and repeating a cold verification. The observed first two levels cost 36 and 108 actions; the latter includes an additional 64-action failed attempt and 17 undo actions. These observations do not establish a state-view regression: Task24's first paid action already differs from Task23 before any older action result can be replaced. The full-game objective, baseline array and cumulative scoring formula were present and unchanged. Raw historical reads continued to work. Task24's own compact renderer omitted the bottom row, although its earlier diff output had exposed changes there; its first NOTES update occurred after the costly loop. Neither renderer omission nor late notes constitutes a host data-loss bug or justifies mandatory notes.

The supported information-contract gap is scope ambiguity. The current flat `budget` exposes host-run authorization controls and cumulative level scoring costs together, without explicitly stating that host actions remaining are not a reading of resources inside the game. The current adapter does not expose a structured environment resource limit or balance. This is a claim about this adapter, not a claim that every SDK lacks such fields. Host journal costs do not roll back when a game action restores an earlier board. Whether any game-internal resource is restored remains an empirical question for the actor.

### Minimal additive contract

Add one closed, application-owned `budget.scope` object from `Solver._budget()`:

```json
{
  "execution_controls": "host-run",
  "scoring_costs": "level-cumulative-including-resets",
  "state_restore_refunds_paid_actions": false,
  "environment_resources": "not-reported-by-adapter"
}
```

These four keys and values are fixed for the current adapter. `execution_controls` describes `action_cap`, `actions_remaining`, `primitive_actions` and the wall-clock controls. `scoring_costs` describes the paid action counts in `budget.scoring`; the existing explicit exception for initialization RESET remains. The non-refund flag concerns already charged host and scoring actions only. The environment-resource value means unavailable structured information, not unlimited resources and not a value of zero. Do not synthesize an environment limit, remaining count, HUD interpretation, episode deadline or automatic reset policy. Keep all existing budget fields and numerical accounting unchanged; no new counters, protocol schemas, tools or execution authority are introduced.

The P7 research prompt may explain this scope in one short paragraph: host-run action/time allowances are distinct from any limits represented by the game; undo or restoration does not refund already charged host/scoring actions; environment resource changes must be inferred from actual observations. It must not name an action number as UNDO, provide a game-specific resource threshold, assert that all games have a timer, prescribe a HUD location or require a particular analysis workflow. Continue to allow optional before/expect and independent model research.

Prime generic state views, cell archives and context memory remain unchanged. They preserve code, outputs and notes; replacing the current NOTES snapshot does not remove accumulated cell outputs. No runtime-semantic meaning is assigned to those outputs. P7 data continues to supply complete current pixels and exact historical reads; the scope object distinguishes known accounting facts from an unreported environment quantity. P7 research remains responsible for selecting abstractions and retaining resource observations relevant to its hypotheses.

### Compatibility and bounded verification

The addition belongs to the P7 application context, outside the closed generic runtime/capability/assembly manifests. Actor projection and trusted memory copy `budget` without a fixed nested field schema; existing UI consumers read their named numerical fields. The current TypeScript action schema accepts plans and does not validate the returned budget object. The runtime integration test `test_initial_actor_v2_snapshot_and_continuation_deliver_score_facts` derives its expected budget from `current_context()`, so extend it to assert the exact scope object across initial, actor, memory and continuation surfaces rather than weakening its key comparison. Also verify execution feedback preserves the same scope.

Use a small existing accounting fixture to demonstrate that an executed action followed by a paid RESET retains prior cumulative costs, while a rejected before guard adds no charge. Assert that the new field is a fresh value on each context read, leaves existing numerical fields unchanged and supplies no inferred environment balance. Prompt checks should cover the scope distinction and absence of a game-specific threshold. No additional benchmark or exhaustive test matrix is required for this metadata change; complete the normal packaged-resource/deployment checks applicable to the resulting files.

### Restart interpretation

Freeze one new cold trial with only the budget-scope addition and its matching explanation changed from 687c6fac; retain model/effort, source-view behavior, optional guards, game/seed, target, tools and finite execution controls. Do not copy the failed run's notes, route, model program, resource threshold or external diagnosis into actor context. Observe per-level total and successful-attempt actions, resets, undo/restore action use, time, resource-related research evidence and the actual scope delivery. Record state-view adoption only within the bounded diagnostic evidence available. Fewer actions would be an observed outcome, not proof that this wording caused the improvement; repeated loops would falsify a claim that the scope clarification alone resolves them. This fixes a narrow information contract and does not establish the root cause of the actor's strategy regression or guarantee lower action cost.
