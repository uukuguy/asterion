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
.PHONY: asterion-prime-p4-witness
.PHONY: asterion-prime-p4-run-verbose
.PHONY: asterion-prime-p3-run
.PHONY: asterion-prime-p3-witness
.PHONY: asterion-prime-p3-run-limits
.PHONY: asterion-prime-p3-run-verbose
.PHONY: asterion-prime-p5-run
.PHONY: asterion-prime-p5-witness
.PHONY: asterion-prime-p5-run-limits
.PHONY: asterion-prime-p5-run-verbose
.PHONY: asterion-prime-p6-run
.PHONY: asterion-prime-p6-witness
.PHONY: asterion-prime-p6-run-limits
.PHONY: asterion-prime-p6-run-verbose
.PHONY: asterion-prime-p7-solve
.PHONY: asterion-prime-p7-level-witness
.PHONY: asterion-prime-p7-sweep
.PHONY: asterion-prime-p7-first-round
.PHONY: asterion-prime-p7-second-round
.PHONY: asterion-prime-p7-sweep-attempt
.PHONY: asterion-prime-p7-games
.PHONY: asterion-prime-p7-stories
.PHONY: asterion-prime-p7-sync-games
.PHONY: asterion-prime-p7-official-preflight
.PHONY: asterion-prime-p7-official-submit
.PHONY: asterion-prime-p7-official-recover
.PHONY: asterion-prime-p7-official-live-eval

# Operator-owned values for the Prime presets. The P7 research assets live
# beside this checkout; the operator preflight rejects missing assets.
ASTERION_PRIME_PI_ENTRY ?= /mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js
ASTERION_PRIME_OPERATOR_ROOT ?= $(CURDIR)
ASTERION_PRIME_P2_CORPUS ?= $(CURDIR)/tests/fixtures/prime_p2/small_corpus.json
ASTERION_PRIME_ARC_ROOT := $(abspath $(CURDIR)/../external-prime/arc-agi-3)
ASTERION_PRIME_P4_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p4-witness
ASTERION_PRIME_P4_LIVE_ROOT ?= $(CURDIR)/.asterion-private/prime-p4-live
ASTERION_PRIME_P3_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p3-witness
ASTERION_PRIME_LOCAL_PI_ENTRY ?= /opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js
ASTERION_PRIME_P3_LIVE_ROOT ?= $(CURDIR)/.asterion-private/prime-p3-live
ASTERION_PRIME_P5_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p5-witness
ASTERION_PRIME_P5_LIVE_ROOT ?= $(CURDIR)/.asterion-private/prime-p5-live
ASTERION_PRIME_P6_PRIVATE_ROOT ?= $(CURDIR)/.asterion-private/prime-p6-witness
ASTERION_PRIME_P6_LIVE_ROOT ?= $(CURDIR)/.asterion-private/prime-p6-live
# The application catalog validates GAME aliases and exact IDs from local metadata.
# ls20-9607627b
# tu93-0768757b
GAME ?= tu93
ASTERION_PRIME_P7_GAME_ID := $(GAME)
RUN ?=
export ASTERION_PRIME_P7_RECOVERY_RUN := $(RUN)
ifneq ($(filter asterion-prime-p7-official-submit,$(MAKECMDGOALS)),)
ifneq ($(origin GAME),command line)
$(error asterion-prime-p7-official-submit requires GAME=<alias-or-all>)
endif
endif
LEVEL ?= 1
ASTERION_PRIME_P7_TARGET_LEVEL := $(LEVEL)
ASTERION_PRIME_P7_SEED := 0
ASTERION_PRIME_P7_LEVEL_EXPLICIT := $(if $(filter command line,$(origin LEVEL)),1,0)

