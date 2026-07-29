# Asterion Capability Packages

Capability packages are portable payloads selected from explicit sources. The
portable payload contains only closed protocol documents and declared public
resources. Provider factories and local paths stay in the source declaration,
not in `capability-package.json`.

## Author Commands

```bash
asterion capability init ./my-package --package-id acme.demo
asterion capability validate ./my-package/payload
asterion capability inspect \
  --package acme.demo@0.1.0 \
  --source-id acme.demo.local-directory \
  --root /absolute/path/to/my-package \
  --payload-root payload \
  --module-path provider.py \
  --factory-name create_package \
  --payload-sha256 <validated-payload-sha256>
asterion capability test \
  --package acme.demo@0.1.0 \
  --source-id acme.demo.local-directory \
  --root /absolute/path/to/my-package \
  --payload-root payload \
  --module-path provider.py \
  --factory-name create_package \
  --payload-sha256 <validated-payload-sha256>
```

`validate` opens the portable payload and reports only public identity,
counts, and the payload digest. `inspect` uses an explicit local-directory
source declaration and does not import the provider module. `test` loads only
that selected provider after source identity validation, then runs the public
conformance kit without runtime, Agent, Judge, provider-backed, network, or
dataset work.

`pack` and `convert` currently validate their arguments and then report that
archive forms are unsupported. They do not write output until the archive-form
plan is approved.

## Source Boundary

Use exact local source arguments. Asterion does not scan parent directories,
search sibling repositories, mutate `sys.path`, choose latest versions, or
apply source precedence. Local roots, module paths, provider locators, and
private operator details are not printed in public output.

Portable manifests must not contain prompts, commands, executable paths,
credentials, provider configuration, environment values, private paths, or
mutable state. Source selection grants no execution authority; host services
and runtimes remain operator-injected after package selection.
