# Asterion Prime P7 Evidence

> Updated: 2026-09-10. Scope: first native `asterion.prime` AgentRuntime slice
> and the `prime.arc-agi-3-solving@1.0.0` application.

## Claim

**Verified:** Asterion Prime, using Asterion's Pi integration and the
`deepseek-v4-flash` model, completed Level 1 of ARC-AGI-3 game
`ls20-9607627b`. The selected application and runtime contain no Prime Agent
source or SDK dependency, no seeded answer, and no preset action sequence.

This proves the native P7 application slice. It does not prove complete
Asterion Prime parity, all seven game levels, the ARC-AGI-3 suite, or product
promotion.

## Live run

| Field | Recorded value |
|---|---|
| Run | `p7-live-20260909065351` |
| Application / runtime | `prime.arc-agi-3-solving@1.0.0` / `asterion.prime` |
| Game / seed | `ls20-9607627b` / `0` |
| Model | `deepseek-v4-flash` |
| Result | Level 1 completed; terminal reason `level-completed` |
| Actions | 23 primitive environment actions; 23 action trace entries |
| Agent tools | 43 persistent IPython cells |
| Frames | 30 recorded visual frames |
| Partial game score | `3.267621` |
| Trace | 25 entries; sealed |
| Replay / cleanup | verified / complete |
| Receipt SHA-256 | `72dbca77f43b88579911883daa96250d38113e7103171c2fb125a01e152d21d9` |
| Replay SHA-256 | `sha256:ce19ada57c6bbf6c71a3091a4ea8ba4b56550b91ee948884b7ce6e51680bc6a4` |
| Final trace SHA-256 | `sha256:61d983c2eb0ab41acb6d016fafa209b0f85636ccf6edccadd226665ac39c2225` |
| Story bundle SHA-256 | `sha256:b35614f8764e6b27409f8e4777f7efab732b58161379446dea4a09da4fdc681e` |

The run predates common Pi usage normalization. Elapsed time, token usage,
and an exact model-callback count were not persisted and are therefore
reported as **not recorded**, not estimated. No comparison report was produced
for this run.

## Reproducible artifacts

- Canonical catalog: `artifacts/arc-agi-3/catalog.json`
- Normalized run data: `artifacts/arc-agi-3/games/ls20-9607627b/runs/p7-live-20260909065351/`
- Accepted analysis: `analysis-eaebabce55daf73d3eda`
- Current web render: `web-2936ab8ccd2c7b525b2d`
- Offline single-file export:
  `artifacts/arc-agi-3/exports/arc-agi-3-ls20-9607627b-p7-live-20260909065351-web-2936ab8ccd2c7b525b2d.html`
- Offline export SHA-256:
  `c8ca0a727b1b36c803f3a9b1b2e2e111424f3fbbc4964ec40f6767730a62e561`

The normalized bundle is digest-bound to the private source evidence. Public
documentation does not reproduce private prompts, provider payloads, or raw
reasoning content.

## Verification ledger

| Status | Command / evidence | Boundary |
|---|---|---|
| PASS | Original native P7 live runner | authoritative level transition, sealed trace, replay and cleanup |
| PASS | Focused native runtime/P7/Pi suite: 95 tests | native runtime and P7 implementation |
| PASS | Focused legacy preparation/lock suite: 23 tests | retained P1-P7 development preparation |
| PASS | Wrapper-removal regression: 112 Python tests | native registration, source detachment, packaging inventory and retained broker behavior |
| PASS | `npm run build --prefix packages/typescript/prime-gateway` | remaining TypeScript gateway compiles after P7 wrapper removal |
| PASS | `uv build --wheel` | wheel builds and contains no removed P7 SDK wrapper files |
| PASS | `git diff --check` | changed files have no whitespace errors |
| Not rerun | full `make test`, `make check`, `make promotion-check` | intentionally not promoted from focused research checks |
| External-limited | remaining six ARC levels and multi-game benchmark | require separately authorized model/environment execution |

## Architecture boundary and next work

`asterion.prime` and `asterion.native` are peer agent runtimes built on the
shared Asterion framework. P1-P7 are applications. P7 is the first application
implemented on the native Asterion Prime kernel; the former Prime SDK solving
provider, gateway, host, preparation route, TypeScript bridge, seeded command,
and package artifacts were removed in commit `e8ac49ec`.

Complete Asterion Prime capability parity still requires separately planned
work for its control-plane client, durable sessions and recovery, context
accounting and compaction, child-agent coordination, bounded autonomy,
continual improvement, and native P1-P6 application routes. Historical
Prime-Agent-backed development evidence remains historical evidence only.