# P7 selection is forwarded through Orb by variable name, never by expanding
# an operator-supplied value into its command line.
export ASTERION_PRIME_P7_GAME_ID
export ASTERION_PRIME_P7_TARGET_LEVEL
export ASTERION_PRIME_P7_SEED
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
	@echo "Asterion Prime bounded live applications: asterion-prime-p3-run p4-run p5-run p6-run"
	@echo "Asterion Prime ARC-AGI-3 solve: asterion-prime-p7-solve GAME=<alias-or-exact-id> [LEVEL=N] (default: tu93)"
	@echo "Asterion Prime local ARC-AGI-3 breadth sweep: asterion-prime-p7-sweep"
	@echo "Asterion Prime authorized unbounded local L1 sweep: asterion-prime-p7-first-round"
	@echo "Asterion Prime local L2 sweep of verified L1 games: asterion-prime-p7-second-round"
	@echo "Asterion Prime ARC-AGI-3 partial witness: asterion-prime-p7-level-witness GAME=<alias-or-exact-id> LEVEL=N"
	@echo "Asterion Prime local ARC-AGI-3 games and verified progress: asterion-prime-p7-games"
	@echo "Asterion Prime local ARC-AGI-3 solved-game story pages: asterion-prime-p7-stories"
	@echo "Asterion Prime sync official public games without a scorecard: asterion-prime-p7-sync-games"
	@echo "Asterion Prime official ARC-AGI-3 catalog readiness: asterion-prime-p7-official-preflight"
	@echo "Asterion Prime submit saved verified actions: asterion-prime-p7-official-submit GAME=<alias-or-all>"
	@echo "Asterion Prime read-only closed-card recovery: asterion-prime-p7-official-recover RUN=<run-id>"
	@echo "Asterion Prime full-catalog model evaluation: asterion-prime-p7-official-live-eval"
	@echo "Asterion Prime deterministic diagnostics: asterion-prime-p3-witness p4-witness p5-witness p6-witness"
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

# The default P7 target selects the prepared next game and its sibling asset
# root. The operator rejects missing or unusable assets before a model run.
asterion-prime-p7-games:
	@PYTHONPATH="$(CURDIR)/src" python3 tools/list_prime_p7_games.py --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --runs-root "$(CURDIR)/.asterion-private/prime-p7-live"

asterion-prime-p7-stories:
	@$(UV_BIN) run asterion arc-story serve --open-browser

asterion-prime-p7-sync-games:
	@python3 tools/sync_prime_p7_games.py --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --env-file "$(CURDIR)/.env"

asterion-prime-p7-sweep:
	@exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		$(UV_BIN) run --no-project --isolated --with "$$1" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arcengine-0.9.3-py3-none-any.whl" python -I tools/run_prime_p7_sweep.py --operator-root "$(CURDIR)" --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --guest-machine "$(PRIME_ORB_MACHINE)"'

asterion-prime-p7-first-round:
	@printf '[asterion-prime-p7-first-round] authorized local L1 campaign; 30 minutes per game, no total token or time cap\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		$(UV_BIN) run --no-project --isolated --with "$$1" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arcengine-0.9.3-py3-none-any.whl" python -I tools/run_prime_p7_sweep.py --operator-root "$(CURDIR)" --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --guest-machine "$(PRIME_ORB_MACHINE)" --unbounded-first-round'

asterion-prime-p7-second-round:
	@printf '[asterion-prime-p7-second-round] local L2 campaign; 30 minutes per game, no total token or time cap\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		$(UV_BIN) run --no-project --isolated --with "$$1" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$(ASTERION_PRIME_ARC_ROOT)/wheels/arcengine-0.9.3-py3-none-any.whl" python -I tools/run_prime_p7_sweep.py --operator-root "$(CURDIR)" --arc-root "$(ASTERION_PRIME_ARC_ROOT)" --guest-machine "$(PRIME_ORB_MACHINE)" --unbounded-second-round'

