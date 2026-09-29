status: PASS
commit: 4501b62531c39c491c0ad60a2942d15a92e648d4

Implemented the validated provider-neutral P7 world model in `world_model.py`, including validated evidence and JSON-safe values, immutable snapshot records, capped hypotheses, confirmation matching, level refresh, conflict branches, deterministic redacted projections, and bounded projection sizing.

Verification:

    uv run python -m unittest -v tests.test_prime_p7_world_model
    Ran 5 tests in 0.000s
    OK

    git diff --check
    PASS

Concerns: none within the task boundary. The focused suite covers the required validation, detachment, confirmation, refresh, conflict, redaction, sorting, and size-limit behavior.
