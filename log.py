# btclab/log.py
# 实验日志 —— 严格按照 PROJECT_DOC.md §4.6
# JSONL append-only + 摘要压缩

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import config

LOG_DIR = Path(config.LOG_DIR)
LOG_FILE = LOG_DIR / 'experiment_log.jsonl'
SUMMARY_FILE = LOG_DIR / 'summary.json'

# 因子家族分类关键字
FAMILY_KEYWORDS = {
    'momentum': ['returns', 'rsi', 'ts_rank', 'diff', 'roc'],
    'volatility': ['std', 'atr', 'bb_bw', 'squeeze', 'bb_pctb'],
    'reversal': ['zscore', 'quantile', '-1', '-'],
    'structure': ['ema', 'sma', 'ts_corr', 'ts_delay'],
    'liquidity': ['volume'],
}

def classify_family(dsl_expr: str) -> str:
    """根据DSL表达式中的关键字推断因子家族"""
    expr_lower = dsl_expr.lower()
    scores = {}
    for family, keywords in FAMILY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in expr_lower)
        if score > 0:
            scores[family] = score
    if scores:
        return max(scores, key=scores.get)
    return 'other'

def append_entry(entry: Dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(_sanitize(entry), ensure_ascii=False, default=str) + '\n')

def _sanitize(obj):
    import numpy as np
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj

