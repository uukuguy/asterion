#!/usr/bin/env bash
set -euo pipefail

case "${1:?hypothesis id required}" in
  H-001) test_module=tests.test_dci_capability_payload ;;
  H-002) test_module=tests.test_dci_benchmark_bindings ;;
  H-003) test_module=tests.test_dci_package_ownership ;;
  H-004) test_module=tests.test_dci_application_adapter ;;
  H-005) test_module=tests.test_project_boundaries ;;
  H-006) test_module=tests.test_dci_external_distribution ;;
  H-007) test_module=tests.test_dci_source_form_equivalence ;;
  H-008) test_module=tests.test_project_boundaries ;;
  *) echo "unknown hypothesis" >&2; exit 2 ;;
esac

if uv run python -m unittest -v "$test_module"; then
  printf '{"total": 1, "test_module": "%s"}\n' "$test_module"
else
  printf '{"total": 0, "test_module": "%s"}\n' "$test_module"
  exit 1
fi
