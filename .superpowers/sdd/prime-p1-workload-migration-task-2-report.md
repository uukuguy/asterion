# Prime P1 workload migration — Task 2

## Result

Migrated the closed Prime P1 consumer and lock boundary to the canonical
workload identity `sha256:21e33f624940b7715de04f30a68223ad5947daba3b294c9e1cd6`.
The legacy `f4ebce1e8a4576db9235f6d8c67dffd9718931f64a07960e1d83b3809d3ce022`
remains exclusively the expected-result identity in `workload.json` and
`ipython_workload.py`.

- The image launcher, fixture lock, P1 request contract v2, host supervisor,
  application-resource descriptor, and authority-artifact descriptor now bind
  the new workload digest without an old-digest fallback.
- The application descriptor now locks `fixture/workload.json` and the changed
  launcher/fixture-lock bytes. Both descriptor hash sets were independently
  recomputed and verified.
- Docker worker and CLI test seams already consume
  `PRIME_IPYTHON_CODING_WORKLOAD_DIGEST`; focused tests prove the new identity
  is admitted and foreign digests are rejected.

## TDD evidence

Before implementation, the focused RED run failed at the intended stale
boundaries: request-contract version/bytes, launcher and fixture-lock identity,
and P1 host-supervisor identity admission. After the atomic migration:

```text
uv run python -m unittest -v tests.test_prime_ipython_workload \
  tests.test_prime_p1_authority_request_contract \
  tests.test_prime_ipython_launcher_protocol \
  tests.test_prime_ipython_host_supervisor \
  tests.test_prime_ipython_host_orchestrator \
  tests.test_prime_ipython_host_issuer tests.test_prime_docker_worker \
  tests.test_prime_docker_cli tests.test_prime_p1_authority_application_resources \
  tests.test_prime_p1_authority_artifact_lock
# 128 tests, OK
```

`ruff` passed for changed source and tests. Targeted `pyright` passed for the
changed contract/supervisor and tests; running it with the pre-existing
`authority_application_resources.py` file reports two existing incompatible
`__reduce__` / `__reduce_ex__` override annotations, unrelated to this
constant-only change. `git diff --check` passed.

## External promotion blocker

No Docker, provider, network, subprocess, image build, or production execution
was invoked. `PRIME_P1_PROMOTED_SECCOMP_POLICY_CATALOG` remains empty, so
static migration cannot make an existing image eligible for `basic`. A future
promotion needs externally produced exact native image/build-input and seccomp
artifacts. This task intentionally leaves the admission path fail-closed and
does not fabricate those identities.
