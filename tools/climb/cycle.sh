#!/bin/sh
set -eu

require_clean_tree() {
  if [ -n "$(git status --porcelain)" ]; then
    exit 2
  fi
}

require_node22() {
  version="$(node -v 2>/dev/null || true)"
  case "$version" in
    v22.*) ;;
    *) exit 2 ;;
  esac
  IFS=.
  set -- ${version#v}
  IFS=' '
  if [ "$1" -ne 22 ] || [ "$2" -lt 8 ]; then
    exit 2
  fi
}

require_h037_tree() {
  status="$(git status --porcelain)"
  allowed_temp='?? "$(getconf DARWIN_USER_TEMP_DIR)/"'
  allowed_promotion='?? .task13-promotion-bin/'
  case "$status" in
    ""|"$allowed_temp"|"$allowed_promotion"|"$allowed_temp
$allowed_promotion"|"$allowed_promotion
$allowed_temp") ;;
    *) exit 2 ;;
  esac
}

case "${1-}" in
  H-001)
    uv run python -m unittest -v tests.test_prime_rlm_messaging_parity
    python3 tools/climb/regen-tree.py H-001 passed H-002 test.prime-rlm.provider-free
    ;;
  H-002)
    uv run python -m unittest -v tests.test_prime_rlm_messaging_parity.TestPrimeRlmMessagingParity.test_real_daemon_exposes_asterion_rlm_spawn_admission
    python3 tools/climb/regen-tree.py H-002 passed H-003 test.prime-rlm.recovery-read-only
    ;;
  H-005)
    make ASTERION_PRIME_SOURCE_ROOT=3th-party/prime-agent prime-verify-native-rlm-bounded
    python3 tools/climb/regen-tree.py H-005 passed H-006 make.prime-native-rlm-bounded
    ;;
  H-006)
    make test.prime-session-context-parity.bounded
    python3 tools/climb/regen-tree.py H-006 passed H-007 test.prime-session-context-parity.bounded
    ;;
  H-007)
    make check
    make promotion-check
    git diff --check
    python3 tools/climb/regen-tree.py H-007 passed H-008 check.phase2-session-context-closure
    ;;
  H-008)
    make test.prime-rlm-spawn-admission.provider-free
    python3 tools/climb/regen-tree.py H-008 passed H-009 test.prime-rlm-spawn-admission.provider-free
    ;;
  H-009)
    uv run python -m unittest -v tests.test_prime_rlm_experiment.TestNativeRlmExperiment.test_phase1_receipt_does_not_claim_model_program_or_depth_evidence
    python3 tools/climb/regen-tree.py H-009 falsified H-010 audit.prime-native-rlm-bounded-receipt
    ;;
  H-010)
    make ASTERION_PRIME_SOURCE_ROOT=3th-party/prime-agent prime-verify-native-rlm-bounded
    make test.prime-rlm-spawn-admission.provider-free
    uv run python tools/check_prime_parity.py --domain rlm.programmatic --provider asterion.prime-gateway
    python3 tools/climb/regen-tree.py H-010 passed H-011 check.rlm-programmatic-closure
    ;;
  H-011)
    make docs-check
    uv run python -m unittest -v tests.test_prime_parity_ledger
    python3 tools/climb/regen-tree.py H-011 passed H-012 check.operation-long-running-inventory
    ;;
  H-012)
    uv run python -m unittest -v tests.test_prime_long_running_parity tests.test_prime_parity_conformance tests.test_prime_parity_ledger
    python3 tools/climb/regen-tree.py H-012 passed H-013 test.prime-long-running-matrix.provider-free
    ;;
  H-013)
    uv run python -m unittest -v tests.test_control_long_running tests.test_control_journal
    python3 tools/climb/regen-tree.py H-013 passed H-014 test.control-long-running.provider-free
    ;;
  H-014)
    npm --prefix packages/typescript/prime-gateway test -- test/daemon-wire.test.mjs
    npm --prefix packages/typescript/prime-gateway run build
    python3 tools/climb/regen-tree.py H-014 passed H-015 test.prime-heartbeat-wire.provider-free
    ;;
  H-015)
    npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs
    npm --prefix packages/typescript/prime-gateway run build
    python3 tools/climb/regen-tree.py H-015 passed H-016 test.prime-heartbeat-fencing.provider-free
    ;;
  H-016)
    npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs
    npm --prefix packages/typescript/prime-gateway run build
    python3 tools/climb/regen-tree.py H-016 passed H-017 test.prime-heartbeat-ipc.provider-free
    ;;
  H-017)
    uv run python -m unittest -v tests.test_control_long_running tests.test_prime_long_running_parity
    npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs
    python3 tools/climb/regen-tree.py H-017 passed H-018 test.prime-long-running-binding.provider-free
    ;;
  H-018)
    uv run python -m unittest -v tests.test_control_long_running tests.test_control_journal tests.test_prime_long_running_parity
    npm --prefix packages/typescript/prime-gateway test -- test/long-running.test.mjs
    python3 tools/climb/regen-tree.py H-018 passed H-019 test.prime-residency-recovery.provider-free
    ;;
  H-019)
    uv run python -m unittest -v tests.test_prime_long_running_parity
    python3 tools/climb/regen-tree.py H-019 passed H-020 test.prime-long-running-authority.provider-free
    ;;
  H-020)
    receipt="${ASTERION_PRIME_LONG_RUNNING_RECEIPT-.asterion-private/prime-long-running/prime-long-running-bounded-receipt.json}"
    uv run python -c 'import json,sys; from pathlib import Path; from asterion.control.providers.prime.parity_testing import build_prime_long_running_bounded_observation; value=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); observation=build_prime_long_running_bounded_observation(value); assert observation.provider_operations == 1' "$receipt"
    python3 tools/climb/regen-tree.py H-020 passed H-021 test.prime-long-running.bounded
    ;;
  H-021)
    make test.prime-long-running.provider-free
    uv run python -m unittest -v tests.test_prime_parity_ledger tests.test_prime_long_running_parity
    python3 tools/climb/regen-tree.py H-021 passed H-022 test.prime-long-running.provider-free
    ;;
  H-022)
    uv run python tools/check_prime_parity.py --domain operation.long-running --provider asterion.prime-gateway
    make check
    make promotion-check
    git diff --check
    python3 tools/climb/regen-tree.py H-022 passed H-023 check.operation-long-running-closure
    ;;
  H-023)
    uv run python tools/check_prime_parity.py --domain harness.continual --provider asterion.prime-gateway
    make check
    make promotion-check
    git diff --check
    python3 tools/climb/regen-tree.py H-023 passed H-024 check.harness-continual-closure
    ;;
  H-024)
    uv run python -m unittest -v tests.test_prime_parity_ledger tests.test_check_prime_parity
    python3 tools/climb/regen-tree.py H-024 passed H-025 check.ecosystem-capabilities-inventory
    ;;
  H-025)
    uv run python -m unittest -v tests.test_control_ecosystem
    python3 tools/climb/regen-tree.py H-025 passed H-026 test.control-ecosystem.provider-free
    ;;
  H-026)
    uv run python -m unittest -v tests.test_control_ecosystem_materialization
    python3 tools/climb/regen-tree.py H-026 passed H-027 test.ecosystem-materialization.provider-free
    ;;
  H-027)
    uv run python -m unittest -v \
      tests.test_prime_ecosystem_adapter.TestPrimeEcosystemClient.test_selected_client_adds_only_private_ecosystem_activate_request \
      tests.test_prime_ecosystem_adapter.TestPrimeEcosystemClient.test_transport_failure_quiesces_consumer_before_projection_cleanup
    python3 tools/climb/regen-tree.py H-027 passed H-028 test.prime-ecosystem-adapter.provider-free
    ;;
  H-028)
    npm --prefix packages/typescript/prime-gateway test -- test/ecosystem.test.mjs test/main.test.mjs
    python3 tools/climb/regen-tree.py H-028 passed H-029 test.prime-ecosystem-gateway.provider-free
    ;;
  H-029)
    uv run python -m unittest -v tests.test_prime_ecosystem_real_process tests.test_setup_prime_agent
    python3 tools/climb/regen-tree.py H-029 passed H-030 test.prime-ecosystem-module.provider-free
    ;;
  H-030)
    make test.prime-ecosystem-resources.provider-free
    python3 tools/climb/regen-tree.py H-030 passed H-031 test.prime-ecosystem-resources.provider-free
    ;;
  H-031)
    make test.prime-ecosystem-extensions.provider-free
    python3 tools/climb/regen-tree.py H-031 passed H-032 test.prime-ecosystem-extensions.provider-free
    ;;
  H-032)
    make test.prime-ecosystem-packages.provider-free
    python3 tools/climb/regen-tree.py H-032 passed H-033 test.prime-ecosystem-packages.provider-free
    ;;
  H-033)
    make test.prime-ecosystem-mcp.provider-free
    python3 tools/climb/regen-tree.py H-033 passed H-034 test.prime-ecosystem-mcp.provider-free
    ;;
  H-034)
    make test.prime-ecosystem-resources.provider-free
    make test.prime-ecosystem-extensions.provider-free
    make test.prime-ecosystem-packages.provider-free
    make test.prime-ecosystem-mcp.provider-free
    uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway
    make check
    make promotion-check
    git diff --check
    python3 tools/climb/regen-tree.py H-034 passed H-035 check.ecosystem-capabilities-closure
    ;;
  H-035)
    make test.prime-client-core.provider-free
    make test.prime-client-protocols.provider-free
    make test.prime-client-interactive.provider-free
    make test.prime-client-export-share.provider-free
    uv run python tools/check_prime_parity.py --features interface.sdk,interface.cli-interactive,interface.rpc,interface.acp,interface.json-stream,interface.headless-print,interface.tui-commands,interface.tui-extension-ui,interface.export-share --provider asterion.prime-gateway
    make check
    make promotion-check
    git diff --check
    python3 tools/climb/regen-tree.py H-035 passed H-036 check.client-interfaces-closure
    ;;
  H-036)
    require_clean_tree
    require_node22
    make test.prime-operational-auth.provider-free
    make test.prime-operational-model-selection.provider-free
    make test.prime-operational-settings-keybindings.provider-free
    make test.prime-operational-telemetry-usage.provider-free
    make test.prime-operational-doctor.provider-free
    make test.prime-operational-controlled-update-restart.provider-free
    uv run python tools/check_prime_parity.py --features operation.auth,operation.model-selection,operation.settings-keybindings,operation.telemetry-usage,operation.doctor,operation.controlled-update-restart --provider asterion.prime-gateway
    make check
    make promotion-check
    git diff --check
    python3 tools/climb/regen-tree.py H-036 passed future-work-queue check.operational-parity-closure
    ;;
  H-037)
    require_h037_tree
    require_node22
    npm --prefix packages/typescript/prime-gateway run build
    uv run python -m unittest -v tests.test_prime_operation_real_process
    uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.prime-gateway
    make check
    make promotion-check
    git diff --check
    require_h037_tree
    python3 tools/climb/regen-tree.py H-037 passed phase-3-native-kernel-design prime-system-parity-operation-host-callback
    ;;
  *) exit 2 ;;
esac
