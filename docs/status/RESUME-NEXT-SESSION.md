# Live Session Checkpoint

> Updated: 2026-09-28 10:35 CST. Session remains active; this is not a final handoff.

## TL;DR

P7 now has a bounded structured cross-level mechanics prior and a real Pi registered tool path. The Python broker, facade, Unix bridge, TypeScript registration, packaged extension, and verified solve guidance are connected. Four bounded FT09 next-level runs were executed after these changes: two stalled at the 59-action replay prefix and two failed before any bridge call. Cross-level live improvement is not verified.

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
- The current TypeScript source and packaged extension resource both expose the same nine tools, including `p7_mechanics_prior`; `npm run build` and the extension build-closure suite passed, with the generated bundle digest matching the packaged resource.

## 当前判断

- The implementation boundary is code-verified, but FT09 live verification is paused until the native runtime `ProtocolError` is independently diagnosed or the Pi provider/session is changed.
- The prior is intentionally evidence-only: it summarizes repeated effects, no-effect counts, click ranges, advances, and confidence; it does not synthesize a route or authorize actions.
- A legacy client without `mechanics_prior` receives an empty safe prior for compatibility; the live prediction client implements the real method.

## 历史归档

- Prompt-only tool listing was insufficient; prior GPT-6-Sol runs stalled at the replay prefix with no new actions.
- Earlier bridge tests covered the old worker socket but not the actual Pi Unix bridge. That gap caused the parameter, result-envelope, injected-client, and newline-framing fixes above.
- Existing successful FT09 and SU15 runs remain historical evidence; they do not prove the new structured prior improves live solving.

## 未完成边界

- FT09 post-change run `p7-live-20260927081939-5c7820a6bfe22dbc0be38357` ended `execution-stalled` at prefix 59 / target L5 with cleanup true and no new verified level. The recording has no model tool-call events, so it cannot establish whether `p7_mechanics_prior` was called.
- FT09 second run `p7-live-20260927083252-0bd5aa566c21a90c48c60cf7` ended `child-evidence-invalid`; private accounting shows zero bridge calls, worker cell count 0, two usage events, and successful prefix replay/seal/cleanup. The native runtime error is intentionally redacted to a generic application failure; operator now retains private failure stage/type when a composed capability diagnostic is available.
- FT09 fourth run `p7-live-20260927170356-0499ca87ddaeba7c4a2d6ce8` recorded `application_failure={stage: capability.execute, exception_type: ProtocolError}`, zero bridge calls, worker cell count 0, and successful prefix replay/seal/cleanup. This places the failure before P7 tool dispatch.
- No claim is made that all games or hidden rules are solved, or that the current model will generalize from one prior.
- The full npm test suite remains broader than the focused registration test and retains unrelated fixture-harness failures.

## 下一动作

1. Do not change the bridge based on the second run: its zero-call evidence places the failure before Pi tool dispatch.
2. Do not spend further live budget on FT09 until the native runtime ProtocolError boundary is independently diagnosed or the Pi provider/session is changed.
3. Keep all FT09 outcomes as bounded negative evidence; do not promote them to a general model or bridge conclusion.

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

The previously retained `.superpowers/sdd/task-1-report.md` scratch changes were reviewed and committed in `697da942`; the working tree is clean.
