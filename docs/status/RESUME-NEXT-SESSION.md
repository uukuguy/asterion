# Live Session Checkpoint

> Updated: 2026-09-29 01:05. **Session remains active — not a final handoff.**

## TL;DR

1. Code baseline is unchanged: `d50897f7` (Prime P7 migrated to `openai-codex / gpt-6-sol`), still with no authorized P7 gameplay run.
2. New this session: P7's provider and model are now selected by `ASTERION_PRIME_PROVIDER` / `ASTERION_PRIME_MODEL` from the operator environment (commit `e392577`, decision `D-2026-09-29-01`).
3. GPT-6-Sol was verified reachable live, from both the macOS host and the P7 OrbStack guest; the OAuth credential in `~/.pi/agent/auth.json` is valid to 2026-10-07.

## Where things stand

- HEAD: `e392577 Source the native P7 provider and model from the operator environment` on top of the `d50897f7` baseline and its close-out commit.
- Working tree: clean; nothing in flight; no P7 or Asterion process running.
- P7 test set (376 tests before, 386 now): 4 failures + 7 errors, **all pre-existing** (see "Known existing failures"). The pre-change baseline was 4 failures + 9 errors, so this change removed two stale DeepSeek-era errors and added none.
- Verified live: `openai-codex/gpt-6-sol` answered a sentinel prompt from the Mac (`pi --print`) and from the `ubuntu` OrbStack guest through the exact P7 launch path (node 22 + mounted `rpc-entry`, `PI_CODING_AGENT_DIR` pointing at the shared profile).

## Current judgment (not yet proven end-to-end)

- Selecting another model through the environment is wired through identity, receipt, prefix reuse and the operator tools, but **no P7 run has been executed with a non-default model**. Only the default pair has live evidence.
- The fail-closed rule treats the Pi catalog plus a declared credential as the allowlist. That is a deliberate downgrade from a compiled-in constant and is only as good as the profile.

## Known existing failures (pre-existing, unrelated to this change)

- `tests/test_prime_p7_live_command.py` — six worker tests and one generated-module-facade test fail with `KeyError: 'act'`.
- `tests/test_prime_p7_installed*` / `test_prime_p7_official_gameplay*` — four sub-failures on the installed route.
- Not investigated this session; they are not caused by the model-selection change.

## Next steps (immediate, action-level)

1. Decide whether to fix the eleven pre-existing failures above, or leave them.
2. If the model selection is to be exercised, run one bounded P7 level-witness with an explicit non-default model and confirm the trace identity, receipt and prefix gate follow it.
3. No gameplay run is authorized by this checkpoint.

## Don't go down these paths again (ruled out)

- Do not treat `ASTERION_PRIME_PROVIDER` / `ASTERION_PRIME_MODEL` as decorative: they are read in exactly one module (`p7/model_selection.py`). Editing them elsewhere reintroduces the drift this change removed.
- Do not restore a hardcoded pair in `prime/runtime_binding.py`: the factories now require `context.options` to agree with the approved launch command, and a fixture without `--provider` / `--model` is rejected by design.
- Do not read stale `.asterion-private` traces as evidence of the current selection; the discarded post-baseline session left generated artifacts on disk.
- A zero-model-call P7 preflight (`make asterion-prime-p7-breadth-preflight`) was started and killed this session: it spends minutes in `uv --isolated` dependency resolution and proves less than the direct model probe. Prefer the probe.

## Ready-to-paste commands / configs

```bash
git log --oneline -3
make asterion-prime-p7-games            # provider-free P7 surface
uv run python -m unittest -v tests.test_prime_p7_model_selection
uv run python -m unittest tests.test_prime_p7_gpt6_migration tests.test_prime_p7_official_operator
```

To exercise another model, set both keys in the operator `.env` to a provider/model pair present in `~/.pi/agent/models-store.json` with a credential, then run the normal P7 preset. `--thinking high` stays fixed.
