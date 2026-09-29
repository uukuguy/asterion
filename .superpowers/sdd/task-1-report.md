status: PASS
commit: 76ec4fb0ab44a717dd8ef95d7dcafbcd0bbe9a25

Implemented the validated provider-neutral P7 world model in `world_model.py`, including validated evidence and JSON-safe values, immutable snapshot records, capped hypotheses, confirmation matching, level refresh, conflict branches, deterministic redacted projections, and bounded projection sizing.

Verification:

    uv run python -m unittest -v tests.test_prime_p7_world_model
    Ran 5 tests in 0.000s
    OK

    git diff --check
    PASS

Concerns: none within the task boundary. The focused suite covers the required validation, detachment, confirmation, refresh, conflict, redaction, sorting, and size-limit behavior.
