UV_BIN ?= uv
ASTERION_PROVIDER ?= dci-agent-lite
ASTERION_ARGS ?=
DCI_ARGS ?=
ASTERION_PRIME_SOURCE_ROOT ?= 3th-party/prime-agent
ASTERION_PRIME_AUTHORITY ?=
ASTERION_PRIME_MAX_COST_MICROS ?=
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
.PHONY: prime-check prime-setup prime-verify-provider-free prime-verify-bounded prime-verify-native-rlm-bounded prime-readme-rlm-smoke prime-smoke-core
.PHONY: prime-parity-inventory prime-verify-system-parity
.PHONY: prime-p1-run prime-p2-run prime-p3-run prime-p4-run prime-p5-run prime-p6-run prime-p7-run
.PHONY: test.prime-session-context-parity.provider-free test.prime-rlm-spawn-admission.provider-free
.PHONY: test.prime-long-running.provider-free test.prime-long-running.bounded
.PHONY: test.prime-continual-harness.provider-free
.PHONY: test.prime-continual-harness.bounded
.PHONY: test.prime-ecosystem-resources.provider-free
.PHONY: test.prime-ecosystem-extensions.provider-free
.PHONY: test.prime-ecosystem-packages.provider-free
.PHONY: test.prime-ecosystem-mcp.provider-free
.PHONY: test.prime-client-core.provider-free
.PHONY: test.prime-client-protocols.provider-free
.PHONY: test.prime-client-interactive.provider-free
.PHONY: test.prime-client-export-share.provider-free
.PHONY: test.prime-client-parity.provider-free
.PHONY: test.prime-operational-auth.provider-free test.prime-operational-telemetry-usage.provider-free test.prime-operational-doctor.provider-free test.prime-operational-controlled-update-restart.provider-free
.PHONY: test.prime-operational-harness.provider-free test.prime-operational-parity.provider-free
.PHONY: test.native-controller-core.provider-free

help:
	@echo "provider-free setup (network/disk; Agent operations 0; Judge operations 0): setup setup-pi setup-resources-basic setup-resources-benchmark"
	@echo "provider-free checks: check-pi check-resources-basic check-resources-benchmark doctor first-run-check"
	@echo "layered provider-free: test.framework-core test.cross-language-contracts test.extension-wheels test.provider-integration test.framework-provider-free"
	@echo "bounded presets: asterion-verify-basic asterion-verify-complete dci-basic dci-complete prime-verify-bounded prime-p1-run ... prime-p7-run"
	@echo "operator-authorized run/benchmark: asterion-run dci-run dci-benchmark"
	@echo "full regression: check promotion-check"
	@echo "provider-free lifecycle: sync build test lint docs-check"
	@echo "framework acceptance: test.core-only test.public-extension test.cross-package-extension test.cross-runtime-extension"
	@echo "provider-free framework: asterion-list asterion-describe asterion-verify-preflight asterion-verify-acceptance"
	@echo "bounded provider-backed presets: asterion-verify-basic asterion-verify-complete"
	@echo "DCI adapter: dci-list dci-describe dci-preflight dci-basic dci-complete dci-run dci-benchmark"
	@echo "DCI bounded examples: dci-basic-example dci-runtime-context-example"
	@echo "Cross-language provider-free: test-typescript test-rust check-rust"
	@echo "Prime Gateway: prime-check prime-setup prime-verify-provider-free prime-verify-bounded prime-readme-rlm-smoke prime-smoke-core prime-parity-inventory prime-verify-system-parity test.prime-session-context-parity.provider-free test.prime-rlm-spawn-admission.provider-free test.prime-long-running.provider-free test.prime-long-running.bounded"
	@echo "Prime development execution (Orb Ubuntu): prime-p1-run prime-p2-run prime-p3-run prime-p4-run prime-p5-run prime-p6-run prime-p7-run"
	@echo "Cost boundary: full execution requires separate authorization"
	@echo "Arguments: ASTERION_ARGS='...' or DCI_ARGS='...'"

sync:
	$(UV_BIN) sync --frozen

build:
	$(UV_BIN) build .

test:
	$(UV_BIN) run python -m unittest discover -s tests -v

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
	ASTERION_PRIME_SOURCE_ROOT="$(ASTERION_PRIME_SOURCE_ROOT)" $(UV_BIN) run python tools/check_promotion.py --npm-cache "$(ASTERION_PROMOTION_NPM_CACHE)" --node-executable "$(ASTERION_PRIME_NODE)"

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
	npm ci --prefix packages/typescript/prime-gateway
	npm --prefix packages/typescript/prime-gateway run build

test-rust:
	cargo test --manifest-path packages/rust/controlled-executor/Cargo.toml

