# Prime Candidate Store Service Extraction Plan

**Goal:** Separate the cohesive P6 candidate-store implementation while preserving all existing service imports and behavior.

**Scope:** Move P6 limits, data types, CandidateStoreLoop, factory, diagnostic helpers and exact inverse cleanup from `applications/prime/services.py` to `applications/prime/p6/candidate_store.py`. Retain explicit re-exports from `services.py`, including private names already used by operator/test integration. Do not alter P3/P4/P5 behavior or add another coordinator.

- [x] Add import identity regression in `tests/test_prime_service_imports.py`; run RED before module exists.
- [x] Move the complete candidate-store section and its dependencies; avoid a dependency back into the service facade.
- [x] Verify facade class/factory identity and run existing P6 operator/service/runtime tests, including cancellation and rollback.
- [x] Review P5/P6 host execution, public receipt and failure redaction; report remaining boundaries. Parent owns commit and promotion verification.

Commands:

```bash
uv run --extra prime python -m unittest -v tests.test_prime_service_imports tests.test_prime_p5_p6_composed_execution tests.test_asterion_prime_p6_candidate_store_service tests.test_asterion_prime_p6_operator tests.test_asterion_prime_p6_runtime_binding
uv run --extra prime python -m unittest discover -s tests -p 'test_asterion_prime_p[56]*.py' -v
uv run ruff check src/asterion/applications/prime/services.py src/asterion/applications/prime/p6/candidate_store.py tests/test_prime_service_imports.py
```

## Verification and self-review

- RED import identity check failed because the target module did not exist.
- GREEN focused import/composed/P6 service/operator/runtime command above: 42 passed.
- Existing P5/P6 discovery command above: 139 passed. Ruff and scoped diff checks passed.
- The 26 candidate-store names retain object identity through the existing services facade. The extracted module has no dependency back to that facade.
- P5 success operator traverses compose/runner, then the injected loop, oracle and finalization; exact sealed digest is checked before publication.
- P6 success operator traverses the same public composition path, one injected loop/coordinator and the real oracle. Cancellation after admission performs at most one authorized inverse; a changed current revision or failed inverse produces recovery-required and no receipt/artifact.
- Public receipt artifacts expose hashes and fixed metadata. Public runtime failures use fixed messages; the rollback sentinel regression verifies private error text does not escape.
- Boundaries: provider-free fake-worker witnesses only; no live model/task ability or automatic recovery was established. Limits presets remain explicit refusal paths. Legacy low-level candidate-store outcome tuples still require their error/count evidence to be interpreted by the host; the composed host additionally requires actual oracle/result and inverse evidence, so a tuple saying rolled-back alone is never sufficient completion evidence. This extraction changes ownership only and does not redesign that older internal tuple API.