asterion-prime-p7-solve asterion-prime-p7-level-witness asterion-prime-p7-sweep-attempt:
	@exec /bin/sh -ec 'if [ "$@" = asterion-prime-p7-level-witness ] || [ "$@" = asterion-prime-p7-sweep-attempt ] || [ "$(ASTERION_PRIME_P7_LEVEL_EXPLICIT)" = 1 ]; then case "$$ASTERION_PRIME_P7_TARGET_LEVEL" in '\''\'\''|*[^0-9]*|0) printf '\''[$@] LEVEL must be a positive integer; got %s\n'\'' "$$ASTERION_PRIME_P7_TARGET_LEVEL" >&2; exit 2 ;; esac; fi; \
		printf '\''[$@] native Asterion-prime ARC-AGI-3 %s\n'\'' "$$(if [ "$@" = asterion-prime-p7-solve ]; then printf full-game-solve; else printf level-witness; fi)" >&2; \
		build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		orb() { if [ "$$ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND" = 1 ]; then ORBENV="$$ORBENV:ASTERION_PRIME_P7_UNBOUNDED_FIRST_ROUND:OPERATION_MODE"; export ORBENV; fi; command orb "$$@"; }; \
		ORBENV="ASTERION_PRIME_P7_GAME_ID:ASTERION_PRIME_P7_SEED:ASTERION_PRIME_P7_RUN_MODE:ASTERION_PRIME_P7_ATTEMPT_UNIT:ASTERION_PRIME_P7_ATTEMPT_SECONDS"; ASTERION_PRIME_P7_RUN_MODE=solve; if [ "$@" = asterion-prime-p7-level-witness ]; then ASTERION_PRIME_P7_RUN_MODE=witness; fi; if [ "$@" = asterion-prime-p7-sweep-attempt ]; then ASTERION_PRIME_P7_RUN_MODE=sweep; fi; if [ "$@" = asterion-prime-p7-level-witness ] || [ "$@" = asterion-prime-p7-sweep-attempt ] || [ "$(ASTERION_PRIME_P7_LEVEL_EXPLICIT)" = 1 ]; then ORBENV="$$ORBENV:ASTERION_PRIME_P7_TARGET_LEVEL"; fi; export ORBENV ASTERION_PRIME_P7_RUN_MODE; orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_ARC_ROOT="$$3"; export ASTERION_PRIME_PI_ENTRY="$$4"; export ASTERION_PRIME_P7_GAME_ID ASTERION_PRIME_P7_SEED ASTERION_PRIME_P7_RUN_MODE; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; set -- /root/.local/bin/uv run --isolated --with "$$1" --with "$$3/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$$3/wheels/arcengine-0.9.3-py3-none-any.whl" --with "python-dotenv>=1.0.0" --with "ipython==9.17.1" python -I -m asterion.applications.prime.p7.operator; if [ "$$ASTERION_PRIME_P7_RUN_MODE" = sweep ]; then exec python3 "$$ASTERION_PRIME_OPERATOR_ROOT/tools/run_prime_p7_guest.py" launch --unit "$$ASTERION_PRIME_P7_ATTEMPT_UNIT" --seconds "$$ASTERION_PRIME_P7_ATTEMPT_SECONDS" -- "$$@"; fi; exec "$$@"'\'' "$@" "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_ARC_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)"'

asterion-prime-p7-official-preflight asterion-prime-p7-official-submit asterion-prime-p7-official-live-eval:
	@exec /bin/sh -ec 'printf '\''[$@] official ARC-AGI-3 %s\n'\'' "$$(if [ "$@" = asterion-prime-p7-official-preflight ]; then printf preflight; else printf scorecard-run; fi)" >&2; \
		build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		case "$@" in asterion-prime-p7-official-preflight) ASTERION_PRIME_P7_OFFICIAL_MODE=preflight ;; asterion-prime-p7-official-submit) ASTERION_PRIME_P7_OFFICIAL_MODE=saved-submit ;; *) ASTERION_PRIME_P7_OFFICIAL_MODE=live-eval ;; esac; export ASTERION_PRIME_P7_OFFICIAL_MODE; ORBENV=ASTERION_PRIME_P7_OFFICIAL_MODE; if [ "$$ASTERION_PRIME_P7_OFFICIAL_MODE" = saved-submit ]; then ORBENV="$$ORBENV:ASTERION_PRIME_P7_GAME_ID"; fi; export ORBENV; \
		orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_ARC_ROOT="$$3"; export ASTERION_PRIME_P7_OFFICIAL_MODE; if [ "$$ASTERION_PRIME_P7_OFFICIAL_MODE" = live-eval ]; then export ASTERION_PRIME_PI_ENTRY="$$4"; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; fi; exec /root/.local/bin/uv run --isolated --with "$$1" --with "$$3/wheels/arc_agi-0.9.9-py3-none-any.whl" --with "$$3/wheels/arcengine-0.9.3-py3-none-any.whl" --with "python-dotenv>=1.0.0" --with "ipython==9.17.1" python -I -m asterion.applications.prime.p7.official_operator'\'' "$@" "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_ARC_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)"'

