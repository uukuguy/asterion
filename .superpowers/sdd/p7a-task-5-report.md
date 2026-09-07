# P7a Task 5 report: persistent controlled IPython worker

Baseline: `74891a8390972a6219f91378e54263dacb779275`.

Implemented a solve-image entrypoint that owns one long-lived
`InteractiveShell` and serves canonical length-prefixed requests over the
container-local `/workspace/kernel.sock`. Its client mode accepts one
base64-encoded UTF-8 cell argument, returns bounded canonical JSON, retains
the namespace, caps code/output/cells, and removes the socket on exit.

`P7SolvingDockerTransport` creates a source-locked, non-root, read-only,
network-disabled container with a single writable workspace and the exact
read-only broker model socket. It clears inherited provider environment values,
uses the inherited Docker call/control helpers, validates the inspect
projection, and compensates uncertain creation. `P7SolvingDockerWorker`
seeds only the supplied broker client, accepts at most 128 cells, validates
contiguous counts, and shields cleanup from cancellation until absence is
proved. Public errors and reprs are redacted.

Verification:

* `uv run python -m unittest -v tests.test_prime_p7_solving_kernel tests.test_prime_p7_solving_docker` — 4 passed, including the real solve-image `x = 41` then `print(x + 1)` persistence path.
* `uv run ruff check src/asterion/applications/prime_agent/operator/p7_solving_docker.py src/asterion/applications/prime_agent/operator/p7_solving_image/launcher.py tests/test_prime_p7_solving_docker.py tests/test_prime_p7_solving_kernel.py` — passed.
* `uv run python -m py_compile src/asterion/applications/prime_agent/operator/p7_solving_docker.py src/asterion/applications/prime_agent/operator/p7_solving_image/launcher.py` — passed.

The initial Buildx spelling mismatch was corrected to `--pull=false`; the real
container integration assertion then built and passed in this environment.
