UV_BIN ?= uv
ASTERION_PROVIDER ?= dci-agent-lite
ASTERION_ARGS ?=
DCI_ARGS ?=
ASTERION_PRIME_NODE ?= $(shell npm exec --offline --yes --package=node@22 -- node -p 'process.execPath' 2>/dev/null)
ASTERION_PROMOTION_NPM_CACHE ?=
PRIME_ORB_MACHINE ?= ubuntu

.DEFAULT_GOAL := help

.PHONY: help sync build test lint docs-check check promotion-check first-run-check test.core-only test.public-extension test.cross-package-extension test.cross-runtime-extension
.PHONY: test.framework-core test.cross-language-contracts test.extension-wheels test.provider-integration test.framework-provider-free
.PHONY: setup-pi check-pi
.PHONY: setup-resources-basic check-resources-basic
.PHONY: setup-resources-benchmark check-resources-benchmark
.PHONY: setup doctor
.PHONY: asterion-list asterion-describe asterion-verify-preflight
.PHONY: asterion-verify-basic asterion-verify-acceptance asterion-verify-complete
.PHONY: asterion-run
.PHONY: dci-list dci-describe dci-preflight dci-basic dci-complete
.PHONY: dci-run dci-benchmark
.PHONY: dci-basic-example dci-runtime-context-example
.PHONY: test-typescript test-rust check-rust
.PHONY: asterion-prime-p1-run
.PHONY: asterion-prime-p2-run
.PHONY: asterion-prime-p2-run-verbose
.PHONY: asterion-prime-p4-run
.PHONY: asterion-prime-p4-run-verbose
.PHONY: asterion-prime-p3-run
.PHONY: asterion-prime-p3-run-limits
.PHONY: asterion-prime-p3-run-verbose
.PHONY: asterion-prime-p7-solve

# Operator-owned values for the Prime presets. Defaults below are this
# machine's current install paths; pass any of them as `make <target>
# VAR=value` to override (e.g. on a fresh install). Empty values fail
# closed in the operator preflight, so unset defaults are surfaced
# immediately rather than at the run boundary.
ASTERION_PRIME_PI_ENTRY ?= /mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js
ASTERION_PRIME_OPERATOR_ROOT ?= $(CURDIR)
ASTERION_PRIME_P2_CORPUS ?= $(CURDIR)/tests/fixtures/prime_p2/small_corpus.json
ASTERION_PRIME_ARC_ROOT ?= /Users/sujiangwen/sandbox/agentic-2026/external-prime/arc-agi-3
ASTERION_PRIME_P4_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p4-witness
ASTERION_PRIME_P3_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p3-witness
.PHONY: test.native-controller-core.provider-free

help:
	@echo "provider-free setup (network/disk; Agent operations 0; Judge operations 0): setup setup-pi setup-resources-basic setup-resources-benchmark"
	@echo "provider-free checks: check-pi check-resources-basic check-resources-benchmark doctor first-run-check"
	@echo "layered provider-free: test.framework-core test.cross-language-contracts test.extension-wheels test.provider-integration test.framework-provider-free"
	@echo "bounded presets: asterion-verify-basic asterion-verify-complete dci-basic dci-complete"
	@echo "operator-authorized run/benchmark: asterion-run dci-run dci-benchmark"
	@echo "full regression: check promotion-check"
	@echo "provider-free lifecycle: sync build test lint docs-check"
	@echo "framework acceptance: test.core-only test.public-extension test.cross-package-extension test.cross-runtime-extension"
	@echo "provider-free framework: asterion-list asterion-describe asterion-verify-preflight asterion-verify-acceptance"
	@echo "bounded provider-backed presets: asterion-verify-basic asterion-verify-complete"
	@echo "DCI adapter: dci-list dci-describe dci-preflight dci-basic dci-complete dci-run dci-benchmark"
	@echo "DCI bounded examples: dci-basic-example dci-runtime-context-example"
	@echo "Cross-language provider-free: test-typescript test-rust check-rust"
	@echo "Asterion Prime fixed small verification: asterion-prime-p1-run"
	@echo "Asterion Prime P4 cross-generation witness: asterion-prime-p4-run"
	@echo "Cost boundary: full execution requires separate authorization"
	@echo "Arguments: ASTERION_ARGS='...' or DCI_ARGS='...'"

sync:
	$(UV_BIN) sync --frozen

build:
	$(UV_BIN) build .

