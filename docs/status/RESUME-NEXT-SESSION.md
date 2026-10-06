# Live Session Checkpoint

Updated 2026-10-06 09:32 CST. Active session, not a handoff. Branch main. Console remains http://127.0.0.1:57515/; verify owned PID from `launches/p7-controller-server.json`. Saved local results at09:31: **8/25 full games,79/183 levels,2815 saved-route actions,40.765368 local score**. Observed unsealed progress is separate. Latest official submission remains29.834632,7full/54levels/1883actions; no third card is authorized.

## 已验证事实

- Canonical worklist/spec: `docs/superpowers/plans/2026-10-05-p7-worldmap-solver-redesign.md` and matching spec. Prime owns persistent IPython/model continuation; P7 owns WorldMap, evidence and short plans. Registered tools remain `ipython`, `p7_workspace`, `p7_execute_plan`.
- Authorized campaign: at most two distinct independent games,900seconds **per level attempt**, two genuine unfinished attempts at one blocked level then switch. Announce each new game before launch. Infrastructure faults preserve evidence and quarantine that game; they do not count as reasoning failures.
- Efficiency: actions>=baseline AND level score<115 queues one redo when the game is free. Equal baseline gives100; score=min(115,100*(baseline/actions)^2). Target-only restoration and SDK composition preserve later saved levels. Only a strictly better route replaces authority.
- Saved route alone determines saved scores/counts. Original failed attempts and recovery records remain separate. VC33L1=3; DC22L6=159. Do not rerun either merely to refresh display. BP35L2=40 and later saved levels persist. BP35L6/CD82L1/G50TL3 reached two genuine unfinished attempts and remain skipped in this campaign.

| Game | Saved levels/actions | Authoritative source |
|---|---|---|
| AR25 | 8/8, 258 | `p7-live-20261006043256-6964b205e0594ec58af4fb24` |
| BP35 | 5/9, 150 | `p7-live-20261006044823-71c100a92af04fe2b474bac7` |
| CN04 | 6/6, 186 | `p7-live-20261006060831-921fdc8fc1b140b1b19fde00` |
| DC22 | 6/6, 474 | `p7-live-20261005190338-478eb1c2a4011d0600897097` |
| FT09 | 6/6, 75 | `p7-live-20261006055733-ec244b3b50484023a74085de` |
| G50T | 2/7, 63 | `p7-live-20261006060637-1bf8d2618aff4766831143de` |
| KA59 | 7/7, 350 | `p7-live-20261006064538-1760635dd5aa46bb98a05745` |
| LF52 | 6/10, 345 | `p7-live-20261006082328-7c1981e0f1f04d408a53a09f` |
| LP85 | 8/8, 93 | `p7-live-20261006080754-3fbd0c18c5294c7d998bd1f7` |
| LS20 | 6/7, 374 | `p7-live-20261006084415-fe1bd5b9f2494dbeb7db71af` |
| M0R0 | 4/6, 114 | `p7-live-20261006092445-faec185afb9e4ceea3f9d7f4` |
| R11L | 2/6, 14 | `p7-live-20261006092715-dcea6fb50d6f436384426fac` |
| SP80 | 6/6, 143 | `p7-live-20261006001222-3a7662493aa44f01b109e5f9` |
| VC33 | 7/7, 176 | `p7-live-20261005194027-dc14efb28c722e59760af7b3` |

- Table sources have sealed trace, independent replay, model scope and cleanup. DC22 is a separate offline recovery; VC33 contains explicit offline composition. These do not certify original failed model runtime settlement.
- Latest exact API evidence: `launches/prepared-replay-final-overview.json`. Do not replace saved79 with observed80; pending observations cannot authorize resume or scoring.
- First official card: https://arcprize.org/scorecards/fb5ae449-b935-498f-a1e6-5b31c1633056,12.00,25attempted/3full/19levels/793actions. Second card: https://arcprize.org/scorecards/749fd876-37e4-42aa-9dc8-fdb9511b0f4a,29.834632034632037,25played/0skipped/7full/54levels/1883actions. Receipt `.asterion-private/prime-p7-official/p7-live-20261005233854-92dc94d61c3738ded960a712/official-receipt.json`. Both finite submissions complete. Subsequent local progress does not update either receipt.
- LF52L7 original `p7-live-20261006084206-3f0eaf6cffb0461db7aa0ac4`:491actions,observed7levels but no summary/seal/trusted terminal. Independent zero-model SDK audit verified all491 actions/492 observations and unchanged original hashes (`launches/lf52-l7-independent-sdk-audit.json`). This audit does **not** create reusable recovery authority; saved6/345 remains. Keep game held until a separately designed trusted recovery contract exists.
- LS20L7 `p7-live-20261006085758-24161d22a51c4f95b3f6b604`: trace unavailable finalization, guest stopped, no summary/seal; saved6/374 remains. Parent quarantines the game while preserving the independently running other guest. Read live private campaign state for exact units/PIDs/deadlines rather than trusting prior checkpoint PIDs.

