# Prime P7 game inventory and official results guide

## Goal

Give the operator one read-only command for local ARC-AGI-3 game identity and verified P7 progress, plus a practical guide that separates local results from official scorecards and competition submissions.

## Design

`make asterion-prime-p7-games` invokes a local Python tool. It reads direct `metadata.json` children under the checkout's sibling ARC asset root and completed P7 private summaries under `.asterion-private/prime-p7-live`. It prints the exact official `game_id` (short ID plus version), local input tags, total levels, best verified completed level count, run ID, and local score. A run counts only when its summary has a receipt, sealed trace, verified replay, complete cleanup, and a matching terminal broker result. Older summaries without broker identity may use the exact recording filename identity; malformed, ambiguous, or in-progress runs do not count. No private prompt, raw frame, key, or path appears in terminal output. The command never loads game source, imports the ARC SDK, makes network calls, or starts a model.

The guide shows how to read the table, locate the two current local games and historical ls20 evidence, use the official API or task browser for the full public game set, and inspect official scorecards. It states that current P7 stops after one level and uses `OperationMode.OFFLINE`: neither another level nor an official scorecard can be produced by changing a Make variable. Multi-level continuation and competition-mode scorecards need separate application work and a separately authorized live run. It explains the official Community Leaderboard PR path and the separate Kaggle competition path without implementing submission.

## Boundaries

The inventory is a local evidence index, not an ARC account status or leaderboard score. Missing or contradictory evidence yields no verified completion. It leaves the active paid solve, user changes in Makefile, and private evidence untouched.
