# Autonomous research interface implementation review

This package responds to the [failed NOTES BP35 comparison](2026-10-08-p7-notes-bp35-comparison.md). Implementation and deployment checks do not establish BP35 L5/L6 capability. The original implementation/deployment boundary below did not include a new BP35 trial. A subsequent user-authorized [BP35 comparison](2026-10-08-p7-autonomous-bp35-comparison.md) ended2levels/166committed with diagnostic stderr overflow; consult that report for current capability evidence.

## Changes and reasons

| Layer | Change | Evidence-driven purpose |
| --- | --- | --- |
| Generic Prime | Capacity-triggered model-view projection over complete interactions; notes update and history retention are independent | Preserve recent observations and counterexamples instead of erasing history after each note |
| Generic Prime | Shared absolute monotonic/wall deadline, sticky expiry | Stop on resumption after a suspend-like wall jump without renewing task authority |
| P7 application | Optional NOTES/WorldMap, predictions and action metadata; no coordinate/no-effect novelty admission gates in modern autonomous profile | Let the actor choose its research method and next useful action |
| P7 evidence | Discoverable read-only frame/render/geometry/diff helpers over exact observed pixels | Remove avoidable interface discovery and manual compressed-grid reconstruction |
| P7 execution | Durable pending/reply/commit record, final SDK admission check and fixed evidence-settlement ceiling | Preserve possible effects across interruption and avoid redispatching unknown outcomes |

The existing runner and three registered tools remain the execution path. Historical learner profiles retain their prior rules. Certified replay retains strict witnesses. An absent prediction is recorded as unasserted execution, never a successful prediction. Notes remain model-authored knowledge, not certified truth.

## Context accounting boundary

The 96 KiB trigger and 48 KiB retention target measure model-bearing history JSON, not provider tokens. At most eight recent complete units are selected after a trim, with at least the newest two, pending siblings and genuine user/system instructions protected. The trusted current-state snapshot is separately bounded to128KiB. Protected content can exceed the target and is reported as over-budget. Raw evidence remains intact.

Projection becomes active after the first trusted application tool result. An IPython-only prefix before that result is not covered by this capacity policy. Notes size, projected JSON bytes and billed tokens are distinct quantities.

## Execution boundary

The shared task budget never renews on continuation, RESET or kernel recovery. Guest timing origins are minted in the guest process and removed from model/provider environment. The adapter rechecks admission after journal I/O immediately before SDK entry. User-space checks and external calls are not physically atomic; sleeping hosts cannot execute timers. An already-entered call can return late.

Evidence may settle only up to the original deadline plus180seconds. This does not grant another model/gameplay interval. Separate verification replays are bounded by the same fixed settlement ceiling. Pending records do not authorize retry; initialization refuses an unresolved journal before SDK creation/reset. This is a small sequential effect record, not a general restart/exactly-once service. Minimal terminal status precedes optional rich finalization. Both finite witness and autonomy presets accept the same operator-owned, exact validated research-worker executable. Raw reply metadata preserves integer-valued enum names as well as string states.

## Verification

- Changed-code review: READY, no unresolved blockers. Corrected pending-outcome classification, definitely-not-dispatched suffix retention, and authoritative v2 refresh after a lost note acknowledgement. An apparent read-wrapper exception gap was disproved by exception inheritance and an actual-runtime regression; no redundant catch was added.
- `npm --prefix packages/typescript/asterion-prime-extension test`:48 passed,6 existing external witness skips.
- `npm --prefix packages/typescript/asterion-prime-extension run test:installed-pi`:PASS,0 provider calls. Actual registered tools validate a minimal plan and accept trusted state before NOTES. Fixture history171757bytes becomes42463bytes;59 raw messages stay intact while15 model messages preserve corrections, complete sibling groups, system/tools and restart behavior.
- Final focused Python suite:343 tests,342 passed and1 existing skip. Includes real computation-module import, direct unpredicted action, readable pending-effect state, clocks, durable late replies, existing solver/broker/history and operator integration.
- Targeted Ruff and `git diff --check`:PASS.
- First `make promotion-check`:FAILED (4318tests,2failures/1error/4skips). The installed-official error was an obsolete fixture requiring NOTES admission; its updated standalone installed test passes while retaining actual actions and evidence assertions. Other failure headings were truncated by the verification logger and did not recur in the next full run; no specific cause is claimed for them. Second full promotion:PASS25commands/provider_operations=0/full_dataset=no. Final-source `6ca76ca4` promotion also PASS25commands/provider_operations=0/full_dataset=no (`promotion-deployment.log`). The first isolated packaged r11l L1 launch was cancelled by a private installation-observer error before any committed action. The corrected observer passed a provider-free probe and independent review; the replacement witness below completed successfully.