test:
	$(UV_BIN) run --extra dci --extra prime python -m unittest discover -s tests -v

test.core-only:
	$(UV_BIN) run python -m unittest -v tests.test_core_only_install tests.test_project_boundary

test.public-extension:
	$(UV_BIN) run python -m unittest -v tests.test_public_extension

test.cross-package-extension:
	$(UV_BIN) run python -m unittest -v tests.test_cross_package_extension

test.cross-runtime-extension:
	$(UV_BIN) run python -m unittest -v tests.test_cross_runtime_extension

test.framework-core:
	$(UV_BIN) run python -m unittest -v tests.test_core_only_install

test.cross-language-contracts:
	$(UV_BIN) run python -m unittest -v tests.test_runtime_protocol tests.test_capability_catalog tests.test_capability_package_protocol tests.test_protocol_canonical_ordering
	npm ci --prefix packages/typescript/asterion-runtime
	npm test --prefix packages/typescript/asterion-runtime

test.extension-wheels: test.public-extension test.cross-package-extension test.cross-runtime-extension

test.provider-integration:
	$(UV_BIN) run asterion verify --provider dci-agent-lite --level acceptance

test.framework-provider-free: test.framework-core test.cross-language-contracts test.extension-wheels test.provider-integration

lint:
	$(UV_BIN) run python -m compileall -q src tests tools
	$(UV_BIN) run ruff check src tests tools

docs-check:
	$(UV_BIN) run python tools/check_docs.py

check: test-typescript test lint docs-check check-rust build

promotion-check:
	$(UV_BIN) run python tools/check_promotion.py --npm-cache "$(ASTERION_PROMOTION_NPM_CACHE)" --node-executable "$(ASTERION_PRIME_NODE)"

first-run-check:
	$(UV_BIN) run python -m unittest -v tests.test_setup_pi tests.test_resource_setup tests.test_asterion_dci_verification

setup: sync setup-pi setup-resources-basic

setup-pi:
	bash scripts/setup_pi.sh

check-pi:
	bash scripts/setup_pi.sh --check

setup-resources-basic:
	$(UV_BIN) run --extra setup python tools/setup_resources.py --profile basic

check-resources-basic:
	$(UV_BIN) run python tools/setup_resources.py --profile basic --check

setup-resources-benchmark:
	$(UV_BIN) run --extra setup python tools/setup_resources.py --profile benchmark

check-resources-benchmark:
	$(UV_BIN) run python tools/setup_resources.py --profile benchmark --check

doctor:
	$(UV_BIN) run asterion verify --provider $(ASTERION_PROVIDER) --level preflight --env-file "$(CURDIR)/.env" $(ASTERION_ARGS)

asterion-list:
	$(UV_BIN) run asterion list $(ASTERION_ARGS)

asterion-describe:
	$(UV_BIN) run asterion describe --provider $(ASTERION_PROVIDER) $(ASTERION_ARGS)

asterion-verify-preflight:
	$(UV_BIN) run asterion verify --provider $(ASTERION_PROVIDER) --level preflight $(ASTERION_ARGS)

asterion-verify-basic:
	$(UV_BIN) run asterion verify --provider $(ASTERION_PROVIDER) --level basic $(ASTERION_ARGS)

asterion-verify-acceptance:
	$(UV_BIN) run asterion verify --provider $(ASTERION_PROVIDER) --level acceptance $(ASTERION_ARGS)

asterion-verify-complete:
	$(UV_BIN) run asterion verify --provider $(ASTERION_PROVIDER) --level complete $(ASTERION_ARGS)

asterion-run:
	$(UV_BIN) run asterion run $(ASTERION_ARGS)

dci-list:
	$(UV_BIN) run asterion-dci list $(DCI_ARGS)

dci-describe:
	$(UV_BIN) run asterion-dci describe $(DCI_ARGS)

dci-preflight:
	$(UV_BIN) run asterion-dci preflight $(DCI_ARGS)

dci-basic:
	$(UV_BIN) run asterion-dci basic $(DCI_ARGS)

dci-complete:
	$(UV_BIN) run asterion-dci complete $(DCI_ARGS)

dci-run:
	$(UV_BIN) run asterion-dci run $(DCI_ARGS)

dci-benchmark:
	$(UV_BIN) run asterion-dci benchmark $(DCI_ARGS)

test-typescript:
	npm ci --prefix packages/typescript/asterion-runtime
	npm test --prefix packages/typescript/asterion-runtime
	npm test --prefix packages/typescript/dci-context-extension

