# P7 WorldMap implementation review and verification

Date: 2026-10-05. Scope: approved Prime workspace / P7 solver / console redesign.

## Architecture

Prime owns persistent computation, explicit source/JSON exports and recovery. P7 supplies read-only observation access, versioned WorldMap and host-checked reports; the actor alone submits predictions to the existing Broker. Default runs expose exactly three tools and do not inject historical routes or shared cognition. The existing Prime session owns model continuation; no second runner was added.

## Independent review and corrections

Astra reviewed generic kernel/admission, console, and solver/application wiring. Corrections:

- Python errors remain settled tool results; a repairable cell cannot poison the shared bridge. Kernel loss retains its own status.
- The bridge keeps one event loop for worker startup, all cells and cleanup; no persistent subprocess transport crosses per-cell loops.
- Actor responses retain bounded settled frames, references, budgets and action settlement. Large research and prediction projections explicitly signal omitted detail; authoritative history stays complete.
- Terminal WIN events use the final valid level so the console keeps the final feedback.
- Cleanup executes even when writing control state fails. Actual research-host closure and cell lifecycle drive diagnostics.

Read-only RPC isolation is an application capability boundary, not an OS sandbox for arbitrary Python. Host report checks establish prediction agreement with observations, not a proof of complete model correctness.

## Provider-free evidence

- Generic real-worker workspace: 16 tests. Prime admission/session: 40 tests.
- Console/control: 105 Python tests; shipped-asset DOM suite: 74 tests, zero skips. Actual exported HTML exercised without external requests.
- Runtime integration: real kernel computes predictions, actor publishes, second real Broker action contradicts prediction, suffix stops, WorldMap is revised. Actual socket bridge preserves namespace across a Python error. Explicit checkpoint survives computation loss and requires calibration before action.
- Installed wheel tests: legacy regression explicitly isolated; new default registers three tools and runs real kernel exports, publication and predicted actions through Solver/Broker.
- Per user correction, UI acceptance remains the established background DOM/HTTP/export workflow. An unnecessary Chrome connection attempt timed out; it is not a gate and supplies no verification claim.

Final independent implementation re-review accepted the corrected primary path. A low-probability constructor-failure cleanup tail remains outside the verified normal lifecycle; no broad hardening was added.

Final related Python suite: **365 tests PASS**. `make lint docs-check`: PASS (274 Markdown files, 63 local links).

## Deployment and ability boundary

- Extension final test: 39 total, 33 PASS, 6 external-Pi skips. Generated resource synchronized after source freeze.
- `make promotion-check`: 3957 tests, 15 failures / 5 errors / 4 skips; **not PASS**. The wrapper retained only its tail (existing source-detachment failures). One full Python 3.12 rerun recorded 3957 tests / 12 failures / 4 errors / 4 skips. Two new failures were obsolete core-module inventory and tool allowlist assertions, fixed in `b45977e6` with three targeted checks passing. The other 14 failing cases match historical names and causes. Promotion used Python 3.14; its additional 3 failures / 1 error were not fully reproduced, so the full gate remains non-PASS. No second complete rerun was done.
- Real packaged `make asterion-prime-p7-level-witness GAME=sp80 LEVEL=1`: **PASS**. Run `p7-live-20261005212851-4b7287c4dc5d498db14c16a6`, seed 0, model gpt-6.1-sol, commit `a1aef743`. Fixed existing 900-second cgroup preset; human-baseline action cap 39. Completed Level 1 with **9 actions**, remaining 30; target stop `level-completed`, replay verified, trace sealed, cleanup complete. Exact guest unit is inactive/dead with MainPID 0.
- First live attempt used six actor plans and four workspace focus calls, **zero IPython cells**, no WorldMap publication. `playbook_loaded=false`, `replayed_prefix_actions=0`. This proves a fresh default-path Level 1 completion; it does **not** prove program-model-driven reasoning or cross-level transfer. No old route or human save was injected.
- A second bounded fresh run targets Level 2 by naturally replaying neither route nor prefix: `p7-live-20261005213404-18a2a34f77bf46a4b282e66b`, same fixed 900-second preset, target-level human-baseline cap. It completed **Level 2 in 20 total actions**, replay verified, trace sealed, cleanup complete; guest unit inactive/dead/MainPID 0. Ten actor plans, four focus calls, zero cells/publications, no prefix or playbook loaded. This establishes fresh natural two-level completion, but not persistent WorldMap use or program-model transfer.

Full 25-game evaluation is outside this authorization. No benchmark percentage is inferred from these partial witnesses.

## Evidence-driven completion of the main reasoning path

The real attempts exposed a structural bypass: the initial empty revision admitted plans indefinitely, and focus only changed the current task. This allowed successful direct planning with no external WorldMap. Requiring Python/export boilerplate for a semantic update plausibly discouraged publication; that causal explanation is a current judgment, while the bypass and zero publication are verified facts.

The existing workspace tool now supports direct, bounded semantic `revise`, preserving optional program publication. Plans will use a meaningful current semantic revision; mismatches, actual RESET and level changes will require one update grounded in current evidence before the next plan. Matched predictions may retain their revision. This does not require complete rules, report certification, one experiment per hypothesis, or compulsory computation. Independent supplement review passed. Extension tests: 33 PASS / 6 external-Pi skips; related integration Python suite: 317 PASS; final task-declaration event patch: 18 Solver tests PASS. Packaged extension synchronized. Direct semantic updates emit actor task declarations plus model revisions, without inventing calculation starts/completions. Final promotion and the revised installed witness remain pending.
