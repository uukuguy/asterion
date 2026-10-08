# Autonomous research interface implementation review

This package responds to the [failed NOTES BP35 comparison](2026-10-08-p7-notes-bp35-comparison.md). Implementation and deployment checks do not establish BP35 L5/L6 capability. No new BP35 trial is part of this package.

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
- First `make promotion-check`:FAILED (4318tests,2failures/1error/4skips). The installed-official error was an obsolete fixture requiring NOTES admission; its updated standalone installed test passes while retaining actual actions and evidence assertions. Other failure headings were truncated by the verification logger and did not recur in the next full run; no specific cause is claimed for them. Second full promotion:PASS25commands/provider_operations=0/full_dataset=no. Final-source `6ca76ca4` promotion also PASS25commands/provider_operations=0/full_dataset=no (`promotion-deployment.log`). The first isolated packaged r11l L1 launch was cancelled by a private installation-observer error before any committed action. Deployment remains unverified; a corrected observer and replacement witness are being prepared.

Private logs and independent review: `.asterion-private/p7-autonomous-interface-20261008/`.

## Deployment attempt boundary

The first launch (`p7-live-20261008023619-5cb327a1be074acda9448da1`) ended after6.836seconds. Its observer incorrectly inferred the installed package location from a temporary uv interpreter path and cancelled the actor. There were0committed actions,0NOTES updates and0reported usage entries; a provider request may already have started, so this is not a provider-free claim or a solving failure. Wheel source/bundle identity and eventual owned cleanup passed; installed runtime identity, replay and sealed trace did not. The user console was preserved. The failed receipt remains in the private `witness/` directory. Production code stays frozen; only the private observer is being repaired for a replacement bounded validation.
