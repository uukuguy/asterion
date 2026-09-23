# Private failure diagnostics plan

## Boundary

Add one optional, operator-owned diagnostic sink at existing execution and source-preparation boundaries. Keep public v1 payloads and existing failure wording closed. A public Python exception may carry an opaque diagnostic ID; the sink stores only a closed stage, exception type, and digests of run and capability identity. It never stores exception text, input, payload, environment, or credentials.

## Steps

1. Add a focused failing runner test: a secret-bearing implementation error yields the same public error, an opaque ID, and a retrievable private record with no secret.
2. Add a narrow `services.diagnostics` protocol and memory implementation for host injection. Capture at the first runner projection boundary. Sink failure must not change execution outcome.
3. After package-preparation changes settle, cover its public projection boundary with the same sink, preserving the exact generic error text.
4. Add focused prompt/worker/oracle diagnostic capture only at already-owned operator boundaries after the prompt and Prime execution work settles.
5. Run focused tests, review redaction, then commit the slice.

## Acceptance

- A failed capability produces no result artifact, and the public exception contains no sentinel content.
- Its `diagnostic_id` locates one bounded private record with stage and exception class.
- No sink and failing sink preserve prior fail-closed behavior.
- No schema or TypeScript public protocol changes.
