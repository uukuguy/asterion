# P2 Task 3 — sealed launcher protocol

Implemented the private P2 canonical frame reducer and its distinct image
entrypoint. The reducer admits only the ordered self-check, exact P2 release,
broker-response/program-digest binding, IPython fact, oracle fact, disposal,
and one terminal completion. It rejects malformed, non-canonical, oversized,
out-of-order, mismatched, deadline-expired, and post-terminal frames.

The completion is public-safe and contains only normalized fixed facts and
digests. The P2 image has its own entrypoint, fixed fixture/corpus/oracle
directories, immutable fixture lock hash, and a digest-pinned base image. Its
static source contains no generic command, configuration, or caller-supplied
program surface.

Verification (provider-free):

- `uv run python -m unittest -v tests.test_prime_programmatic_long_context_launcher_protocol` — PASS
- `uv run ruff check src/asterion/applications/prime_agent/operator/programmatic_long_context_release.py tests/test_prime_programmatic_long_context_launcher_protocol.py` — PASS
- `uv run pyright src/asterion/applications/prime_agent/operator/programmatic_long_context_release.py tests/test_prime_programmatic_long_context_launcher_protocol.py` — PASS
- `node --check src/asterion/applications/prime_agent/operator/programmatic_long_context_image/launcher.mjs` — PASS
- `git diff --check` — PASS

Docker, model, network, and benchmark execution were intentionally not run.