test-rust:
	cargo test --manifest-path packages/rust/controlled-executor/Cargo.toml

check-rust: test-rust
	cargo fmt --manifest-path packages/rust/controlled-executor/Cargo.toml -- --check
	cargo clippy --manifest-path packages/rust/controlled-executor/Cargo.toml -- -D warnings

asterion-prime-p1-run:
	@exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p1-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		printf '\''%s\n'\'' '\''[asterion-prime-p1-run] native Asterion-prime fixed small verification'\'' >&2; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --isolated --with "$$1" --with "python-dotenv>=1.0.0" --with "ipython==9.17.1" python -I -m asterion.applications.prime.p1.operator'\'' asterion-prime-p1-run "$$1" "$(CURDIR)" "$(ASTERION_PRIME_PI_ENTRY)"'

# P2 long-context witness: source material stays outside the prompt; the
# model performs one bounded programmatic retrieval/transform through the
# injected ``prime.p2-oracle`` service; the answer oracle passes within the
# caps. Like P1, this is provider-backed and needs operator authorization.
# Corpus path, Pi entry and node are operator-owned resources; the preset
# supplies no provider, model, cost or deadline knob.
#
# Pass values either as `make asterion-prime-p2-run VAR=value` or via the
# shell environment; the ``?=`` defaults fall back to whichever was set.
asterion-prime-p2-run:
	@printf '[asterion-prime-p2-run] native Asterion-prime fixed small verification\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p2-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P2_CORPUS="$$4"; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated --with "$$1" --with "python-dotenv>=1.0.0" --with "ipython==9.17.1" python -I -m asterion.applications.prime.p2.operator'\'' asterion-prime-p2-run "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P2_CORPUS)"'

# ARC root, Pi entry and node are operator-owned resources, exactly like
# ASTERION_PRIME_OPERATOR_ROOT above. The preset supplies no provider, model,
# cost or deadline knob, and it names no checkout layout: the operator exports
# ASTERION_PRIME_ARC_ROOT and ASTERION_PRIME_PI_ENTRY, and the operator module
# rejects the invocation when either is missing or unusable.
asterion-prime-p7-solve:
	@printf '[asterion-prime-p7-solve] native Asterion-prime ARC-AGI-3 first-level solve\n' >&2; \
	@exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_ARC_ROOT="$$3"; export ASTERION_PRIME_PI_ENTRY="$$4"; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --isolated --with "$$1" --with "$$3/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$$3/wheels/arcengine-0.9.3-py3-none-any.whl" --with "python-dotenv>=1.0.0" --with "ipython==9.17.1" python -I -m asterion.applications.prime.p7.operator'\'' asterion-prime-p7-solve "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_ARC_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)"'

# Diagnostic sibling of ``asterion-prime-p2-run``: identical command line,
# without the ``@`` prefix on the orb invocation, so Orb / python stderr
# surfaces to the host terminal for diagnosis only.
asterion-prime-p2-run-verbose:
	@printf '[asterion-prime-p2-run-verbose] native Asterion-prime fixed small verification\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p2-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P2_CORPUS="$$4"; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated --with "$$1" --with "python-dotenv>=1.0.0" --with "ipython==9.17.1" python -I -m asterion.applications.prime.p2.operator'\'' asterion-prime-p2-run "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P2_CORPUS)"'