check-rust: test-rust
	cargo fmt --manifest-path packages/rust/controlled-executor/Cargo.toml -- --check
	cargo clippy --manifest-path packages/rust/controlled-executor/Cargo.toml -- -D warnings

prime-check:
	ASTERION_PRIME_NODE="$(ASTERION_PRIME_NODE)" $(UV_BIN) run python tools/setup_prime_agent.py --check --node-executable "$(ASTERION_PRIME_NODE)" --source-root "$(ASTERION_PRIME_SOURCE_ROOT)"

prime-setup:
	ASTERION_PRIME_NODE="$(ASTERION_PRIME_NODE)" $(UV_BIN) run python tools/setup_prime_agent.py --node-executable "$(ASTERION_PRIME_NODE)" --source-root "$(ASTERION_PRIME_SOURCE_ROOT)"

prime-verify-provider-free:
	$(UV_BIN) run python tools/verify_prime_loop.py --level provider-free

prime-p1-run:
	@run_id="$${PRIME_RUN_ID:-prime-p1-$$(date -u +%Y%m%d%H%M%S)-$$$$}"; \
		exec orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)" /root/.local/bin/uv run --python /usr/bin/python3 --isolated asterion run \
			--provider prime-agent \
			--application prime.ipython-coding@1.0.0 \
			--runtime prime.agent \
			--run-id "$$run_id" \
			--input fixed-small-verification

prime-p2-run:
	@run_id="$${PRIME_RUN_ID:-prime-p2-$$(date -u +%Y%m%d%H%M%S)-$$$$}"; \
		exec orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)" /root/.local/bin/uv run --python /usr/bin/python3 --isolated asterion run \
			--provider prime-agent \
			--application prime.programmatic-long-context@1.0.0 \
			--runtime prime.agent \
			--run-id "$$run_id" \
			--input fixed-small-verification

prime-p3-run:
	@run_id="$${PRIME_RUN_ID:-prime-p3-$$(date -u +%Y%m%d%H%M%S)-$$$$}"; \
		exec orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)" /root/.local/bin/uv run --python /usr/bin/python3 --isolated asterion run \
			--provider prime-agent \
			--application prime.recursive-workflow@1.0.0 \
			--runtime prime.agent \
			--run-id "$$run_id" \
			--input fixed-small-verification

prime-p4-run:
	@run_id="$${PRIME_RUN_ID:-prime-p4-$$(date -u +%Y%m%d%H%M%S)-$$$$}"; \
		exec orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)" /root/.local/bin/uv run --python /usr/bin/python3 --isolated asterion run \
			--provider prime-agent \
			--application prime.long-session-continuity@1.0.0 \
			--runtime prime.agent \
			--run-id "$$run_id" \
			--input fixed-small-verification

prime-p5-run:
	@run_id="$${PRIME_RUN_ID:-prime-p5-$$(date -u +%Y%m%d%H%M%S)-$$$$}"; \
		exec orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)" /root/.local/bin/uv run --python /usr/bin/python3 --isolated asterion run \
			--provider prime-agent \
			--application prime.bounded-autonomy@1.0.0 \
			--runtime prime.agent \
			--run-id "$$run_id" \
			--input fixed-small-verification

prime-p6-run:
	@run_id="$${PRIME_RUN_ID:-prime-p6-$$(date -u +%Y%m%d%H%M%S)-$$$$}"; \
		exec orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)" /root/.local/bin/uv run --python /usr/bin/python3 --isolated asterion run \
			--provider prime-agent \
			--application prime.continual-improvement@1.0.0 \
			--runtime prime.agent \
			--run-id "$$run_id" \
			--input fixed-small-verification

prime-p7-run:
	@run_id="$${PRIME_RUN_ID:-prime-p7-$$(date -u +%Y%m%d%H%M%S)-$$$$}"; \
		exec orb -m "$(PRIME_ORB_MACHINE)" -u root -w "$(CURDIR)" /root/.local/bin/uv run --python /usr/bin/python3 --isolated asterion run \
			--provider prime-agent \
			--application prime.arc-agi-3@1.0.0 \
			--runtime prime.agent \
			--run-id "$$run_id" \
			--input fixed-small-verification

test.prime-session-context-parity.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_session_context_protocol \
		tests.test_session_context_manager \
		tests.test_prime_session_context_parity \
		tests.test_prime_parity_conformance
	npm --prefix packages/typescript/asterion-runtime test
	npm --prefix packages/typescript/prime-gateway test

test.prime-session-context-parity.bounded:
	ASTERION_PRIME_SESSION_CONTEXT_BOUNDED=1 $(UV_BIN) run python -m unittest -v \
		tests.test_prime_session_context_parity.TestPrimeSessionContextParity.test_real_prime_provider_free_scenarios_match_committed_evidence

