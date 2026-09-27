# Prime P7 GPT-6-Sol Solving Design

## Goal and boundary

Move the native P7 solving preset from `deepseek/deepseek-v4-flash` to
`openai-codex/gpt-6-sol` through the installed Pi RPC host, then test whether
the new preset advances locally verified ARC-AGI-3 levels. This change is
application/operator integration only. DCI, framework protocols, manifests,
the game broker, prompt, seed 0, saved actions, and score rules remain intact.
An official card is created only after new local prefixes pass seal, replay,
and cleanup checks.

## Operator-owned Pi resources

- The Orb guest continues to launch the installed Pi 0.87.1 RPC bundle from
  `ASTERION_PRIME_PI_ENTRY`. It does not invoke the host `pi` command or the DCI
  checkout's Pi build.
- The operator supplies an exact, existing Pi agent directory through
  `ASTERION_PRIME_PI_AGENT_DIR`. For this workstation it is the guest mount of
  the canonical host `~/.pi/agent` directory, containing the authenticated
  `openai-codex` entry and model catalog. Pi uses that same auth-file and lock
  location for token refresh; no OAuth token is copied or symlinked.
- Application preflight checks that the directory is canonical, non-symlinked,
  readable, has a selected OAuth entry, has enabled compaction, and has no
  `SYSTEM.md`, `APPEND_SYSTEM.md`, or `models.json` override. It never writes
  into the operator's Pi profile. Missing or unexpected inputs fail closed
  with a public-safe message.
- Pi argv fixes `--provider openai-codex --model gpt-6-sol --thinking medium`,
  disables extension, skill, prompt-template, theme, and context-file
  discovery, and explicitly loads only the pinned packaged P7 IPython
  extension. The selected tool remains `ipython`.
- The installed Pi model registry must resolve the exact provider/model and
  official Codex Responses endpoint. A zero-prompt RPC `get_state` check is
  required before a paid run. The existing global Pi `settings.json` can keep
  unrelated interactive preferences; the P7 argv and preflight must exclude
  them from the solving session.

## Evidence and backward compatibility

- New run options, private trace identities, experiment metadata, and public
  safe model labels use the exact new identity. Active P7 execution accepts
  only the new identity.
- Historical DeepSeek summaries, seals, traces, official receipts, and action
  recordings remain unchanged. Saved-prefix loading accepts only the exact
  historical DeepSeek identity or the new Codex identity, then still requires
  the existing hash, seal, game/seed, recording, and fresh-engine replay checks.
  It rejects any unknown or mixed identity. A replayed historical action is
  attributed to the current run as an imported, reverified prefix rather than
  represented as a GPT-generated action.
- Official replay remains model independent: it executes an already verified
  action sequence against a new Competition game and checks every transition.
  No previous official card is modified.

## Finite research sequence

1. Provider-free unit and installed-wheel checks prove exact argv, OAuth
   preflight, global resource isolation, historic-prefix acceptance, new
   identity validation, redaction, and cleanup. The guest's no-prompt RPC
   `get_state` must report `openai-codex/gpt-6-sol`.
2. One tiny bounded model smoke proves an IPython call/result pair, usage
   reporting, terminal event, and cleanup. It does not count as solving.
3. Run one OFFLINE same-game retry at a time, preserving the best verified
   prefix and human-baseline action cap: FT09 L5, M0R0 L4, TR87 L3. Each run
   keeps the existing 30-minute wall limit and 5-minute no-action stop.
   Verify seal, replay, cleanup, and prefix level before starting the next.
4. If at least one of three passes, consider AR25 L5, KA59 L3, and TU93 L5
   in that order of expected value per bounded attempt. If none passes, stop
   paid retries and compare tool calls, no-effect loops, compaction, and
   terminal causes before changing reasoning effort or prompts.
5. Submit all newly verified prefixes in one official 25-game card, then read
   the closed scorecard. The prior 11.546232740099406 score is the baseline,
   not an expected score for the new model.

## Verified starting point

On 2026-09-27, the host Pi and Orb guest Pi both report version 0.87.1. A
zero-prompt guest RPC `get_state` using the canonical Codex profile returned
`openai-codex/gpt-6-sol`; it did not invoke the model. The existing P7 code
still launches DeepSeek. The latest closed official card is
`8cd88c5b-ec12-49e3-9ff6-1d4af2e1e8c5` with score 11.546232740099406,
25 attempted games, and zero complete games.
