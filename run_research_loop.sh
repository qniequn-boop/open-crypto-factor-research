#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

max_cycles="${1:-3}"
python_bin="${PYTHON_BIN:-venv/bin/python}"
extra_args=()
if [ "${RUN_SEED_RESEARCH:-1}" = "0" ]; then
  extra_args+=("--skip-seed")
fi
if [ "${RUN_FACTOR_SEARCH:-0}" = "1" ]; then
  extra_args+=("--run-llm")
fi

exec "${python_bin}" -u research_loop.py --cycles "${max_cycles}" --python-bin "${python_bin}" "${extra_args[@]}"