test.prime-rlm-spawn-admission.provider-free:
	npm --prefix packages/typescript/prime-gateway test -- \
		test/daemon-wire.test.mjs \
		test/rlm-host-shim.test.mjs
	$(UV_BIN) run python -m unittest -v \
		 tests.test_prime_rlm_messaging_parity

test.prime-long-running.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_control_long_running \
		tests.test_prime_long_running_experiment \
		tests.test_prime_long_running_parity
	npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs

test.prime-long-running.bounded:
	$(UV_BIN) run python tools/prime_long_running_experiment.py \
		--authorized-bounded-provider \
		--source-root "$(ASTERION_PRIME_SOURCE_ROOT)"

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

test.prime-client-core.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_client_sdk_jsonl \
		tests.test_prime_client_core

test.prime-client-protocols.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_client_rpc_acp \
		tests.test_prime_client_protocols

test.prime-client-interactive.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_client_interactive \
		tests.test_asterion_cli \
		tests.test_prime_client_interactive

test.prime-client-export-share.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_client_export_share \
		tests.test_prime_client_export_share

test.prime-client-parity.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_prime_client_parity \
		tests.test_prime_parity_ledger \
		tests.test_check_prime_parity
	$(UV_BIN) run python tools/check_prime_parity.py \
		--features interface.sdk,interface.cli-interactive,interface.rpc,interface.acp,interface.json-stream,interface.headless-print,interface.tui-commands,interface.tui-extension-ui,interface.export-share \
		--provider asterion.prime-gateway

test.prime-operational-auth.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_operation_auth \
		tests.test_prime_operational_auth
	npm --prefix packages/typescript/asterion-runtime test
	npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs

test.prime-operational-harness.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_prime_operation_bridge \
		tests.test_prime_operational_harness
	npm --prefix packages/typescript/prime-gateway test -- \
		test/operational-interface.test.mjs \
		test/main.test.mjs

test.prime-operational-telemetry-usage.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_operation_telemetry \
		tests.test_prime_operational_telemetry
	npm --prefix packages/typescript/asterion-runtime test
	npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs

test.prime-operational-doctor.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_operation_doctor \
		tests.test_prime_operational_doctor
	npm --prefix packages/typescript/asterion-runtime test
	npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs

test.prime-operational-controlled-update-restart.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_operation_update_restart \
		tests.test_prime_operational_update_restart
	npm --prefix packages/typescript/asterion-runtime test
	npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs

.PHONY: test.prime-operational-model-selection.provider-free
test.prime-operational-model-selection.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_operation_model_selection \
		tests.test_prime_operational_model_selection
	npm --prefix packages/typescript/asterion-runtime test
	npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs

.PHONY: test.prime-operational-settings-keybindings.provider-free
test.prime-operational-settings-keybindings.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_operation_settings \
		tests.test_prime_operational_settings
	npm --prefix packages/typescript/asterion-runtime test
	npm --prefix packages/typescript/prime-gateway test -- test/operational-interface.test.mjs

test.prime-operational-parity.provider-free:
	$(UV_BIN) run python -m unittest -v \
		tests.test_prime_operational_parity \
		tests.test_prime_parity_ledger \
		tests.test_check_prime_parity
	$(UV_BIN) run python tools/check_prime_parity.py \
		--features operation.auth,operation.model-selection,operation.settings-keybindings,operation.telemetry-usage,operation.doctor,operation.controlled-update-restart \
		--provider asterion.prime-gateway

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

prime-verify-bounded:
	$(UV_BIN) run python tools/verify_prime_loop.py --level bounded --source-root "$(ASTERION_PRIME_SOURCE_ROOT)" $(if $(ASTERION_PRIME_AUTHORITY),--authority "$(ASTERION_PRIME_AUTHORITY)") $(if $(ASTERION_PRIME_MAX_COST_MICROS),--max-cost-micros "$(ASTERION_PRIME_MAX_COST_MICROS)")

prime-verify-native-rlm-bounded:
	$(UV_BIN) run python tools/verify_prime_loop.py --level native-rlm-bounded --native-rlm-experiment --source-root "$(ASTERION_PRIME_SOURCE_ROOT)"

prime-readme-rlm-smoke:
	$(UV_BIN) run python -m tools.run_prime_readme_smoke

prime-smoke-core:
	ASTERION_PRIME_NODE="$(ASTERION_PRIME_NODE)" $(UV_BIN) run python -m tools.run_prime_core_smoke

prime-parity-inventory:
	$(UV_BIN) run python tools/check_prime_parity.py --claim inventory

prime-verify-system-parity:
	$(UV_BIN) run python tools/check_prime_parity.py --claim verified-system-parity

dci-basic-example:
	bash examples/asterion_dci_basic_example.sh

dci-runtime-context-example:
	bash examples/asterion_dci_runtime_context_example.sh
