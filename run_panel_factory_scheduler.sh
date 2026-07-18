#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ -z "${PANEL_FACTORY_SUBSTRATE_MANIFEST:-}" ]]; then
  PANEL_FACTORY_SUBSTRATE_MANIFEST="$(venv/bin/python panel_factory_runtime.py --print-substrate)"
fi

exec venv/bin/python -u panel_factory_scheduler.py \
  --substrate-manifest "$PANEL_FACTORY_SUBSTRATE_MANIFEST"
