#!/bin/sh
set -eu

if [ "${1-}" != "H-001" ]; then
  exit 2
fi

uv run python -m unittest -v tests.test_prime_rlm_messaging_parity
python3 tools/climb/regen-tree.py H-001 passed H-002 test.prime-rlm.provider-free
