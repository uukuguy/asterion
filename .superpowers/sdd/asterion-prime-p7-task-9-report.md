# Task 9 — installed native P7 route

## Delivered

- Added an isolated-wheel smoke test that installs the built wheel in a `/tmp`
  virtual environment with the source checkout unavailable to the child.
- Added a fixture-only Pi JSONL double.  It loads the packaged pinned extension,
  invokes its public `ipython` tool, and exercises injected deterministic engine
  and worker edges.  Its receipt is explicitly labelled
  `solver_evidence=deterministic-double`; it is not solving evidence.
- Added the Hatch pre-build hook and wheel artifact entry for the compiled,
  comment-free, self-contained Task 5 extension.
- Projected the P7 runtime's native tool traffic to the capability's sealed
  receipt-only stream.  The projected artifact digest is calculated before the
  capability seals the trace; the capability remains the sole receipt issuer.
- Made an empty promotion `--npm-cache` select a local temporary cache path and
  made the full checker prepare the extension package before Hatch invokes its
  build hook.

## Evidence

- RED: `uv run python -m unittest -v tests.test_prime_p7_native_installed`
  initially failed because the wheel lacked the extension and loader resources.
- GREEN: `uv run python -m unittest -v tests.test_prime_p7_native_installed tests.test_prime_p7_native_provider tests.test_prime_arc_agi_3_solver_package tests.test_check_promotion`
  passed 44 tests.
- `uv build --wheel` plus archive inspection confirmed the extension, loader,
  and P7 assembly resources are packaged; no TypeScript source tree, legacy
  `prime_agent` identifier, `@mariozechner` SDK marker, or `process.argv`
  reference appears in the compiled extension.
- Ruff and Python compilation were run on the changed Python surfaces.

## Boundary

The fixture completes one deterministic 13-action level and proves wiring,
receipt sealing, replay, and cleanup only.  It does not establish model-backed
ARC solving performance or promotion evidence.