# P4 cross-generation continuity witness: deterministic fake-worker, two
# Orb invocations against a persistent ASTERION_PRIME_P4_PRIVATE_ROOT. The
# commit-mode invocation seals gen=1 and prints one JSON line; the recover-
# mode invocation opens the same private_root at gen=2 (no new checkpoint
# seal — only the prior's sealed digest is read back) and prints one JSON
# line. The host shell captures both, then ``jq -e`` asserts the six
# continuity invariants:
#
#   1. commit.status == "committed" && commit.checkpoint_sha256 non-null
#   2. recover.status == "recovered" && recover.prior_checkpoint_sha256 non-null
#   3. recover.prior_checkpoint_sha256 == commit.checkpoint_sha256
#   4. recover.new_generation == commit.generation + 1
#   5. recover.result_sha256 != commit.result_sha256  (no-replay witness)
#   6. commit.receipt_sha256 non-null  (recover does not seal a new checkpoint
#      — its output's receipt_sha256 is intentionally null)
#
# Pass values either as `make asterion-prime-p4-run VAR=value` or via the
# shell environment; the ``?=`` defaults fall back to whichever was set.
# Like the other Prime presets, this is provider-backed and needs operator
# authorization. Operator root, PI entry, P4 private root, Orb VM, and
# node are operator-owned; the preset supplies no provider, model, cost,
# or deadline knob.
asterion-prime-p4-run:
	@printf '[asterion-prime-p4-run] native Asterion-prime P4 cross-generation continuity witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p4-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; \
		commit_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P4_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P4_MODE=commit; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p4.operator'\'' asterion-prime-p4-run-commit "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P4_PRIVATE_ROOT)")"; \
		recover_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P4_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P4_MODE=recover; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p4.operator'\'' asterion-prime-p4-run-recover "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P4_PRIVATE_ROOT)")"; \
		[ -n "$$commit_json" ] && [ -n "$$recover_json" ] || { echo "[asterion-prime-p4-run] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$commit_json" | jq -e ".status == \"committed\" and (.checkpoint_sha256 | length) == 64 and (.receipt_sha256 | length) == 64" >/dev/null || { echo "[asterion-prime-p4-run] commit witness failed: $$commit_json" >&2; exit 2; }; \
		echo "$$recover_json" | jq -e ".status == \"recovered\" and (.prior_checkpoint_sha256 | length) == 64" >/dev/null || { echo "[asterion-prime-p4-run] recover witness failed: $$recover_json" >&2; exit 2; }; \
		{ echo "$$commit_json"; echo "$$recover_json"; } | jq -e -s ".[1].prior_checkpoint_sha256 == .[0].checkpoint_sha256 and .[1].new_generation == (.[0].generation + 1) and .[1].result_sha256 != .[0].result_sha256 and .[1].continuation_id == .[0].continuation_id and .[1].worker_identity_sha256 != .[0].worker_identity_sha256" >/dev/null || { echo "[asterion-prime-p4-run] continuity invariants failed: $$recover_json (commit: $$commit_json)" >&2; exit 2; }; \
		echo "[asterion-prime-p4-run] witness passed: gen 1 -> 2, prior_checkpoint_sha256 matches commit checkpoint, result_sha256 differs across modes" >&2'

# Diagnostic sibling of ``asterion-prime-p4-run``: identical command line,
# without the ``@`` prefix on the orb invocation, so Orb / python stderr
# surfaces to the host terminal for diagnosis only.
asterion-prime-p4-run-verbose:
	@printf '[asterion-prime-p4-run-verbose] native Asterion-prime P4 cross-generation continuity witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p4-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P4_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P4_MODE=commit; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p4.operator'\'' asterion-prime-p4-run-commit "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P4_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P4_MODE=recover; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p4.operator'\'' asterion-prime-p4-run-recover "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"'

# P3 cross-runner continuity witness: deterministic fake-worker that
# admits exactly one child at depth 2, joins the child's result back into
# the root receipt, and seals one JSON line. The host shell captures the
# stdout JSON and ``jq -e`` asserts the success invariants:
#
#   1. status == "completed", child_run_id non-null, depth_reached == 2
#   2. child_generation == root_generation + 1
#   3. child_result_sha256 != root_result_sha256 (child did real work)
#   4. joined_result_sha256 non-null, receipt_sha256 non-null,
#      refusal_reason == null
#
# Pass values either as `make asterion-prime-p3-run VAR=value` or via the
# shell environment; the ``?=`` defaults fall back to whichever was set.
# Like the other Prime presets, this is provider-backed and needs operator
# authorization. Operator root, PI entry, P3 private root, Orb VM, and
# node are operator-owned; the preset supplies no provider, model, cost,
# or deadline knob.
asterion-prime-p3-run:
	@printf '[asterion-prime-p3-run] native Asterion-prime P3 cross-runner continuity witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p3-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; \
		success_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P3_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P3_MODE=success; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p3.operator'\'' asterion-prime-p3-run-success "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P3_PRIVATE_ROOT)")"; \
		[ -n "$$success_json" ] || { echo "[asterion-prime-p3-run] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$success_json" | jq -e ".status == \"completed\" and (.child_run_id | length > 0) and (.depth_reached == 2) and (.child_generation == (.root_generation + 1)) and (.child_result_sha256 != .root_result_sha256) and (.joined_result_sha256 | length == 64) and (.receipt_sha256 | length == 64) and (.refusal_reason == null)" >/dev/null || { echo "[asterion-prime-p3-run] witness failed: $$success_json" >&2; exit 2; }; \
		echo "[asterion-prime-p3-run] witness passed: depth 1 -> 2, child_generation = root_generation + 1, child_result_sha256 differs from root_result_sha256, refusal_reason is null" >&2'

