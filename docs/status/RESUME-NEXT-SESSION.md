# Live Session Checkpoint

Updated 2026-10-06 05:06 CST. Active session, not a handoff. Branch `main`. Latest backend commits `3bfe0c3d` (offline-source cognition) and `72c60d94` (acknowledged interruption). Per-level console source-map changes passed independent review and98 DOM tests; packaged and actual integration checks remain pending. Background dispatch is held with no active guest while the new package is committed; resume BP35 L6 and CD82 L1 afterward. Console remains http://127.0.0.1:57515/; read actual owned-server metadata before reload.

## 已验证事实

- Canonical worklist/design: `docs/superpowers/plans/2026-10-05-p7-worldmap-solver-redesign.md` and matching spec. Prime owns persistent IPython/model continuation; P7 owns WorldMap, evidence and short plans. Registered tools are `ipython`, `p7_workspace`, `p7_execute_plan`.
- User authorizes the local25-game campaign with at most two independent games and900seconds PER LEVEL ATTEMPT. Two genuine unfinished attempts at a blocked level switch games; infrastructure faults HOLD/repair. Announce newly started games by ID, start level and concurrent partner.
- Efficiency policy: actual actions >= canonical baseline AND per-level score <115 queues one retry immediately when the same game is free. Equal baseline gives100. Target-only restoration and SDK replay preserve later saved levels without paid model re-solving. Admit only a strictly better result. Per-level score is min(115,100*(baseline/actions)^2); weighted game score separately caps100.
- Saved route is the score/action authority; current attempts are diagnostic/live observations. Count saved game actions separately from all attempted/repeated/restoration actions. No baseline overrides or per-game display patches.

| Game | Saved levels/actions | Per-level actions | Authoritative source |
|---|---|---|---|
| SP80 | 6/6,143 | 7/9/14/37/28/48 | `p7-live-20261006001222-3a7662493aa44f01b109e5f9` |
| DC22 | 6/6,474 | 34/45/46/66/124/159 | `p7-live-20261005190338-478eb1c2a4011d0600897097` |
| VC33 | 7/7,176 | 3/8/23/21/46/22/53 | `p7-live-20261005194027-dc14efb28c722e59760af7b3` |
| AR25 | 8/8,258 | 17/13/40/22/29/53/37/47 | `p7-live-20261006043256-6964b205e0594ec58af4fb24` |
| BP35 | 5/9,150 | 19/40/34/25/32 | `p7-live-20261006044823-71c100a92af04fe2b474bac7` |

- All saved sources above have sealed trace, independent replay and cleanup. DC22 is a separate zero-model offline recovery of actual SDK WIN after the original model runtime failed; VC33 is a zero-model composition preserving older later actions. Neither changes the original failed runtime evidence.
- BP35 L2 retry `p7-live-20261006044159-900201c67ab64328a8286b4a` passed40 new actions,115points. Offline partial composition `p7-live-20261005204718-5cf8fa5b7b0ce83073f20e1f` preserved L3/L4 and saved4/9 at118=[19,40,34,25], with zero model calls. Subsequent L5 passed32/baseline33, saved5/9 at150. L5 does not qualify under the current actions>=baseline policy. Next L6 restores150 actions and has87 new-action budget.
- Shared restored-cognition validation now admits offline composed/recovered sources using actual current restoration observations, pinned source provenance and hashes. Actual HTTP BP35 first-four counts19/40/34/25, cognition6/3/2/5; L5 cognition6. DC22/VC33 cognition remains generic shared projection. Evidence `launches/bp35-final-cognition-http.json`.
- Actual API previews CD82 L1/L6, CN04 L3, SP80 L6, BP35 L9 contain real64×64 SDK initial grids with zero actions/completed levels. No model/manual run starts. Missing future-level display is a common frontend source-selection issue, not missing SDK previews. Evidence `launches/console-live-preview-source-proof.json`.
- CD82 L1 first run `p7-live-20261006044209-4f96e8a1afaf42af8c2b50e6` ran about902seconds under a900-second guest bound,29 acknowledged actions,zero completed levels. Cleanup succeeded but the original trace is unsealed because cancellation left broker active. Preserve original files. Independent SDK audit verified all29 before/after hashes and original trace chain with zero model calls; original four file hashes unchanged. Evidence `launches/cd82-interrupted-sdk-audit.json`. Exact-unit systemd evidence confirms runtime-time-limit after900.206874seconds (`launches/cd82-deadline-lifecycle-audit.json`). Private ledger counts one genuine unfinished L1 attempt without changing original trace/ack; original acknowledgment reason remains null. Existing experience loader accepts its integrity-checked unsealed research as advisory29history/6cells, with no resume authority; actual actor consumption on retry remains pending.
- `72c60d94` adds a truthful interrupted failure terminal only for actual trusted ProcessCancellation plus CancelledError with all actions acknowledged and no uncertain result. Unknown action results/ordinary model errors remain fail closed. Failed evidence publishes no success receipt or positive progress. Future verified interrupted attempts can contribute bounded inert failure experience.
- Exactly ONE complete25-game official submission is closed-confirmed: `p7-live-20261005195759-a3c256e549dbadb5019898cd`, card `fb5ae449-b935-498f-a1e6-5b31c1633056`, https://arcprize.org/scorecards/fb5ae449-b935-498f-a1e6-5b31c1633056. Official12.00,25 attempted,3 complete,19/183levels,793actions; SP80/DC22/VC33 each100 game aggregate. Subsequent local progress does not update that receipt. No second submission authorized.