asterion-prime-p7-official-recover:
	@exec /bin/sh -ec 'case "$$ASTERION_PRIME_P7_RECOVERY_RUN" in ""|*[!A-Za-z0-9_-]*) printf '\''[asterion-prime-p7-official-recover] RUN must be a run ID\n'\'' >&2; exit 2 ;; esac; \
		build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p7-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		$(UV_BIN) run --isolated --with "$$1" python -I -m asterion.applications.prime.p7.official_recovery "$(abspath $(ASTERION_PRIME_OPERATOR_ROOT))/.asterion-private/prime-p7-official/$$ASTERION_PRIME_P7_RECOVERY_RUN/official-recovery.json"'

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
asterion-prime-p4-witness:
	@printf '[asterion-prime-p4-witness] native Asterion-prime P4 cross-generation continuity witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p4-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P4_PRIVATE_ROOT)"; \
		commit_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P4_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P4_MODE=commit; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p4.operator'\'' asterion-prime-p4-run-commit "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P4_PRIVATE_ROOT)")"; \
		recover_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P4_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P4_MODE=recover; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p4.operator'\'' asterion-prime-p4-run-recover "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P4_PRIVATE_ROOT)")"; \
		[ -n "$$commit_json" ] && [ -n "$$recover_json" ] || { echo "[asterion-prime-p4-witness] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$commit_json" | jq -e ".status == \"committed\" and (.checkpoint_sha256 | length) == 64 and (.receipt_sha256 | length) == 64" >/dev/null || { echo "[asterion-prime-p4-witness] commit witness failed: $$commit_json" >&2; exit 2; }; \
		echo "$$recover_json" | jq -e ".status == \"recovered\" and (.prior_checkpoint_sha256 | length) == 64" >/dev/null || { echo "[asterion-prime-p4-witness] recover witness failed: $$recover_json" >&2; exit 2; }; \
		{ echo "$$commit_json"; echo "$$recover_json"; } | jq -e -s ".[1].prior_checkpoint_sha256 == .[0].checkpoint_sha256 and .[1].new_generation == (.[0].generation + 1) and .[1].result_sha256 != .[0].result_sha256 and .[1].continuation_id == .[0].continuation_id and .[1].worker_identity_sha256 != .[0].worker_identity_sha256" >/dev/null || { echo "[asterion-prime-p4-witness] continuity invariants failed: $$recover_json (commit: $$commit_json)" >&2; exit 2; }; \
		echo "[asterion-prime-p4-witness] witness passed: gen 1 -> 2, prior_checkpoint_sha256 matches commit checkpoint, result_sha256 differs across modes" >&2'

# Commit and recover run in separate installed-wheel processes. The checkpoint
# and both private transcripts remain under the per-run local evidence root.
asterion-prime-p4-run:
	@printf '[asterion-prime-p4-run] bounded live P4 commit/recover verification\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p4-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		mkdir -p "$(ASTERION_PRIME_P4_LIVE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P4_LIVE_ROOT)"; \
		pair_dir="$$(mktemp -d "$(ASTERION_PRIME_P4_LIVE_ROOT)/pair.XXXXXX")"; private_root="$$pair_dir/store"; \
		commit_json="$$(ASTERION_PRIME_OPERATOR_ROOT="$(ASTERION_PRIME_OPERATOR_ROOT)" ASTERION_PRIME_P4_PRIVATE_ROOT="$$private_root" ASTERION_PRIME_P4_MODE=commit ASTERION_PRIME_NODE="$$(command -v node)" ASTERION_PRIME_PI_ENTRY="$(ASTERION_PRIME_LOCAL_PI_ENTRY)" $(UV_BIN) run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p4.live_entry)"; \
		recover_json="$$(ASTERION_PRIME_OPERATOR_ROOT="$(ASTERION_PRIME_OPERATOR_ROOT)" ASTERION_PRIME_P4_PRIVATE_ROOT="$$private_root" ASTERION_PRIME_P4_MODE=recover ASTERION_PRIME_NODE="$$(command -v node)" ASTERION_PRIME_PI_ENTRY="$(ASTERION_PRIME_LOCAL_PI_ENTRY)" $(UV_BIN) run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p4.live_entry)"; \
		{ echo "$$commit_json"; echo "$$recover_json"; } | jq -e -s '\''select(length == 2 and .[0].status == "committed" and .[1].status == "recovered" and .[0].model_call_count == 1 and .[1].model_call_count == 1 and .[0].input_tokens > 0 and .[1].input_tokens > 0 and .[1].prior_checkpoint_sha256 == .[0].checkpoint_sha256 and .[1].recovered_payload_sha256 != null and .[1].new_generation == (.[0].generation + 1) and .[1].result_sha256 != .[0].result_sha256 and .[1].continuation_id == .[0].continuation_id and .[1].worker_identity_sha256 != .[0].worker_identity_sha256)'\'''

# Diagnostic sibling runs the same bounded live P4 preset.
asterion-prime-p4-run-verbose:
	@$(MAKE) asterion-prime-p4-run

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
asterion-prime-p3-witness:
	@printf '[asterion-prime-p3-witness] native Asterion-prime P3 cross-runner continuity witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p3-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P3_PRIVATE_ROOT)"; \
		success_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P3_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P3_MODE=success; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p3.operator'\'' asterion-prime-p3-run-success "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P3_PRIVATE_ROOT)")"; \
		[ -n "$$success_json" ] || { echo "[asterion-prime-p3-witness] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$success_json" | jq -e ".status == \"completed\" and (.child_run_id | length > 0) and (.depth_reached == 2) and (.child_generation == (.root_generation + 1)) and (.child_result_sha256 != .root_result_sha256) and (.joined_result_sha256 | length == 64) and (.receipt_sha256 | length == 64) and (.refusal_reason == null)" >/dev/null || { echo "[asterion-prime-p3-witness] witness failed: $$success_json" >&2; exit 2; }; \
		echo "[asterion-prime-p3-witness] witness passed: depth 1 -> 2, child_generation = root_generation + 1, child_result_sha256 differs from root_result_sha256, refusal_reason is null" >&2'

