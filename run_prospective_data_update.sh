#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p logs

exec flock -n logs/prospective_data_update.lock \
  venv/bin/python -u prospective_data_update.py "$@"
