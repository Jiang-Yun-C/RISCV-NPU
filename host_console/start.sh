#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if command -v npu-python >/dev/null 2>&1; then
  exec npu-python server.py --open "$@"
else
  exec python3 server.py --open "$@"
fi