## 当前判断 / 下一动作

1. Commit and deploy the frozen common console source-map: exact best-run authority; each selected level obtains frames/actions/events/cognition from one source; saved fallback preserves later levels during redo; any missing level uses a real initial preview. Fence async best replacement, game switching and polling so playback/cursors do not jump. Sol implemented and Astra reviewed the pending-best cache, implicit source-rebind playback and live-mode preview fixes; all three are covered by the passing DOM checks.
2. Resume only the private single-writer pool after clean main commit: BP35 L6 plus CD82 L1 retry. `/root/parallel_campaign` owns private ledger/audit disposition and exact source adoption; do not launch a second coordinator or retired sequential monitor. Dynamic paths: `.asterion-private/prime-p7-live/launches/remaining22-background.json`, `parallel-campaign-state.json`, `parallel-campaign-live-evidence.json`; script `run-parallel-campaign.py`. Old pool UV25875/Python25879 has exited, guest units inactive/MainPID0. Inspect actual processes before taking ownership.
3. Run actual servedHTML/API+DOM acceptance for all saved games and future-level previews; HTTP/DOM does not establish Chrome visual acceptance. The existing Chrome connector repeatedly times out even after prescribed existing-profile recovery. No isolated profile or hidden browser acceptance.
4. Once source is frozen, run one combined `make promotion-check` for the packaged JS/backend changes. Earlier full gate PASS25 commands is pinned to c45ad79f (`launches/p7-efficiency-promotion.log`), not the new edits. Latest backend integration:127 tests PASS (`launches/interrupted-integration.log`); restored cognition68PASS; partial route/root integration45PASS and actual isolated SDK composition0-model PASS. DOM98PASS/one optional real-export environment skip before final review fixes.
5. Keep fixed replay aliases `.asterion-private/prime-p7-live/replays/<alias>.html` current after saved route admission. Review actual metadata/controller+manual idle before reloading only owned57515 console; never stop guests to reload console. Last owned metadata PID35871, which must be rechecked.

## 历史归档

- DC22 redo was requested before L6 passed; now L6=159/baseline578/115points. Never redo it merely to refresh display. VC33 current L1=3, not the older11-action route. Older full VC33 source `p7-live-20261006025626-cc6636dfc10144408e847d2e` remains historical.
- BP35 older native4/9 route `p7-live-20261006043200-adc04a21c3304a798e4c6e27` has obsolete L2=49. Keep it as source evidence, not latest authority after improved40 admission.
- Whole-game900-second dispatch and waiting for full-game completion before efficiency retry are superseded. Current witnesses target one level and carry restored actions separately; partial saved suffix composition is deployed by `d7e9ef52`.
- Latest-attempt default and lexical opaque run-ID ordering caused old/full results to replace better saved routes. Authority must follow verified scope and best-run evidence, not attempt chronology alone.
- Original post-WIN DC22 Pi RPC failure and unsealed CD82 interruption are not successful native model runs. Separate independent audit/recovery evidence retains these distinctions.

## 未完成边界

- Four full local games plus BP35 partial do not complete25games or establish private-test generalization. The first official submission is complete; local breadth research remains unfinished.
- Experience loaded/read is not guaranteed improvement or executable program restoration. The old audited CD82 run's original trace remains unsealed; bounded advisory loading is verified, while actual actor consumption on the new retry remains pending.
- Final combined promotion and actual source-map integration acceptance remain pending at this checkpoint. Chrome visual acceptance is external-limited.