# The application preset calls Pi twice on independent local sessions. Evidence
# is private under a fresh per-run directory; only the safe receipt is printed.
asterion-prime-p3-run:
	@printf '[asterion-prime-p3-run] bounded live P3 child/root verification\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p3-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		ASTERION_PRIME_OPERATOR_ROOT="$(ASTERION_PRIME_OPERATOR_ROOT)" ASTERION_PRIME_P3_PRIVATE_ROOT="$(ASTERION_PRIME_P3_LIVE_ROOT)" ASTERION_PRIME_NODE="$$(command -v node)" ASTERION_PRIME_PI_ENTRY="$(ASTERION_PRIME_LOCAL_PI_ENTRY)" \
			$(UV_BIN) run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p3.live_entry | \
			jq -e '\''select(.status == "completed" and .model_call_count == 2 and .input_tokens > 0 and .output_tokens > 0 and (.evidence_sha256 | length) == 64 and (.receipt_sha256 | length) == 64)'\'''

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

# Diagnostic sibling runs the live P3 preset and deterministic refusal checks.
asterion-prime-p3-run-verbose:
	@$(MAKE) asterion-prime-p3-run
	@$(MAKE) asterion-prime-p3-run-limits

# P5 bounded-autonomy success-path witness: re-invokes the operator with
# ``ASTERION_PRIME_P5_MODE=success``. The operator drives exactly one
# propose step, observes one verify failure, runs one repair step, and
# then verifies-pass on the second verify attempt, emitting one JSON
# line that seals the receipt. The host shell captures the stdout JSON
# and ``jq -e`` asserts the success invariants:
#
#   1. status == "completed", propose_step_count == 1
#   2. verify_step_count == 2, repair_step_count == 1
#   3. failed_verify_count == 1 (first verify rejected the proposal)
#   4. terminal_reason == "success"
#   5. joined_workspace_digest and receipt_sha256 each 64 chars
#
# Pass values either as `make asterion-prime-p5-run VAR=value` or via
# the shell environment; the ``?=`` defaults fall back to whichever was
# set. Like the other Prime presets, this is provider-backed and needs
# operator authorization. Operator root, PI entry, P5 private root, Orb
# VM, and node are operator-owned; the preset supplies no provider,
# model, cost, or deadline knob.
asterion-prime-p5-witness:
	@printf '[asterion-prime-p5-witness] native Asterion-prime P5 bounded-autonomy success-path witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p5-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P5_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P5_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P5_PRIVATE_ROOT)"; \
		success_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P5_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P5_MODE=success; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p5.operator'\'' asterion-prime-p5-run-success "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P5_PRIVATE_ROOT)")"; \
		[ -n "$$success_json" ] || { echo "[asterion-prime-p5-witness] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$success_json" | jq -e ".status == \"completed\" and (.propose_step_count == 1) and (.verify_step_count == 2) and (.repair_step_count == 1) and (.failed_verify_count == 1) and (.terminal_reason == \"success\") and (.joined_workspace_digest | length == 64) and (.receipt_sha256 | length == 64)" >/dev/null || { echo "[asterion-prime-p5-witness] witness failed: $$success_json" >&2; exit 2; }; \
		echo "[asterion-prime-p5-witness] witness passed: propose 1 + verify 2 + repair 1, terminal_reason=success" >&2'

