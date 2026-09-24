# Prime P7 Game Inventory Implementation Plan

> **For agentic workers:** Implement these tasks with focused review. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only P7 game/progress command and an operational official-results guide.

**Architecture:** A standalone tool reads local metadata and sealed run summaries, then Make exposes it. Documentation explains what the local table proves and the separate official submission routes.

**Tech Stack:** Python standard library, Make, unittest, Markdown.

## Global Constraints

- Do not start a model, connect to ARC, submit a scorecard, or touch the active run.
- Preserve the user's pre-existing Makefile edits.
- Never print private paths, payloads, frames, prompts, credentials, or failure messages.
- An incomplete or ambiguous run contributes zero verified progress.

---

### Task 1: Local inventory tool

**Files:** Create `tools/list_prime_p7_games.py`; create `tests/test_prime_p7_game_inventory.py`.

**Interfaces:** `inventory(arc_root: Path, runs_root: Path) -> list[dict[str, object]]`; `main(argv: list[str] | None = None) -> int` prints a deterministic table. Exact game IDs come from `metadata.json`; completed levels come from verified summary and exact run identity.

- [ ] Add a unittest fixture with two game metadata files, one completed run and one incomplete run; assert only the completed run contributes progress and output contains no private fields.
- [ ] Run `uv run python -m unittest -v tests.test_prime_p7_game_inventory` and observe the missing-module failure.
- [ ] Implement metadata parsing, safe run validation, sorted table output, and argument defaults. For older summaries, resolve game identity only from one unambiguous recording filename.
- [ ] Run the focused unittest and `uv run python tools/list_prime_p7_games.py` with no model/network calls.

### Task 2: Operator command and guide

**Files:** Modify `Makefile`; create `docs/guides/prime-p7-games-and-official-results.md`; modify `docs/status/INDEX.md` and `docs/status/PRIME-P1-P7-ACCEPTANCE.md` for discovery.

**Interfaces:** `make asterion-prime-p7-games` invokes Task 1 tool and prints local status only.

- [ ] Add the Make target without modifying the existing P7 solve recipe or the user's game-ID comments.
- [ ] Write exact commands for local inventory, full official game discovery, official scorecard workflow, community PR, and Kaggle entry. State current OFFLINE/first-level limits and absence of official scorecard.
- [ ] Run focused unittest, `make asterion-prime-p7-games`, `make docs-check`, `make lint`, and `git diff --check`.
- [ ] Review changed code and docs, commit scoped files, and record the result in the project journal/checkpoint.
