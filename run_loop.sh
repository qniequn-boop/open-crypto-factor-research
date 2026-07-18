#!/bin/bash
# btclab ?????: ???10?x10?=100?, ??????
# ????????????, ???????
cd ~/btclab
source venv/bin/activate

TOTAL_BATCHES=10
BATCH_SIZE=10  # ??10? (config.MAX_ROUNDS)

# ???MAX_ROUNDS???????
sed -i "s/MAX_ROUNDS = .*/MAX_ROUNDS = $BATCH_SIZE/" config.py

for batch in $(seq 1 $TOTAL_BATCHES); do
    echo "============================================"
    echo "BATCH $batch/$TOTAL_BATCHES starting at $(date)"
    echo "============================================"
    
    # ??experiment_log.jsonl (????), ???latest.log
    python -u main.py 2>&1 | tee logs/batch_${batch}.log
    
    echo "BATCH $batch done at $(date)"
    echo "Total entries so far: $(wc -l < logs/experiment_log.jsonl 2>/dev/null || echo 0)"
    echo ""
    
    # ????30? (API rate limit??)
    if [ $batch -lt $TOTAL_BATCHES ]; then
        echo "Sleeping 30s before next batch..."
        sleep 30
    fi
done

echo "============================================"
echo "ALL BATCHES DONE at $(date)"
echo "Total entries: $(wc -l < logs/experiment_log.jsonl 2>/dev/null || echo 0)"
echo "Promoted: $(python3 -c "
import json
entries = [json.loads(l) for l in open('logs/experiment_log.jsonl')]
promoted = [e for e in entries if e.get('promoted')]
print(len(promoted))
")"
echo "============================================"
