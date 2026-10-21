#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec uv run --with "python-dotenv>=1.0.0" python examples/applications/native_dci.py --live
