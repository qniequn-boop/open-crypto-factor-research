#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p logs prospective_snapshots

exec flock -n logs/prospective_snapshot.lock \
  bash -c '
    set -euo pipefail
    venv/bin/python -u prospective_universe_snapshot.py "$@"
    venv/bin/python -u prospective_factor_snapshot.py "$@"
    venv/bin/python -u prospective_evidence_readiness.py
  ' bash "$@"