def read_all_entries() -> List[Dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries

def _is_admitted(entry: Dict) -> bool:
    return bool(entry.get('admitted_to_pool', entry.get('promoted', False)))

def _is_promoted(entry: Dict) -> bool:
    return bool(entry.get('promoted')) and entry.get('status') != 'pooled_is_gate'

def create_entry(candidate_id: str, hypothesis: str, dsl_expr: str,
                 is_result: Dict, val_result: Dict, holdout_result: Dict = None,
                 overfit_result: Dict = None, promoted: bool = False,
                 family: str = None, existing_candidates: List[Dict] = None,
                 direction: str = 'neutral', admitted_to_pool: bool = False,
                 status: str = None) -> Dict:
    if family is None:
        family = classify_family(dsl_expr)

    # 与已晋升候选的最大相关性
    max_corr = 0.0
    if existing_candidates:
        promoted_entries = [e for e in existing_candidates if e.get('promoted')]
        if promoted_entries:
            max_corr = overfit_result.get('checks', {}).get('crowding', {}).get('max_correlation', 0) if overfit_result else 0

    entry = {
        'id': candidate_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'hypothesis': hypothesis,
        'dsl_expr': dsl_expr,
        'family': family,
        'direction': direction,
        'is_sharpe': is_result.get('sharpe') if is_result else None,
        'is_annual_return': is_result.get('annualized_return') if is_result else None,
        'is_max_dd': is_result.get('max_drawdown') if is_result else None,
        'is_win_rate': is_result.get('win_rate') if is_result else None,
        'is_dir_acc': is_result.get('dir_acc') if is_result else None,
        'is_ic_spearman': is_result.get('ic_spearman') if is_result else None,
        'val_sharpe': val_result.get('sharpe') if val_result else None,
        'val_annual_return': val_result.get('annualized_return') if val_result else None,
        'val_max_dd': val_result.get('max_drawdown') if val_result else None,
        'val_dir_acc': val_result.get('dir_acc') if val_result else None,
        'val_ic_spearman': val_result.get('ic_spearman') if val_result else None,
        'holdout_sharpe': holdout_result.get('sharpe') if holdout_result else None,
        'holdout_annual_return': holdout_result.get('annualized_return') if holdout_result else None,
        'holdout_dir_acc': holdout_result.get('dir_acc') if holdout_result else None,
        'admitted_to_pool': admitted_to_pool,
        'status': status or ('promoted' if promoted else ('pooled_is_gate' if admitted_to_pool else 'rejected')),
        'promoted': promoted,
        'reject_reason': overfit_result.get('reasons', '') if overfit_result and not promoted else '',
        'max_correlation_with_promoted': max_corr,
        'overfit_details': overfit_result.get('checks', {}) if overfit_result else {},
    }
    return entry

def summarize(n_recent_rounds: int = 3) -> str:
    """摘要压缩: 给LLM提供可操作的反馈, 不只是'你失败了'。

    核心改进: 把regime分段结果和'接近通过'的候选信息喂回,
    让LLM知道哪个方向有效、差在哪、该怎么改。
    """
    entries = read_all_entries()
    if not entries:
        return '暂无实验记录。这是第一轮。'

    entries_sorted = sorted(entries, key=lambda x: x.get('timestamp', ''), reverse=True)
    recent = entries_sorted[:n_recent_rounds * config.CANDIDATES_PER_ROUND]

    # 1. 基本统计
    total = len(entries)
    admitted = [e for e in entries if _is_admitted(e)]
    promoted = [e for e in entries if _is_promoted(e)]
    rejected = [e for e in recent if not _is_admitted(e)]
    val_passed = [
        e for e in entries
        if e.get('single_factor_status') in ('single_factor_val_pass', 'single_factor_val_sharpe_pass')
    ]

    summary = f"=== 实验摘要 (总记录: {total}, 已入池: {len(admitted)}, 已晋升: {len(promoted)}) ===\n\n"
    summary += f"单因子Val通过: {len(val_passed)} (入池不等于高质量; Val通过才是更强证据)\n\n"

    # 2. 家族统计
    family_stats = {}
    for e in recent:
        fam = e.get('family') or 'other'
        if fam not in family_stats:
            family_stats[fam] = {'total': 0, 'best_is': -999}
        family_stats[fam]['total'] += 1
        is_sr = e.get('is_sharpe', 0) or 0
        if is_sr > family_stats[fam]['best_is']:
            family_stats[fam]['best_is'] = is_sr

    summary += "家族表现 (最近):\n"
    for fam, stats in sorted(family_stats.items(), key=lambda x: -x[1]['best_is']):
        summary += f"  {fam}: {stats['total']}个, 最佳IS夏普={stats['best_is']:.2f}\n"

    # 3. Regime分析: 找出在某个regime下IS+Val都为正的候选
    close_calls = []
    for e in recent:
        od = e.get('overfit_details', {})
        for regime_name in ['trending', 'ranging']:
            r = od.get(regime_name, {})
            is_sr = r.get('is_sharpe', -999)
            val_sr = r.get('val_sharpe', -999)
            if is_sr > 0 and val_sr > 0:
                close_calls.append({
                    'id': e['id'],
                    'regime': regime_name,
                    'is_sr': is_sr,
                    'val_sr': val_sr,
                    'expr': e['dsl_expr'][:60],
                    'reason': r.get('reason', ''),
                    'family': e.get('family', '?'),
                })

    if close_calls:
        summary += f"\n=== 接近通过的候选 (IS+Val在某个regime都为正): {len(close_calls)}个 ===\n"
        # Sort by best val_sharpe
        close_calls.sort(key=lambda x: -x['val_sr'])
        for cc in close_calls[:5]:
            summary += f"  {cc['id']} [{cc['regime']}] IS={cc['is_sr']:.2f} Val={cc['val_sr']:.2f}\n"
            summary += f"    表达式: {cc['expr']}\n"
            summary += f"    未通过原因: {cc['reason'][:100]}\n"
            # Add actionable hint
            if 'MaxDD' in cc['reason']:
                summary += "    建议: 乘一个波动率调节项(如div(1, std(returns(close,20),20)))降低回撤\n"
            elif 'decay' in cc['reason']:
                summary += "    建议: 尝试更短的窗口或加趋势确认过滤\n"
            elif 'DSR' in cc['reason']:
                summary += "    建议: 这个方向可能已饱和, 换一个不同的机制\n"
    else:
        # Find near-misses: IS positive in a regime
        near_miss = []
        for e in recent:
            od = e.get('overfit_details', {})
            for regime_name in ['trending', 'ranging']:
                r = od.get(regime_name, {})
                is_sr = r.get('is_sharpe', -999)
                val_sr = r.get('val_sharpe', -999)
                if is_sr > 0 and val_sr > -1:
                    near_miss.append((e['id'], regime_name, is_sr, val_sr, e['dsl_expr'][:50]))
        if near_miss:
            summary += f"\n=== 有潜力的候选 (IS为正, Val接近0): {len(near_miss)}个 ===\n"
            near_miss.sort(key=lambda x: -(x[2] + x[3]))
            for cid, rn, is_sr, val_sr, expr in near_miss[:3]:
                summary += f"  {cid} [{rn}] IS={is_sr:.2f} Val={val_sr:.2f} | {expr}\n"

    # 4. 方向性建议: 基于数据分析
    summary += "\n=== 方向建议 ===\n"

    # Which regime had more positive hits?
    trend_pos = sum(1 for cc in close_calls if cc['regime'] == 'trending')
    range_pos = sum(1 for cc in close_calls if cc['regime'] == 'ranging')
    if trend_pos > range_pos:
        summary += "趋势期因子更有效。继续探索趋势期因子, 但需要降低回撤(加波动率调节/仓位衰减)。\n"
    elif range_pos > trend_pos:
        summary += "震荡期因子更有效。继续探索均值回归和区间交易因子。\n"
    else:
        summary += "趋势和震荡期均有潜力。尝试regime-conditional因子(用squeeze检测状态切换)。\n"

    # What expressions keep failing?
    all_rejected_reasons = [e.get('reject_reason', '') for e in rejected if e.get('reject_reason')]
    maxdd_count = sum(1 for r in all_rejected_reasons if 'MaxDD' in r)
    if maxdd_count > len(all_rejected_reasons) * 0.3:
        summary += f"很多候选因回撤过大被拒({maxdd_count}个)。考虑在因子里加波动率分位调节或ATR归一化。\n"

    # 5. 因子池互补性分析
    promoted_entries = [e for e in entries if _is_admitted(e)]
    if len(promoted_entries) >= 2:
        from collections import Counter
        expr_patterns = []
        for e in promoted_entries:
            expr = e.get('dsl_expr', '')
            if 'ts_corr' in expr:
                expr_patterns.append('相关性类')
            elif 'ema(close' in expr and 'sub' in expr:
                expr_patterns.append('EMA差类')
            elif 'rsi' in expr:
                expr_patterns.append('RSI类')
            elif 'bb_' in expr:
                expr_patterns.append('布林类')
            elif 'volume' in expr:
                expr_patterns.append('成交量类')
            elif 'squeeze' in expr:
                expr_patterns.append('挤压类')
            elif 'sma(diff' in expr:
                expr_patterns.append('斜率类')
            else:
                expr_patterns.append('其他')

        pattern_counts = Counter(expr_patterns)
        dominant = pattern_counts.most_common(1)[0]
        if dominant[1] >= 2:
            summary += f"\n=== 因子池互补性 ===\n"
            summary += f"已晋升{len(promoted_entries)}个因子, 其中{dominant[0]}占{dominant[1]}个。\n"
            summary += f"因子池同质化! 需要探索完全不同的机制。\n"
            summary += f"论文依据: Alpha101平均两两相关性仅15.9%; Hubble top-k分布在3个不同家族。\n"
            summary += f"已有模式: {dict(pattern_counts)}\n"
            summary += f"需要的新方向(选一个跟已有完全不同的):\n"
            summary += f"  - 成交量异动: volume偏离常态 + 价格方向\n"
            summary += f"  - 波动率状态切换: squeeze释放 + bb_bw突变\n"
            summary += f"  - 价格形态: 日内振幅(high-low)/close + 趋势方向\n"
            summary += f"  - 多周期结构: 短期vs长期相关性变化\n"
            summary += f"  目标: 生成与已有因子相关性<0.3的新因子\n"

    # 6. 未探索的家族
    all_families = ['momentum', 'volatility', 'reversal', 'structure', 'liquidity']
    explored = set(e.get('family', 'other') for e in entries)
    unexplored = [f for f in all_families if f not in explored]
    if unexplored:
        summary += f"\n未充分探索: {', '.join(unexplored)}\n"

    return summary

def get_families_covered() -> List[str]:
    entries = read_all_entries()
    admitted = [e for e in entries if _is_admitted(e)]
    return list(set(e.get('family', 'other') for e in admitted))

def count_entries() -> int:
    return len(read_all_entries())