Private logs and independent review: `.asterion-private/p7-autonomous-interface-20261008/`.

## Deployment attempt boundary

The preserved first launch (`p7-live-20261008023619-5cb327a1be074acda9448da1`) ended after6.836seconds. Its observer incorrectly inferred the installed package location from a temporary uv interpreter path and cancelled the actor. There were0committed actions,0NOTES updates and0reported usage entries; a provider request may already have started, so this is not a provider-free claim or a solving failure. Wheel source/bundle identity and eventual owned cleanup passed; installed runtime identity, replay and sealed trace did not. The user console was preserved. The failed receipt remains in the private `witness/` directory. Production code stays frozen; only the private observer was repaired for a replacement bounded validation. The repair locates the imported distribution through package metadata and the actual module path rather than interpreter-prefix arithmetic. A provider-free isolated probe verified582 installed wheel files, bundle and registry; independent review passed. Discovery unavailability/timeout is recorded without cancelling the actor; affirmative identity mismatch still stops the check.

## Packaged r11l L1 result

The replacement run `p7-live-20261008030719-27774d8b3ee84492aa4cfc47` used frozen production `6ca76ca4` (base `959fcb0c`), `gpt-6.1-sol` / high thinking, seed0, target L1 and the existing900-second small-witness preset. It started from an empty isolated operator root. No outside solution hints or production changes occurred during the run.

| Measured item | Result |
| --- | --- |
| Completed levels | 1; requested L1 completed, not full r11l |
| Paid actions / committed transactions | 3 / 3; all ACTION6 |
| Actor paid RESETs | 0; SDK recording separately contains2 initialization RESETs |
| NOTES updates | 0; first action and completion did not require NOTES |
| Actual computation/readers | 2 successful IPython cells; first imports p7_research and uses geometry/render, second frame/current/history; diff not observed |
| Wall / monotonic duration | 64.865209s / 64.864921s, host Make start through completion |
| Reported model usage | 6 entries; normalized input sum158796, output1424, single-request input peak42058 |
| Terminal status | closed, level-completed, deadline_expired=false; committed3, potential_effects3, unresolved=false |
| Replay and sealed trace | Both verified |
| Installation | 582 installed wheel files match;564 production source files unchanged; autonomous profile and selected three-tool registry verified |
| Cleanup | Owned processes/unit/cgroup gone; temporary auth and environment removed; user console52024/56659 retained |

`potential_effects=3` includes the three committed actions; it does not mean three unknown effects. Reported normalized input is not unique context size or an uncached-token cost estimate. The42058-token peak cannot be compared directly with the48KiB JSON retention target. This short witness does not independently measure long-run projection behavior; the installed-Pi provider-free probe covers that contract.

Wheel SHA256: `e9440b89eefb5f2f8c927200bbc7efe56a2e5b56924dafdec3cd020a845f101c`. Bundled extension SHA256: `b93dc05d92e039b55de77db4bd5c1276f7a46c8f0524203c42a22cb23ef15d3a`. Pi overwrites its process title, so actual original argv and a full live model-context transcript were not observed. Tool/model/profile evidence combines exact installed source/resource/registry identity, selected operator configuration, actual Node identity and successful tool/action execution; it is not a transcript claim.

Host Make starts2026-10-08T03:12:34.064780Z and has a fixed deadline03:27:34.064775Z. The guest independently mints its paired task clocks at startup and keeps one consistent scope through all three journal transactions. The exact L1-passing SDK response is03:13:33.557200Z; guest deadline is03:27:36.450933Z. The run ended before either deadline, so it does not exercise live expiry or late-result settlement. Clock-jump and late-result behavior remain test evidence.

Private result and receipts: `.asterion-private/p7-autonomous-interface-20261008/witness-replacement/public-final-metadata.json`, `installed-runtime-identity.json`, `frozen-source.json`, `reader-and-reset-metadata.json`, `action-clocks.json`, and the associated trace/journal/cleanup artifacts. `evidence-sha256.json` indexes74 final private artifacts. The separate certified replay also has two initialization RESETs and three ACTION6 actions; replay verification is not folded into paid solving actions. The first failed observer attempt remains separately preserved in `witness/`.

Independent final scalar audit passed: committed trace and five complete SDK rows align (two initialization RESETs plus three ACTION6 actions), with no unresolved effect. The implementation and small packaged deployment are verified within these boundaries. At this deployment checkpoint BP35 had not yet been rerun. The subsequent comparison linked above failed its six-level target; improved long-range reasoning, action efficiency and L5/L6 autonomous completion remain unverified. A later comparison should retain per-level paid actions/RESETs, useful recent evidence, model-authored understanding, request usage and clock data rather than judging by NOTES size alone.
