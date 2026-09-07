# P7a Task 9 report

Status: DONE

Implemented the operator-only `prime.arc-agi-3-solving` host factory and the
`make prime-p7-solve` preset. The factory accepts the exact provider,
application, version, capability, and empty options; reads `.env` only in the
operator module; requires `deepseek-v4-flash`; passes progress and presentation
to the P7 lifecycle; and limits execution and matched receipt retrieval to one
use. Preflight now has separate `display_name` and `preparation_scenario`
fields. Its P7 solve row displays `prime-p7-solve` while preparing
`p7-solving`, without invoking model or game execution.

Verification:

- `uv run python -m unittest -v tests.test_prime_p7_solving_cli_host tests.test_prime_make_presets tests.test_prime_apps_preflight` — 9 tests passed.
- `make -n prime-p7-solve && make -n prime-p7-run` — solving command contains the exact preparation, application/version, input, and progress arguments; P7 development command is unchanged.
- `uv run ruff check ...` and `uv run pyright ...` on Task 9 paths — passed.