# P3 refusal-scenarios witness: re-invokes the operator with
# ``ASTERION_PRIME_P3_MODE=limits``. The operator emits exactly four JSON
# records (depth / concurrency / budget / cancellation), one per line,
# each carrying its ``scenario`` field, ``refusal_reason``, and a non-null
# ``receipt_sha256``. The host shell ``jq -e -s`` slurps all four into
# one array and asserts by index — fixed-position ``.[N]`` lookup dodges
# the make-recipe ``\$`` quoting trap that bit P4's earlier draft (Phase
# 6 commit ``9d1a2bb7``); see ``serene-mixing-cat.md`` §"Critical files".
#
# Pass values either as `make asterion-prime-p3-run-limits VAR=value` or
# via the shell environment; the ``?=`` defaults fall back to whichever
# was set. Like the other Prime presets, this is provider-backed and
# needs operator authorization.
asterion-prime-p3-run-limits:
	@printf '[asterion-prime-p3-run-limits] native Asterion-prime P3 four-refusal-scenarios witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p3-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; \
		limits_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P3_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P3_MODE=limits; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p3.operator'\'' asterion-prime-p3-run-limits "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P3_PRIVATE_ROOT)")"; \
		[ -n "$$limits_json" ] || { echo "[asterion-prime-p3-run-limits] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$limits_json" | jq -e -s "(length == 4) and (.[0].scenario == \"depth\") and (.[0].refusal_reason == \"depth-exceeded\") and (.[1].scenario == \"concurrency\") and (.[1].refusal_reason == \"concurrency-exceeded\") and (.[2].scenario == \"budget\") and (.[2].refusal_reason == \"budget-exceeded\") and (.[3].scenario == \"cancellation\") and (.[3].refusal_reason == \"cancelled\") and (.[0].receipt_sha256 | length == 64) and (.[1].receipt_sha256 | length == 64) and (.[2].receipt_sha256 | length == 64) and (.[3].receipt_sha256 | length == 64)" >/dev/null || { echo "[asterion-prime-p3-run-limits] witness failed: $$limits_json" >&2; exit 2; }; \
		echo "[asterion-prime-p3-run-limits] witness passed: depth / concurrency / budget / cancellation refusals, each with refusal_reason and receipt_sha256" >&2'

# Diagnostic sibling of ``asterion-prime-p3-run`` + ``-limits``: identical
# command line, without the ``@`` prefix on the orb invocation, so Orb /
# python stderr surfaces to the host terminal for diagnosis only.
asterion-prime-p3-run-verbose:
	@printf '[asterion-prime-p3-run-verbose] native Asterion-prime P3 cross-runner continuity witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p3-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P3_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P3_MODE=success; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p3.operator'\'' asterion-prime-p3-run-success "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P3_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P3_MODE=limits; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p3.operator'\'' asterion-prime-p3-run-limits "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"'

test.native-controller-core.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_native_control_model \
		tests.test_native_control_store \
		tests.test_native_control_capsule \
		tests.test_native_control_controller \
		tests.test_native_control_client \
		tests.test_native_control_factory \
		tests.test_native_control_conformance \
		tests.test_native_control_host \
		tests.test_native_prime_differential \
		tests.test_native_control_process_recovery \
		tests.test_native_controller_core_verification

.PHONY: test.native-verified-loop.provider-free
test.native-verified-loop.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_native_verified_features \
		tests.test_native_verified_differential \
		tests.test_native_verified_loop_verification
	$(UV_BIN) run python tools/verify_native_verified_loop.py --level provider-free

.PHONY: verify.native-verified-loop.bounded
verify.native-verified-loop.bounded:
	@echo "Use explicit verifier with an operator-approved reservation; this target does not execute a provider."
	@exit 1

.PHONY: verify.native-verified-loop.small
verify.native-verified-loop.small:
	$(UV_BIN) run python tools/verify_native_verified_loop.py --level small-verification

dci-basic-example:
	bash examples/asterion_dci_basic_example.sh

dci-runtime-context-example:
	bash examples/asterion_dci_runtime_context_example.sh