# Real candidate proposal, local semantic verification, and bounded repair.
asterion-prime-p5-run:
	@printf '[asterion-prime-p5-run] bounded live P5 proposal/verification\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p5-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		ASTERION_PRIME_OPERATOR_ROOT="$(ASTERION_PRIME_OPERATOR_ROOT)" ASTERION_PRIME_P5_PRIVATE_ROOT="$(ASTERION_PRIME_P5_LIVE_ROOT)" ASTERION_PRIME_NODE="$$(command -v node)" ASTERION_PRIME_PI_ENTRY="$(ASTERION_PRIME_LOCAL_PI_ENTRY)" \
			$(UV_BIN) run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p5.live | \
			jq -e '\''select(.status == "completed" and .terminal_reason == "success" and .propose_step_count == 1 and .verify_step_count >= 1 and .repair_step_count == .failed_verify_count and .model_call_count >= 1 and .input_tokens > 0 and (.evidence_sha256 | length) == 64 and (.receipt_sha256 | length) == 64)'\'''

# P5 refusal-scenarios witness: re-invokes the operator with
# ``ASTERION_PRIME_P5_MODE=limits``. Per D-2026-09-19-01, cancellation
# folds into the closed enum rather than surfacing as a fourth
# scenario, so the operator emits exactly three JSON records
# (iteration-cap / duration-cap / no-progress), one per line, each
# carrying its ``scenario`` field, ``terminal_reason``, and a non-null
# ``receipt_sha256``. The host shell ``jq -e -s`` slurps all three into
# one array and asserts by index — fixed-position ``.[N]`` lookup dodges
# the make-recipe ``\$`` quoting trap that bit P4's earlier draft (Phase
# 6 commit ``9d1a2bb7``); see ``serene-mixing-cat.md`` §"Critical files".
#
# Pass values either as `make asterion-prime-p5-run-limits VAR=value` or
# via the shell environment; the ``?=`` defaults fall back to whichever
# was set. Like the other Prime presets, this is provider-backed and
# needs operator authorization.
asterion-prime-p5-run-limits:
	@printf '[asterion-prime-p5-run-limits] native Asterion-prime P5 three-refusal-scenarios witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p5-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P5_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P5_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P5_PRIVATE_ROOT)"; \
		limits_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P5_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P5_MODE=limits; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p5.operator'\'' asterion-prime-p5-run-limits "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P5_PRIVATE_ROOT)")"; \
		[ -n "$$limits_json" ] || { echo "[asterion-prime-p5-run-limits] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$limits_json" | jq -e -s "length == 3 and .[0].scenario == \"iteration-cap\" and .[0].terminal_reason == \"iteration-cap-exceeded\" and .[1].scenario == \"duration-cap\" and .[1].terminal_reason == \"duration-cap-exceeded\" and .[2].scenario == \"no-progress\" and .[2].terminal_reason == \"no-progress\" and (.[0].receipt_sha256 | length == 64) and (.[1].receipt_sha256 | length == 64) and (.[2].receipt_sha256 | length == 64)" >/dev/null || { echo "[asterion-prime-p5-run-limits] witness failed: $$limits_json" >&2; exit 2; }; \
		echo "[asterion-prime-p5-run-limits] witness passed: iteration-cap / duration-cap / no-progress refusals, each with terminal_reason and receipt_sha256" >&2'

# Diagnostic sibling of ``asterion-prime-p5-run`` + ``-limits``: re-invokes
# both witnesses with full output so Orb / python stderr surfaces to the
# host terminal for diagnosis only.
asterion-prime-p5-run-verbose:
	@$(MAKE) asterion-prime-p5-run ASTERION_PRIME_P5_PRIVATE_ROOT=$(ASTERION_PRIME_P5_PRIVATE_ROOT) || exit 1
	@$(MAKE) asterion-prime-p5-run-limits ASTERION_PRIME_P5_PRIVATE_ROOT=$(ASTERION_PRIME_P5_PRIVATE_ROOT) || exit 1
	@echo "[asterion-prime-p5-run-verbose] live run and limit witness passed"

