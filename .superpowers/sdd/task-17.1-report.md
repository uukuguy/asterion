# Task 17.1 report — exact promoted image targets

Status: Implemented and statically verified. No download, staging, runtime, or
worker execution was performed.

The Prime lock now carries a frozen exact OCI descriptor (`os`, `architecture`,
and explicit nullable `variant`). The code-owned promoted catalog contains one
initial candidate only: `linux/amd64` with no variant. Resolution requires an
explicit descriptor; it rejects unknown targets, variants, duplicates,
substituted catalogs/locks, and implicit selection. The descriptor is carried
by release specifications, proposals, plans, and results; staging resolves it
before any transport interaction and rejects a specification differing from
the selected promoted lock. This does not promote arm64 and does not inspect
the Darwin/OrbStack host.

`tests/test_prime_image_materializer.py` was additionally updated under parent
authorization solely to supply and assert the explicit initial descriptor at
the changed planning API. It introduces no default or fallback.

TDD evidence: before production changes,
`uv run python -m unittest -v tests.test_prime_image_input_lock tests.test_prime_image_release_materializer`
failed with missing `ImagePlatformDescriptor` imports/attributes. Final checks:

- `uv run python -m unittest -v tests.test_prime_image_input_lock tests.test_prime_image_release_materializer tests.test_prime_image_materializer` — PASS (24 tests)
- `uv run ruff check src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_input_lock.py tests/test_prime_image_release_materializer.py tests/test_prime_image_materializer.py` — PASS
- `uv run pyright src/asterion/applications/prime_agent/operator/image_input_lock.py tools/materialize_prime_ipython_inputs.py tests/test_prime_image_input_lock.py tests/test_prime_image_release_materializer.py tests/test_prime_image_materializer.py` — PASS (0 errors)
- `git diff --check` — PASS
