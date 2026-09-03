# Prime IPython Workload-Result Design

## Scope

Implement one real restricted-worker workload for
`prime.ipython-coding/v1`. Products 2–7 remain External-limited. This does
not authorize Docker, model, network, or benchmark execution.

## Contract

The operator-owned Docker worker accepts one code-owned, versioned P1 fixture
selected by its exact workload digest. It does not accept prompts, commands,
paths, environment values, or arbitrary source text from an application.

The fixed launcher receives the selected fixture through code-owned image
content, executes its fixed IPython sequence after the release barrier, and
emits exactly one canonical terminal-result JSON frame. That frame includes:

- `workload_digest` — the exact selected fixture identity;
- `result_digest` — SHA-256 of canonical result bytes produced in the worker;
- `terminal` — exactly `completed`.

The host verifies the frame is canonical, exact, bounded, and matches the
lease workload digest. It derives the execution receipt result digest from the
canonical result bytes. A fixed completion marker alone is never a result.

## Boundaries

- Docker remains fixed to `prime.ipython-coding`; no generic role or command
  launcher is introduced.
- The image owns fixture content and execution; requests carry only the
  fixture digest and finite limits.
- Public receipts retain IDs and digests only. They never expose fixture code,
  IPython output, prompts, paths, credentials, or raw frames.
- P5/P6 cannot consume this P1 receipt because their scenario and worker role
  do not match. They remain External-limited until their own launcher exists.

## Verification

- Unit tests reject unknown workload digests, substituted frame workload or
  result fields, noncanonical frames, duplicate frames, and result body leaks.
- Docker service tests prove that the execution receipt is derived from the
  actual canonical worker result and binds the lease workload.
- Existing P1 fixture/provider-free behavior remains provider-free; no test
  starts Docker or a model.
