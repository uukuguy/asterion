# Live Session Checkpoint

> Updated: 2026-09-27 16:16 CST. Session remains active; this is not a final handoff.

## TL;DR

P7 now has a bounded structured cross-level mechanics prior and a real Pi registered tool path. The Python broker, facade, Unix bridge, TypeScript registration, packaged extension, and verified solve guidance are connected. No new live game has been run after these changes, so cross-level live improvement is not yet verified.

## 已验证事实

- Design and plan for structured cross-level prior were approved and committed as `bcb9cbe1` and `5910b645`.
- `build_mechanics_prior()` is deterministic, bounded, redacted, immutable-input safe, and accepts only ACTION1–ACTION7 with level bounds. Implementation: `ec69aa51`, boundary fix: `08f25fa2`.
- `_P7BrokerClient.mechanics_prior()` pages bounded detached history and returns a capped safe mapping.
- Pi registers `p7_mechanics_prior` alongside the existing P7 tools. The Python `_IpythonBridgeServer` injects the live prediction client, allowlists methods, decodes exact parameter shapes, and returns the five-field method-result envelope.
- The TypeScript method-call writer now appends the newline required by the Python newline-delimited socket server; packaged resource was rebuilt. Bridge repair commits: `c4b390b5`, compatibility fix `7f463b65`, framing fix `57342951`.
- Verified solve guidance calls `p7_client.mechanics_prior()` on later levels, treats results as evidence rather than routes, and requests a falsifiable distinguishing probe. Legacy prompt remains unchanged. Commit: `df70f09d`.
- Verification passed:
  - `uv run python -m unittest -q tests.test_prime_p7_mechanics_prior tests.test_prime_p7_live_command tests.test_prime_p7_native_broker tests.test_prime_p7_native_provider` — 115 passed.
  - `uv run python -m unittest -v tests.test_prime_extension_build` — 8 passed.
  - TypeScript typecheck, focused registration test, Ruff, and diff-check passed.
- Full TypeScript test suite still has its pre-existing context-witness fixture path failures when invoked from the repository root; this is separate from P7 bridge registration.

## 当前判断

- The implementation boundary is ready for one bounded live verification using a game with a verified replayed prefix and an unfinished next level.
- The prior is intentionally evidence-only: it summarizes repeated effects, no-effect counts, click ranges, advances, and confidence; it does not synthesize a route or authorize actions.
- A legacy client without `mechanics_prior` receives an empty safe prior for compatibility; the live prediction client implements the real method.

## 历史归档

- Prompt-only tool listing was insufficient; prior GPT-6-Sol runs stalled at the replay prefix with no new actions.
- Earlier bridge tests covered the old worker socket but not the actual Pi Unix bridge. That gap caused the parameter, result-envelope, injected-client, and newline-framing fixes above.
- Existing successful FT09 and SU15 runs remain historical evidence; they do not prove the new structured prior improves live solving.

## 未完成边界

- No post-change live run has shown that the model actually calls `p7_mechanics_prior` and uses it to solve a new level.
- No claim is made that all games or hidden rules are solved, or that the current model will generalize from one prior.
- The full npm test suite remains broader than the focused registration test and retains unrelated fixture-harness failures.

## 下一动作

1. Run one explicitly bounded P7 live verification on a replayed-prefix game with a next-level target; inspect tool-call trace for `p7_mechanics_prior`, action count, sealed/replay/cleanup evidence, and terminal reason.
2. If the tool is not called, adjust only verified prompt/tool descriptions after recording the trace; do not infer a bridge failure without socket evidence.
3. Keep the live result as evidence until a second independent run confirms behavior.

## Ready commands

```bash
cd <asterion-repo>
uv run python -m unittest -q \
  tests.test_prime_p7_mechanics_prior \
  tests.test_prime_p7_live_command \
  tests.test_prime_p7_native_broker \
  tests.test_prime_p7_native_provider
npm run typecheck --prefix packages/typescript/asterion-prime-extension
```

The working tree intentionally retains the pre-existing scratch changes in `.superpowers/sdd/task-1-report.md`; do not revert them blindly.
