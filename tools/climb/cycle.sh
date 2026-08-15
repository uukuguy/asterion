#!/bin/sh
set -eu

case "${1-}" in
  H-001)
    uv run python -m unittest -v tests.test_prime_rlm_messaging_parity
    python3 tools/climb/regen-tree.py H-001 passed H-002 test.prime-rlm.provider-free
    ;;
  H-002)
    uv run python -m unittest -v tests.test_prime_rlm_messaging_parity.TestPrimeRlmMessagingParity.test_real_daemon_exposes_asterion_rlm_spawn_admission
    python3 tools/climb/regen-tree.py H-002 passed H-003 test.prime-rlm.recovery-read-only
    ;;
  *) exit 2 ;;
esac
