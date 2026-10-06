# Live Session Checkpoint

Updated 2026-10-06 09:24 CST. Active session, not a handoff. Branch main. Console remains http://127.0.0.1:57515/; verify owned PID from `launches/p7-controller-server.json`. Saved local results at09:23: **8/25 full games,75/183 levels,2725 saved-route actions,38.860606 local score**. Observed unsealed progress is separate. Latest official submission remains29.834632,7full/54levels/1883actions; no third card is authorized.

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
| M0R0 | 2/6, 38 | `p7-live-20261006090944-d9964e50892e4b60a3586aa1` |
| SP80 | 6/6, 143 | `p7-live-20261006001222-3a7662493aa44f01b109e5f9` |
| VC33 | 7/7, 176 | `p7-live-20261005194027-dc14efb28c722e59760af7b3` |

- Table sources have sealed trace, independent replay, model scope and cleanup. DC22 is a separate offline recovery; VC33 contains explicit offline composition. These do not certify original failed model runtime settlement.
- Latest exact API evidence: `launches/prepared-replay-final-overview.json`. Do not replace saved75 with observed77; pending observations cannot authorize resume or scoring.
- First official card: https://arcprize.org/scorecards/fb5ae449-b935-498f-a1e6-5b31c1633056,12.00,25attempted/3full/19levels/793actions. Second card: https://arcprize.org/scorecards/749fd876-37e4-42aa-9dc8-fdb9511b0f4a,29.834632034632037,25played/0skipped/7full/54levels/1883actions. Receipt `.asterion-private/prime-p7-official/p7-live-20261005233854-92dc94d61c3738ded960a712/official-receipt.json`. Both finite submissions complete. Subsequent local progress does not update either receipt.
- LF52L7 original `p7-live-20261006084206-3f0eaf6cffb0461db7aa0ac4`:491actions,observed7levels but no summary/seal/trusted terminal. Independent zero-model SDK audit verified all491 actions/492 observations and unchanged original hashes (`launches/lf52-l7-independent-sdk-audit.json`). This audit does **not** create reusable recovery authority; saved6/345 remains. Keep game held until a separately designed trusted recovery contract exists.
- LS20L7 `p7-live-20261006085758-24161d22a51c4f95b3f6b604`: trace unavailable finalization, guest stopped, no summary/seal; saved6/374 remains. Parent quarantines the game while preserving the independently running other guest. Read live private campaign state for exact units/PIDs/deadlines rather than trusting prior checkpoint PIDs.

## 当前判断 / 下一动作

1. User superseded cache-only warming: parse during saved-route export and persist immutable manifest/per-level public projections. New prepared files publish current pointer last, validate exact source/projector revision, size/hash/public shape, and do not confer score/execution authority. Fresh server reads prepared manifest and selected level directly. Active/legacy/invalid sources use bounded background fallback with visible loading/retry.
2. Frontend clears old board/cognition immediately, requests manifest then selected level only, and fences exact game/run/seed/best/revision/selection generation. A shared-promise race that rejected legal saved routes during idle polling is fixed using captured immutable request authority plus fresh apply-time checks. Final DOM105PASS/0FAIL/1environment real-HTML skip (`launches/prepared-replay-dom-fixed.log`); later real HTML check is separate. Astra final review had no blocker in that boundary.
3. Durable SP80 witness forbids raw builder on a fresh reader: manifest16.7ms/level1 42.4ms (`launches/game-switch-prepared-sp80-witness.json`). Actual served HTML/API+DOM switch825ms/revisit445ms, selected-level requests only (`launches/progressive-replay-http.json`, `prepared-replay-http.log`). These are different boundaries; no Chrome visual acceptance claimed. Existing Chrome connector times out; no alternate browser profile was created.
4. Existing best-source backfill is still being completed. Initial BP35 exposed original-vs-restored event sequence validation mismatch; backend fixes this common provenance contract without changing emitted cognition. Root is integrating final code, named focused checks, promotion and main commit. Do not claim complete until all current best sources have valid prepared artifacts and actual served checks pass.
5. Keep fixed replay aliases `replays/<alias>.html` current; backfill must not change original traces, scores or source selection. Upgrade only campaign parent/export package after final clean committed wheel proof, preserving active guest units and original deadlines. Solving stays on clean pinned7a until that adoption.
6. Current finite campaign was running M0R0L3 when LS20 finalization failed; root announced replacement **R11L L1** paired with M0R0. Astra owns private quarantine/adoption only, not public recovery contracts. Before spawning anything inspect `launches/parallel-campaign-state.json`, actual `orb ... systemctl list-units`, and parent process. Never exceed two guests.

## 历史归档

- The old checkpoint07:50, LF52 only2/10, LP85 4/8 and LS20 2/7 is superseded. Earlier promotion25PASS/provider0 snapshots do not certify later prepared-source edits.
- Full-game900second timers, chronological latest-attempt default and per-game cognition patches caused regressions and are superseded by exact saved-source authority, per-level timers and generic provenance.
- Cache-only prewarming reduced warm loading but left first-use parse slow; save-time prepared projection is the chosen design. In-memory retention is only a bounded fallback/display optimization.
- Blue partial status was replaced by pink at223df120; full saved completion stays green, zero gray, unverified amber, activity orange. Neither activity nor color promotes evidence.

## 未完成边界

- Local8full/75saved does not complete25games or establish private-test generalization. Unsealed SDK-observed progress is not a saved route.
- Experience loaded/read is not guaranteed improvement or executable program recovery. Missing trusted terminal/seal requires an explicit recovery design; do not synthesize credentials or success receipts.
- Final durable backfill, latest package proof and parent export upgrade remain pending at this checkpoint. HTTP/DOM is verified where named; Chrome visual acceptance remains external-limited.
