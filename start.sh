#!/bin/bash
cd ~/btclab
source venv/bin/activate
rm -f logs/experiment_log.jsonl
python main.py 2>&1 | tee logs/run_$(date +%Y%m%d_%H%M%S).log
