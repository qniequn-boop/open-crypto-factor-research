#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
log="logs/strategy_pipeline_${ts}.log"
mkdir -p logs

{
  echo "START strategy pipeline ${ts}"
  venv/bin/python -u strategy_combo_research.py
  venv/bin/python -u strategy_audit.py
  venv/bin/python -u strategy_blend_research.py
  venv/bin/python -u strategy_export.py
  venv/bin/python -u strategy_skeptic_audit.py
  echo "DONE strategy pipeline $(date -u +%Y%m%dT%H%M%SZ)"
} > "${log}" 2>&1

echo "${log}"
