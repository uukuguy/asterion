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