# P6 continual-improvement preserved-path witness: re-invokes the operator with
# ``ASTERION_PRIME_P6_MODE=preserved``. The wrapper admits one candidate via
# ``HarnessCoordinator.apply(proposal)``, evaluates on the task B holdout, then
# applies the explicit promotion action and seals ``P6NativeReceipt`` with
# ``terminal_outcome="preserved"``, ``global_activation_approved=false``,
# ``rollback_invocation_count=0``. The host shell captures the stdout JSON line
# and ``jq -e`` asserts the success invariants:
#
#   1. status == "completed", terminal_outcome == "preserved"
#   2. global_activation_approved == false, rollback_invocation_count == 0
#   3. baseline_snapshot_digest, candidate_revision_digest,
#      task_b_result_digest, receipt_sha256 each 64 chars
#   4. task_b_result_digest and candidate_revision_digest both differ from
#      baseline_snapshot_digest (proves the candidate produced a different
#      snapshot and a different task B output)
#
# Pass values either as `make asterion-prime-p6-run VAR=value` or via the
# shell environment; the ``?=`` defaults fall back to whichever was set. Like
# the other Prime presets, this is provider-backed and needs operator
# authorization. Operator root, PI entry, P6 private root, Orb VM, and node
# are operator-owned; the preset supplies no provider, model, cost, or
# deadline knob. The single-record form (NOT ``jq -s slurp``) proves the
# preserved-path contract — see the spec section 7 / 8 ``Witness strategy``
# and ``Determinism``. Single-line jq is required (bash 3.2.57 macOS default
# rejects multi-line ``\`` continuation; Phase 8 Task 14 fix-on-verify lesson,
# commit ``5c07d9ff``).
asterion-prime-p6-witness:
	@printf '[asterion-prime-p6-witness] native Asterion-prime P6 continual-improvement preserved-path witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p6-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P6_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P6_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P6_PRIVATE_ROOT)"; \
		preserved_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P6_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P6_MODE=preserved; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p6.operator'\'' asterion-prime-p6-run-preserved "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P6_PRIVATE_ROOT)")"; \
		[ -n "$$preserved_json" ] || { echo "[asterion-prime-p6-witness] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$preserved_json" | jq -e ".status == \"completed\" and (.terminal_outcome == \"preserved\") and (.global_activation_approved == false) and (.rollback_invocation_count == 0) and (.baseline_snapshot_digest | length == 64) and (.candidate_revision_digest | length == 64) and (.task_b_result_digest | length == 64) and (.receipt_sha256 | length == 64) and (.candidate_revision_digest != .baseline_snapshot_digest) and (.task_b_result_digest != .baseline_snapshot_digest)" >/dev/null || { echo "[asterion-prime-p6-witness] witness failed: $$preserved_json" >&2; exit 2; }; \
		echo "[asterion-prime-p6-witness] witness passed: terminal_outcome=preserved, rollback_invocation_count=0, candidate_revision_digest and task_b_result_digest differ from baseline_snapshot_digest" >&2'

# One model-proposed candidate, actual train/holdout comparison, and explicit
# project-scope promotion through the composed candidate-store application.
asterion-prime-p6-run:
	@printf '[asterion-prime-p6-run] bounded live P6 candidate/holdout verification\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p6-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		ASTERION_PRIME_OPERATOR_ROOT="$(ASTERION_PRIME_OPERATOR_ROOT)" ASTERION_PRIME_P6_PRIVATE_ROOT="$(ASTERION_PRIME_P6_LIVE_ROOT)" ASTERION_PRIME_NODE="$$(command -v node)" ASTERION_PRIME_PI_ENTRY="$(ASTERION_PRIME_LOCAL_PI_ENTRY)" \
			$(UV_BIN) run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p6.live | \
			jq -e '\''select(.status == "completed" and .terminal_outcome == "preserved" and .global_activation_approved == false and .rollback_invocation_count == 0 and .model_call_count == 1 and .input_tokens > 0 and .output_tokens > 0 and (.candidate_revision_digest | length) == 64 and (.task_b_result_digest | length) == 64 and (.receipt_sha256 | length) == 64)'\'''

