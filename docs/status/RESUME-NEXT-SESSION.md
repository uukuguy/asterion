# Next-Session Handoff

> Updated: 2026-09-29 00:04 CST. End of session.

## TL;DR

1. The repository was intentionally hard-reset to `d50897f7`, the completed Prime P7 migration to `openai-codex / gpt-6-sol`.
2. Every code, prompt, tool, diagnostic, gameplay, and state-document change after that commit was discarded because the later session had become unreliable.
3. No P7 process is running; the Git worktree is clean. Do not reuse post-baseline generated evidence as current results.

## Where things stand

- HEAD: `d50897f7 Migrate Prime P7 to Codex GPT-6 Sol`.
- The migration commit keeps the fixed P7 GPT-6-Sol runtime path and its migration tests.
- The later environment-loading, mechanics-prior, application-tool, native-event diagnostic, and gameplay-retry changes are intentionally absent.
- Ignored `.asterion-private` artifacts may still exist on disk; they are stale generated evidence and are not part of the source baseline.
- No new test or live solve was run after the reset.

## What this session delivered

- Located the exact GPT-6-Sol migration boundary at `d50897f7`.
- Stopped the active BP35 witness before closing the session.
- Reset `main` to that boundary and verified `git status --short` is empty.
- Rewrote the structural snapshot and this handoff so the next session does not follow discarded work.

## Next steps (immediate, action-level)

1. On resume, verify `git status --short` and `git log -1`; keep `d50897f7` as the starting baseline.
2. If gameplay work resumes, inspect the migration commit and current P7 operator path before changing code or launching a model.
3. Run a fresh BP35 L1 only after the user explicitly selects the next experiment and its scoring criterion.

## Don't go down these paths again (ruled out)

- Do not restore or continue the post-`d50897f7` mechanics-prior, diagnostic, native-event allowlist, or retry changes without a new explicit decision.
- Do not treat stale `.asterion-private` traces from the discarded session as proof of current P7 behavior.
- Do not claim a BP35 full-score result from the historical 20-action DeepSeek run; it predates the current GPT-6-Sol baseline.

## Ready-to-paste commands / configs

```bash
git status --short
git log -1 --format='%h %ad %s' --date=iso
git show --stat d50897f7
```

The P7 model baseline is encoded by the migration commit; no new model or provider override is needed for a baseline inspection.

## Current task authorization

No model run or further code change is authorized by this handoff. Await the next explicit P7 objective.
