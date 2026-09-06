# Live Session Checkpoint

> Updated: 2026-09-06 10:36. **Session remains active — not a final handoff.**

## Direction

按评估后的主线持续推进直至完成。Asterion 的核心是统一智能体框架与能力包集成协议；Prime 和 Native 是并行 runtime。当前先收口七项 Prime 端到端复现。研发验证只保留正常链路和关键边界断言，不运行 promotion 或极端矩阵。

Canonical worklist: `docs/status/PRIME-TYPICAL-APPLICATIONS.md`.

## Closed Prime applications

- P1 `make prime-p1-run`: exact installed CLI, five model callbacks, two Docker IPython cells, compact, oracle and cleanup; trace `sha256:a8be640bdcee9c93ea3e382729db561e4c29e071d3ff776335daac4ff572c703`.
- P2 `make prime-p2-run`: two model callbacks, one Docker IPython cell, fixed corpus oracle and cleanup; trace `sha256:4ec38c0cb80010941892523610bb9cdbf8b37c213ed6c759fcd794f30d57a62e`.
- P3 `make prime-p3-run`: two recursive children, ten model callbacks, four Docker IPython cells, host oracle and cleanup; trace `sha256:b961b0ffc13a1e686a73361b9b25b9169690c942a5a84a3604d52f87e5ebe796`.
- P4 `make prime-p4-run`: direct native daemon checkpoint, exact zero-gap detach/reattach, one compact, five model callbacks, two Docker IPython cells, same AST oracle and cleanup; trace `sha256:0bd39b78189f739dcb07123947599276d3f91e7dc24da9407be14ee283e5bebf`.

All four results are development-only and `unpromoted`. P4 closure uses Prime 0.7.1 direct-daemon zero-gap reattach; crash/restart replay and production promotion remain separate work.

## P4 implementation boundary

The full P4 path is implemented by the independent workload/receipt, Python inherited-FD gateway and lifecycle host, TypeScript native-daemon callback bridge, installed provider/application/runtime route, and P1B controlled Docker/provider reuse. Key integration commits are `902ac76b`, `dab17330`, `50ec93fb`, `4d0f3d01`, `0866b122`, `ff4914f3`, `084333bd`, `dac12f57`, `44ce8727`, `25cb9755`, `cbfd4d9b`, `f59803b1`, `942fd6db`, and `e86dddf4`.

Focused verification passed: 19 Python P4 contract/gateway/host/CLI tests, 13 TypeScript bridge/artifact-lock tests, plus the exact real Make command. The final run completed on Orb Ubuntu with Node 22 and P1B image `sha256:acd139a02dbb80277d0a6c78575f1ddcbdd8042c8a7a82b28416a638cab58657`. Orb cleanup inspection found zero P4 processes, containers, sockets, checkpoints and workspaces.

## Next concrete action

P5 `prime.bounded-autonomy/v1` is active. Existing code provides a fixed repair workload, exact ceiling/digest fencing, restricted-worker adapter, two-gate reducer and provider-free acceptance. The missing closure is an installed `make prime-p5-run` route that performs a finite real Prime/IPython diagnostic-repair loop, proves both result and quality gates, emits only a safe unpromoted trace, and cleans up.

Keep P5 within its existing ceilings: at most three actions, bounded usage, fixed IPython-only capability, no retries of uncertain external effects, and fail-closed gate identity. Reuse the P1/P4 runtime, provider, Docker and host-service spine where contracts match; do not introduce a second composer or runner.

## Environment and preservation

- Linux execution uses OrbStack `ubuntu` as root; Docker and the host process share that guest. Node 22 is `/tmp/asterion-node22/bin/node`; the sealed development seccomp profile is `/tmp/asterion-p1-development-seccomp.json`.
- Operator LLM configuration remains in repository `.env` and is read only by application/operator integration.
- Preserve unrelated `.superpowers/sdd/task-1-report.md`, untracked old plan/spec files and existing `tmp*` directories. Never broad-stage, reset, clean, push, or promote.
- Native remains a parallel runtime track and does not block Prime P5–P7 closure.