# P6 continual-improvement refusal-scenarios witness: re-invokes the operator
# with ``ASTERION_PRIME_P6_MODE=limits``. The operator emits exactly two JSON
# records (``rolled-back`` then ``global-rejected``), one per line, each
# carrying its ``scenario`` field, ``terminal_outcome``, and a non-null
# ``receipt_sha256``. The host shell ``jq -e -s`` slurps both into one array
# and asserts by index — fixed-position ``.[N]`` lookup dodges the make-
# recipe ``\$`` quoting trap that bit P4's earlier draft (Phase 6 commit
# ``9d1a2bb7``); see ``serene-mixing-cat.md`` §"Critical files".
#
# Pass values either as `make asterion-prime-p6-run-limits VAR=value` or via
# the shell environment; the ``?=`` defaults fall back to whichever was set.
# Like the other Prime presets, this is provider-backed and needs operator
# authorization. Single-line jq is required (bash 3.2.57 macOS default rejects
# multi-line ``\`` continuation; Phase 8 Task 14 fix-on-verify lesson, commit
# ``5c07d9ff``).
asterion-prime-p6-run-limits:
	@printf '[asterion-prime-p6-run-limits] native Asterion-prime P6 two-refusal-scenarios witness\n' >&2; \
	exec /bin/sh -ec 'build_dir="$$(mktemp -d "$(CURDIR)/.asterion-prime-p6-wheel.XXXXXX")"; trap '\''rm -rf "$$build_dir"'\'' EXIT HUP INT TERM; \
		$(UV_BIN) build --wheel --out-dir "$$build_dir" >/dev/null; \
		set -- "$$build_dir"/asterion-*.whl; [ "$$#" -eq 1 ] && [ -f "$$1" ]; \
		rm -rf "$(ASTERION_PRIME_P6_PRIVATE_ROOT)"; mkdir -p "$(ASTERION_PRIME_P6_PRIVATE_ROOT)"; chmod 700 "$(ASTERION_PRIME_P6_PRIVATE_ROOT)"; \
		limits_json="$$(orb -m "$(PRIME_ORB_MACHINE)" -u root -w /tmp /bin/sh -ec '\''unset PYTHONPATH; export ASTERION_PRIME_OPERATOR_ROOT="$$2"; export ASTERION_PRIME_PI_ENTRY="$$3"; export ASTERION_PRIME_P6_PRIVATE_ROOT="$$4"; export ASTERION_PRIME_P6_MODE=limits; export ASTERION_PRIME_NODE="$$(npm exec --offline --yes --package=node@22 -- node -p "process.execPath")"; exec /root/.local/bin/uv run --no-cache --isolated -q --with "$$1" --with "python-dotenv>=1.0.0" python -I -m asterion.applications.prime.p6.operator'\'' asterion-prime-p6-run-limits "$$1" "$(ASTERION_PRIME_OPERATOR_ROOT)" "$(ASTERION_PRIME_PI_ENTRY)" "$(ASTERION_PRIME_P6_PRIVATE_ROOT)")"; \
		[ -n "$$limits_json" ] || { echo "[asterion-prime-p6-run-limits] operator produced no JSON output" >&2; exit 2; }; \
		echo "$$limits_json" | jq -e -s "length == 2 and .[0].scenario == \"rolled-back\" and .[0].terminal_outcome == \"rolled-back\" and .[0].rollback_invocation_count == 1 and .[0].global_activation_approved == false and (.[0].candidate_revision_digest | length == 64) and .[1].scenario == \"global-rejected\" and .[1].terminal_outcome == \"rolled-back\" and .[1].rollback_invocation_count == 0 and .[1].global_activation_approved == false and .[1].candidate_revision_digest == .[1].baseline_snapshot_digest and (.[0].receipt_sha256 | length == 64) and (.[1].receipt_sha256 | length == 64)" >/dev/null || { echo "[asterion-prime-p6-run-limits] witness failed: $$limits_json" >&2; exit 2; }; \
		echo "[asterion-prime-p6-run-limits] witness passed: rolled-back (rollback_invocation_count=1) and global-rejected (boundary pre-orchestration), each with terminal_outcome=rolled-back and receipt_sha256" >&2'

# Diagnostic sibling of ``asterion-prime-p6-run`` + ``-limits``: re-invokes
# both witnesses with full output so Orb / python stderr surfaces to the
# host terminal for diagnosis only.
asterion-prime-p6-run-verbose:
	@$(MAKE) asterion-prime-p6-run ASTERION_PRIME_P6_PRIVATE_ROOT=$(ASTERION_PRIME_P6_PRIVATE_ROOT) || exit 1
	@$(MAKE) asterion-prime-p6-run-limits ASTERION_PRIME_P6_PRIVATE_ROOT=$(ASTERION_PRIME_P6_PRIVATE_ROOT) || exit 1
	@echo "[asterion-prime-p6-run-verbose] live run and limit witness passed"

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
