UV_BIN ?= uv
ASTERION_PROVIDER ?= dci-agent-lite
ASTERION_ARGS ?=
DCI_ARGS ?=
ASTERION_PRIME_SOURCE_ROOT ?= 3th-party/prime-agent
ASTERION_PRIME_AUTHORITY ?=
ASTERION_PRIME_MAX_COST_MICROS ?=

.DEFAULT_GOAL := help

.PHONY: help sync build test lint docs-check check promotion-check first-run-check
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
.PHONY: prime-check prime-setup prime-verify-provider-free prime-verify-bounded prime-verify-native-rlm-bounded
.PHONY: prime-parity-inventory prime-verify-system-parity
.PHONY: test.prime-session-context-parity.provider-free test.prime-rlm-spawn-admission.provider-free
.PHONY: test.prime-continual-harness.provider-free
.PHONY: test.prime-continual-harness.bounded
.PHONY: test.prime-ecosystem-resources.provider-free
.PHONY: test.prime-ecosystem-extensions.provider-free
.PHONY: test.prime-ecosystem-packages.provider-free
.PHONY: test.prime-ecosystem-mcp.provider-free

help:
	@echo "provider-free setup (network/disk; Agent operations 0; Judge operations 0): setup setup-pi setup-resources-basic setup-resources-benchmark"
	@echo "provider-free checks: check-pi check-resources-basic check-resources-benchmark doctor first-run-check"
	@echo "provider-free lifecycle: sync build test lint docs-check check promotion-check"
	@echo "provider-free framework: asterion-list asterion-describe asterion-verify-preflight asterion-verify-acceptance"
	@echo "bounded provider-backed: asterion-verify-basic asterion-verify-complete asterion-run"
	@echo "DCI adapter: dci-list dci-describe dci-preflight dci-basic dci-complete dci-run dci-benchmark"
	@echo "DCI bounded examples: dci-basic-example dci-runtime-context-example"
	@echo "Cross-language provider-free: test-typescript test-rust check-rust"
	@echo "Prime Gateway: prime-check prime-setup prime-verify-provider-free prime-verify-bounded prime-parity-inventory prime-verify-system-parity test.prime-session-context-parity.provider-free test.prime-rlm-spawn-admission.provider-free"
	@echo "Cost boundary: full execution requires separate authorization"
	@echo "Arguments: ASTERION_ARGS='...' or DCI_ARGS='...'"

sync:
	$(UV_BIN) sync --frozen

build:
	$(UV_BIN) build .

test:
	$(UV_BIN) run python -m unittest discover -s tests -v

lint:
	$(UV_BIN) run python -m compileall -q src tests tools
	$(UV_BIN) run ruff check src tests tools

docs-check:
	$(UV_BIN) run python tools/check_docs.py

check: test lint docs-check test-typescript check-rust build

promotion-check:
	$(UV_BIN) run python tools/check_promotion.py

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

prime-check:
	$(UV_BIN) run python tools/setup_prime_agent.py --check --source-root "$(ASTERION_PRIME_SOURCE_ROOT)"

prime-setup:
	$(UV_BIN) run python tools/setup_prime_agent.py --source-root "$(ASTERION_PRIME_SOURCE_ROOT)"

prime-verify-provider-free:
	$(UV_BIN) run python tools/verify_prime_loop.py --level provider-free

test.prime-session-context-parity.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_session_context_protocol \
		tests.test_session_context_manager \
		tests.test_prime_session_context_parity \
		tests.test_prime_parity_conformance
	npm --prefix packages/typescript/asterion-runtime test
	npm --prefix packages/typescript/prime-gateway test

test.prime-rlm-spawn-admission.provider-free:
	npm --prefix packages/typescript/prime-gateway test -- \
		test/daemon-wire.test.mjs \
		test/rlm-host-shim.test.mjs
	$(UV_BIN) run python -m unittest -v \
		tests.test_prime_rlm_messaging_parity

test.prime-continual-harness.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_control_harness \
		tests.test_prime_continual_harness \
		tests.test_prime_continual_harness_parity
	npm --prefix packages/typescript/prime-gateway test -- test/continual-harness.test.mjs

test.prime-continual-harness.bounded:
	$(UV_BIN) run python tools/prime_continual_harness_experiment.py \
		--authorized-bounded-provider \
		--source-root 3th-party/prime-agent \
		--private-evidence-root .asterion-private/prime-continual-harness

test.prime-ecosystem-resources.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_control_ecosystem \
		tests.test_control_ecosystem_materialization \
		tests.test_prime_ecosystem_resources

test.prime-ecosystem-extensions.provider-free:
	$(UV_BIN) run python -m unittest -v tests.test_prime_ecosystem_extensions
	npm --prefix packages/typescript/prime-gateway test -- test/ecosystem.test.mjs

test.prime-ecosystem-packages.provider-free:
	npm --prefix packages/typescript/prime-gateway run build
	$(UV_BIN) run python -m unittest -v \
		tests.test_prime_ecosystem_packages \
		tests.test_local_capability_source \
		tests.test_distribution_capability_source


test.prime-ecosystem-mcp.provider-free:
	npm --prefix packages/typescript/prime-gateway run build
	$(UV_BIN) run python -m unittest -v \
		tests.test_control_ecosystem_mcp \
		tests.test_prime_ecosystem_mcp

prime-verify-bounded:
	$(UV_BIN) run python tools/verify_prime_loop.py --level bounded --source-root "$(ASTERION_PRIME_SOURCE_ROOT)" --authority "$(ASTERION_PRIME_AUTHORITY)" --max-cost-micros "$(ASTERION_PRIME_MAX_COST_MICROS)"

prime-verify-native-rlm-bounded:
	$(UV_BIN) run python tools/verify_prime_loop.py --level native-rlm-bounded --native-rlm-experiment --source-root "$(ASTERION_PRIME_SOURCE_ROOT)"

prime-parity-inventory:
	$(UV_BIN) run python tools/check_prime_parity.py --claim inventory

prime-verify-system-parity:
	$(UV_BIN) run python tools/check_prime_parity.py --claim verified-system-parity

dci-basic-example:
	bash examples/asterion_dci_basic_example.sh

dci-runtime-context-example:
	bash examples/asterion_dci_runtime_context_example.sh