## 当前判断 / 下一动作

1. User superseded cache-only warming: parse during saved-route export and persist immutable manifest/per-level public projections. New prepared files publish current pointer last, validate exact source/projector revision, size/hash/public shape, and do not confer score/execution authority. Fresh server reads prepared manifest and selected level directly. Active/legacy/invalid sources use bounded background fallback with visible loading/retry.
2. Frontend clears old board/cognition immediately, requests manifest then selected level only, and fences exact game/run/seed/best/revision/selection generation. A shared-promise race that rejected legal saved routes during idle polling is fixed using captured immutable request authority plus fresh apply-time checks. Core DOM105PASS/0FAIL/1environment real-HTML skip; final saved-default/loader follow-up DOM106PASS/0FAIL/1skip (`launches/prepared-saved-default-dom-final.log`); real exported HTML separately1PASS/0skip. Astra final review had no blocker in that boundary.
3. Durable SP80 witness forbids raw builder on a fresh reader: manifest16.7ms/level1 42.4ms (`launches/game-switch-prepared-sp80-witness.json`). Actual served HTML/API+DOM switch825ms/revisit445ms, selected-level requests only (`launches/progressive-replay-http.json`, `prepared-replay-http.log`). These are different boundaries; no Chrome visual acceptance claimed. Existing Chrome connector times out; no alternate browser profile was created.
4. Core committed41f02b61; latest core full `make promotion-check` PASS25/provider_operations0/full_datasetno (`launches/prepared-replay-final-promotion.log`). Backend160PASS; real exported HTML1PASS/0skips. Existing14 saved games prepared; actual HTTP every78 saved levels/counts/cognition PASS (`launches/prepared-saved-roster-http.json`). Further newly saved sources use prepared export. Source-default/loading-slot UI follow-up is outside that frozen full-promotion snapshot; final DOM106PASS/1skip and actual served source/CSS checks passed, with final wheel resource proof separate. BP35 original-vs-restored sequence validation is fixed without changing emitted cognition.
5. Keep fixed replay aliases `replays/<alias>.html` current; derivatives never change original traces/scores/source authority. Parent29704 uses clean pinned41f02b61/wheel8ef87828e480060519cb3b388e9afbc108144c5df3ec708f747a3e7592e4e7d5,14 module/resource hashes verified. Existing guest units continue7a with unchanged Make PIDs/deadlines. Evidence `launches/pinned-41f02b61-{deployment,adoption-proof,adoption-preflight}.json`. Final UI wheel adoption remains pending after its commit; never cancel guests merely to update console.
6. Current confirmed active pool at09:31 is **M0R0L5 + R11LL3**, parent29704 HOLD=false; LF52/LS20 held. Root announced R11LL1 before launch. Read `launches/parallel-campaign-state.json`, actual guest units and parent before dispatch, never exceed two. Source-default fix selects confirmed current then exact verified best, otherwise real initial preview. Recording-only files do not prove a live guest; explicit 尝试 preserves latest attempt and pin. Actual served LS20/LF52 switched to saved sources146/175ms with no requests to stopped unsealed source (`launches/prepared-replay-default-sources-http.json`). Stable40px+8px loader slot prevents visibility/retry changing layout; offline/legacy omit it.

## 历史归档

- The old checkpoint07:50, LF52 only2/10, LP85 4/8 and LS20 2/7 is superseded. Earlier promotion25PASS/provider0 snapshots do not certify later prepared-source edits.
- Full-game900second timers, chronological latest-attempt default and per-game cognition patches caused regressions and are superseded by exact saved-source authority, per-level timers and generic provenance.
- Cache-only prewarming reduced warm loading but left first-use parse slow; save-time prepared projection is the chosen design. In-memory retention is only a bounded fallback/display optimization.
- Blue partial status was replaced by pink at223df120; full saved completion stays green, zero gray, unverified amber, activity orange. Neither activity nor color promotes evidence.

## 未完成边界

- Local8full/75saved does not complete25games or establish private-test generalization. Unsealed SDK-observed progress is not a saved route.
- Experience loaded/read is not guaranteed improvement or executable program recovery. Missing trusted terminal/seal requires an explicit recovery design; do not synthesize credentials or success receipts.
- Prepared core/backfill/provider-free promotion and parent export upgrade are verified where named. Final UI follow-up commit/resource proof remains pending at this checkpoint. Explicit unsealed-attempt inspection still uses bounded projection and may fail; it does not blank the default saved view. Chrome visual acceptance remains external-limited.
