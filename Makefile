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
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --isolated --with "$$1" --with "python-dotenv>=1.0.0" --with "ipython==9.17.1" python -I -m asterion.applications.prime.p1.operator'\'' asterion-prime-p1-run "$$1" "$(CURDIR)"'

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
