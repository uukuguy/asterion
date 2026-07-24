# Rust Controlled Executor

The v1 local backend is a policy-enforcing process executor, not an operating-system sandbox. An allowed child can still use the network, open absolute paths, invoke platform syscalls, and spawn descendants.

## Trusted startup policy

The binary accepts exactly one argument: a JSON file containing trusted operator configuration. Never generate this file from an agent request.

```json
{
  "workspace_root": "/absolute/canonicalizable/workspace",
  "programs": {
    "search": "/absolute/path/to/rg"
  },
  "max_deadline_ms": 30000,
  "max_output_bytes": 65536,
  "max_concurrency": 4
}
```

Run the newline-delimited JSON service with:

```bash
cargo run --manifest-path packages/rust/controlled-executor/Cargo.toml -- /path/to/policy.json
```

Requests arrive on stdin and protocol responses are the only stdout content. Safe startup/runtime diagnostics use stderr. Agent requests can name only a configured `program_id`, literal argument vector, workspace-relative existing cwd, and values within the trusted deadline/output ceilings.

The executor clears the child environment, closes stdin, invokes the canonical executable directly without `PATH` or shell resolution, drains stdout/stderr under independent caps, and kills/reaps on deadline or accepted cancellation. A cancel acknowledgement can race with natural completion, but each execution emits exactly one terminal result.

## Verification

Run the provider-free gates from the standalone repository root:

```bash
cargo test --manifest-path packages/rust/controlled-executor/Cargo.toml
make test-rust
make check-rust
```

Stronger containment belongs in a replaceable container, remote-worker, or platform isolation backend behind the same `dci.executor/v1` contract.
