# P7 Official Competition Scorecard Implementation Plan

> **For agentic workers:** Use test-driven development for each task; run the named test red before production changes and green afterward. Steps use checkbox syntax for tracking.

**Goal:** Run P7 against all official ARC-AGI-3 Competition environments on one scorecard and retain the server-confirmed result and URL.

**Architecture:** A new application-owned Competition coordinator preflights all dependencies, creates one scorecard, enumerates official games, passes each exact environment once into the existing solver through an injected engine, and closes the card once. Official evidence uses the live SDK response and server scorecard; the local fresh-engine replay is never invoked for a Competition environment.

**Tech Stack:** Python 3.12, official `arc_agi` SDK, Asterion Prime runner/Pi host, `unittest` fake SDK, Make.

## Global Constraints

- The official scorecard path is a distinct application mode and does not reinterpret historical OFFLINE receipts.
- `get_environments()` must bind the full official game set before opening the card; all returned games are attempted under finite controls.
- One Competition card, one `make` per game, one initial `reset`, then the same remote `guid` for gameplay and level resets.
- No fresh-engine replay or second `make` in Competition mode.
- Official score and URL are exposed only from a validated closed scorecard response.
- The API key and raw frames/prompts/actions remain private.
- No real scorecard or model call in tests; live submission waits until code and preflight are reviewable.

---

### Task 1: Official SDK adapter and preflight

**Files:** create `src/asterion/applications/prime/p7/official.py`; create `tests/test_prime_p7_official.py`.

**Interface:** `OfficialPreflight` contains exact official game IDs and bounded policies, no credentials. `CompetitionSession` owns one SDK `Arcade`, `card_id`, per-game `guid`, and closure result. The SDK factory is injected for tests. `preflight()` checks API key presence, game list, model host, and evidence root without opening a card.

- [ ] Add fake SDK tests asserting that preflight does not call `create_scorecard`, `make`, or model; malformed/empty/duplicate game lists fail closed. Run red.
- [ ] Implement read-only preflight with safe public status and private exact IDs; run focused tests green.
- [ ] Add fake SDK tests for one card, one `make` per game, first reset, same instance, `ACTION6(x,y)`, current-level reset, and close exactly once. Run red.
- [ ] Implement `CompetitionSession` and a narrow remote adapter satisfying the broker action interface; run tests and commit.

### Task 2: Solver integration and official evidence

**Files:** `src/asterion/applications/prime/p7/operator.py`, `live.py`, `private_trace.py`, `broker.py`; `src/asterion/capabilities/prime_arc_agi_3_solver/host.py`; `tests/test_prime_p7_official.py`, `tests/test_prime_p7_live_command.py`.

**Interface:** The operator runs one resolved P7 solver per official game using an injected Competition engine. No component below the operator creates a scorecard. Official receipts explicitly say `official` and contain server-confirmed card ID, URL, overall score, per-game completion, and a closure digest. They never claim local replay verification.

- [ ] Write a fake multi-game test in which one game wins and another fails; assert the card still closes, per-game status is honest, and there is no second `make`. Run red.
- [ ] Refactor the solver launch to accept the injected engine and skip only the OFFLINE replay path for official mode. Keep ordered action/observation and private trace verification; run focused tests green.
- [ ] Write tests for interrupted/failed game, card close failure, returned card-ID mismatch, missing game row, secret sentinel redaction, and duplicate close; run red.
- [ ] Implement versioned official receipt, private recovery record, server-result validation, and one-shot close logic. Run focused tests and commit.

### Task 3: Commands and distribution

**Files:** `Makefile`, `src/asterion/applications/prime/p7/operator.py`, `docs/guides/prime-p7-games-and-official-results.md`; `tests/test_prime_make_presets.py`, `tests/test_prime_p7_native_installed.py`, `tests/test_prime_p7_official.py`.

**Interface:** `make asterion-prime-p7-official-preflight` performs no scorecard/model operation. `make asterion-prime-p7-official-submit` is the explicit Competition run; it prints only the final official URL, aggregate score, and honest completion counts. Local solve and witness commands cannot publish an official URL.

- [ ] Add command tests with fake SDK and no network; assert preflight is read-only and submit has one card lifecycle. Run red.
- [ ] Wire installed-wheel operator selection and safe environment injection. Never include credentials in Make output or JSON manifests; run focused tests green.
- [ ] Document official card generation, partial result meaning, recovery-required state, Community Leaderboard URL use, and separate Kaggle packaging boundary.
- [ ] Run `make lint`, `make docs-check`, P7 test discovery, and `make promotion-check`; review final diff and commit.

### Task 4: Live submission gate

**Files:** `docs/status/RESUME-NEXT-SESSION.md`, `docs/status/JOURNAL.md`, private official result directory.

- [ ] Verify an operator-owned `ARC_API_KEY` is available without printing its value, and run the read-only official preflight.
- [ ] Review exact official game list, fixed cost/action/deadline controls, and one-shot semantics before the external `official-submit` call.
- [ ] With authorization for the actual potentially costly submission, run once, capture closed scorecard response and URL, and compare public result with server fields. If credentials or authorization remain absent, leave this task incomplete and the goal active.
