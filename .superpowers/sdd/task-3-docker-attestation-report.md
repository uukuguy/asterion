# Task 3 Docker-attestation transport slice

Status: complete (provider-free transport boundary only).

- `create` retains its requested safe name only for create/uncertain-create
  compensation; the daemon-returned 64-hex ID is parsed strictly and becomes
  the lifecycle identity.
- Inspection invokes an operator-owned fixed Docker `--format` projection and
  rejects non-exact projected evidence.
- The private live-lease snapshot bridge pauses, archives only
  `/workspace/solution.py`, parses one bounded regular tar member, and always
  attempts unpause. Snapshot values are redacted wrappers.
- Existing forced removal and absence proof remain the only destruction path.
  Process output and launcher completion frames remain non-evidence.

Verification (2026-09-05):

```text
uv run python -m unittest -v tests.test_prime_docker_cli tests.test_prime_docker_worker  # 47 passed
uv run ruff check src/asterion/applications/prime_agent/operator/docker_cli.py src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_cli.py tests/test_prime_docker_worker.py  # passed
uv run pyright src/asterion/applications/prime_agent/operator/docker_cli.py src/asterion/applications/prime_agent/operator/docker_worker.py tests/test_prime_docker_cli.py tests/test_prime_docker_worker.py  # 0 errors
```

Remaining scope: no real Docker invocation or host-supervisor/oracle integration
was run or added; the follow-on trusted supervisor must consume the private
snapshot bridge and independently bind its attestations.
