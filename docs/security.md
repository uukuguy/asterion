# Asterion security boundaries

## Portable manifests

Portable manifests describe compatibility only. They do not carry prompts,
credentials, commands, executable paths, environment values, provider
configuration, mutable state, or registry pointers. If a value changes at run
time, it belongs to operator-owned input or injected host services, not to the
manifest.

## Source forms and locks

- Built-in is one generic source form.
- The external installed-distribution path is the clean-wheel proof that exact
  `package_id@version` locks select the same portable payload without source
  scanning or precedence rules.
- If an unlocked view would expose multiple candidates, the host fails closed
  on ambiguity.
- Archive and registry source forms are deferred to a separate security design
  and are not part of the current execution contract.

## Operator-owned execution

- DCI operator configuration is application-owned and injected after exact
  selection.
- The generic benchmark host remains plan-only by default.
- `--execute` is the explicit execution gate for `run` and `resume`.
- `--amount` is optional in the DCI adapter; omitting it means no amount budget
  is supplied.
- Installed Python extension code is trusted process code, not a sandbox. The
  trust boundary is the selected exact package plus the host services that are
  explicitly injected.

## Controlled execution

The Rust controlled executor is a policy-enforcing process runner with a
cleared environment and direct invocation. It is not an OS sandbox and does
not authorize commands by itself.

## References

- [Asterion architecture](architecture.md)
- [Capability execution](architecture/capability-execution.md)
- [Rust controlled executor](operator/rust-executor.md)
