#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

substrate_manifest="$(venv/bin/python panel_factory_runtime.py --print-substrate)"

exec venv/bin/python -u panel_factory_unattended_drill.py \
  --substrate-manifest "$substrate_manifest"
