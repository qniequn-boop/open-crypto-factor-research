# btclab/generator.py
# 假设生成器 —— 严格按照 PROJECT_DOC.md §4.3 + §10.6
# prompt构建 + 正负RAG + 候选解析

import ast
from typing import List, Dict
from llm_client import get_client, Candidate
from dsl import parse_and_validate, ast_to_string
from operators import FIELD_NAMES
import config

# ============================================================
# 负 RAG: 拥挤模板黑名单 (§10.6)
# ============================================================

BLACKLIST_TEMPLATES = [
    {
        'name': '纯RSI均值回归',
        'expr': 'if(gt(rsi(close, 14), 70), -1, if(lt(rsi(close, 14), 30), 1, 0))',
        'description': 'RSI超买超卖均值回归, 最拥挤的策略之一',
    },
    {
        'name': '双均线交叉',
        'expr': 'if(gt(ema(close, 9), ema(close, 21)), 1, -1)',
        'description': '短均线上穿长均线做多, 反之做空',
    },
    {
        'name': '纯布林突破',
        'expr': 'if(gt(bb_pctb(close, 20, 2), 1), 1, if(lt(bb_pctb(close, 20, 2), 0), -1, 0))',
        'description': '价格突破布林带上轨做多, 跌破下轨做空',
    },
    {
        'name': '纯动量(ROC)',
        'expr': 'if(gt(returns(close, 20), 0), 1, -1)',
        'description': '纯收益率方向, 无任何过滤',
    },
    {
        'name': '纯波动率(无方向)',
        'expr': 'std(returns(close, 20), 20)',
        'description': '仅波动率, 无方向信号',
    },
]

# 解析黑名单模板的AST用于距离比较
BLACKLIST_ASTS = {}
for t in BLACKLIST_TEMPLATES:
    try:
        tree = parse_and_validate(t['expr'])
        BLACKLIST_ASTS[t['name']] = tree
    except Exception:
        pass


# ============================================================
# 因子家族 (D8)
# ============================================================

FACTOR_FAMILIES = {
    'momentum': '动量类: returns, rsi, ts_rank, diff — 追涨杀跌',
    'volatility': '波动类: std, atr, bb_bw, squeeze — 利用波动率变化',
    'reversal': '反转类: ts_rank取反, zscore极端值反转, quantile低买高卖',
    'structure': '结构类: 均线距离, 通道关系, 多周期对比 — 市场结构变化',
    'liquidity': '流动性类: volume变化, 成交量异动, 换手率异常',
}

# ============================================================
# AST相似度计算 (§10.6)
# ============================================================

def _ast_edit_distance(tree1: ast.AST, tree2: ast.AST) -> float:
    """简化编辑距离: 比较AST字符串的差异"""
    s1 = ast_to_string(tree1.body)
    s2 = ast_to_string(tree2.body)

    # Levenshtein
    m, n = len(s1), len(s2)
    if m == 0:
        return float(n)
    if n == 0:
        return float(m)

    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)

    return float(dp[m][n])

def ast_similarity(tree1: ast.AST, tree2: ast.AST) -> float:
    """AST距离 = 编辑距离 / max(节点数)"""
    dist = _ast_edit_distance(tree1, tree2)
    n1 = len(ast_to_string(tree1.body))
    n2 = len(ast_to_string(tree2.body))
    max_n = max(n1, n2, 1)
    return 1.0 - (dist / max_n)


# ============================================================
# Prompt 构建
# ============================================================

SYSTEM_PROMPT = """你是量化研究策略师。你正在为 BTC-USDT 永续合约寻找预测因子。

约束:
1. 每个因子必须有"可证伪假设": "我预期X能预测Y, 因为Z"
2. 因子用DSL表达式表示, 输出连续值(不要用if包成二值), 仓位会根据信号强度连续变化
3. 可用字段: close, open, high, low, volume
4. 算子签名(严格按此调用, 参数数量不对会被拒绝):
   returns(series, n)          例: returns(close, 20)
   log_returns(series, n)
   diff(series, n)
   ema(series, n)               例: ema(close, 50)
   sma(series, n)
   ts_mean(series, n)          等价于sma(series, n)
   atr(high, low, close, n)     注意: 4个参数!  例: atr(high, low, close, 14)
   std(series, n)               例: std(returns(close, 20), 20)
   rsi(close, n)                例: rsi(close, 14)
   ts_rank(series, n)           输出0~1
   quantile(series, n, q)       3个参数! 例: quantile(close, 60, 0.2)
   zscore(series, n)
   bb_bw(close, n, k)           3个参数! 例: bb_bw(close, 20, 2)
   bb_pctb(close, n, k)
   squeeze(high, low, close, bb_n, bb_k, kc_n, kc_k)  7个参数!
   ts_max(series, n)
   ts_min(series, n)
   ts_corr(s1, s2, n)           例: ts_corr(close, volume, 20)
   ts_delay(series, n)
   add(s1, s2), sub(s1, s2), mul(s1, s2), div(s1, s2)
   max(s1, s2), min(s1, s2), abs(series), neg(series)
   if(cond, s1, s2)             cond>0时取s1, 否则s2
   gt(s1, s2), lt(s1, s2)       输出1或0
5. 所有窗口参数 n >= 1
6. 输出方向: long(正向预测), short(反向预测), neutral(无方向)
7. direction 会在回测前真实作用到信号: short 会把 dsl_expr 输出乘以 -1。
   不要把所有候选都标 long。只有当表达式越大越看涨时用 long;
   当表达式越大越看跌时用 short; 不确定才用 neutral。

禁止: 变量赋值、循环、自定义函数、import、截面算子、用if把信号包成二值
必须: 每个因子覆盖不同逻辑,不是同一家族的变体
重点避免: 反复提交 EMA 差值、布林带宽度变化、波动率乘动量这类上一轮在 Val/Holdout 系统性失败的模板。
优先探索: 成交量加权价格偏离、慢趋势斜率、结构性价量关系、低相关的流动性/结构因子。

好的表达式示例(连续信号, 非二值):
  mul(sub(ts_rank(returns(close, 20), 60), 0.5), zscore(std(returns(close, 10), 40), 100))
  div(sub(close, ema(close, 50)), atr(high, low, close, 14))
  mul(ts_corr(returns(close, 5), returns(volume, 5), 20), sub(ts_rank(close, 100), 0.5))

坏的表达式示例(二值, 信息丢失, 不要这样):
  if(gt(returns(close, 20), 0), 1, -1)
  if(gt(rsi(close, 14), 70), -1, 1)"""

def build_user_prompt(round_num: int, total_candidates_so_far: int,
                      log_summary: str, families_covered: List[str]) -> str:
    """构建用户prompt (§4.3)"""

    # 负RAG: 黑名单
    neg_rag = "\n".join([
        f"- {t['name']}: {t['description']} (表达式: {t['expr']})"
        for t in BLACKLIST_TEMPLATES
    ])

    # 正RAG: 未覆盖的家族
    uncovered = [f for f in FACTOR_FAMILIES if f not in families_covered]
    pos_rag = ""
    if uncovered:
        pos_rag = "当前未覆盖的因子家族:\n" + "\n".join([
            f"- {f}: {FACTOR_FAMILIES[f]}" for f in uncovered
        ]) + "\n\n优先探索这些家族。"

    # 多样性要求
    diversity_req = f"本轮必须覆盖至少 {config.MIN_FAMILIES_PER_ROUND} 个不同因子家族。"
    diversity_req += "\n至少一半候选必须是非momentum家族。必须覆盖 structure / liquidity / reversal 中至少两个方向。"
    diversity_req += "\n不要把慢趋势EMA斜率、EMA差值、波动率乘动量换参数后重复提交。"

    prompt = f"""=== 搜索轮次: {round_num + 1} ===
已生成候选总数: {total_candidates_so_far}

=== 负RAG: 以下策略模板已被大量使用, 必须避开 ===
{neg_rag}

=== 正RAG: 鼓励探索的方向 ===
{pos_rag}

=== 多样性要求 ===
{diversity_req}
所有因子家族: {', '.join(FACTOR_FAMILIES.keys())}

=== 上轮实验反馈 ===
{log_summary if log_summary else '这是第一轮, 无历史反馈。'}

=== 任务 ===
生成 {config.CANDIDATES_PER_ROUND} 个候选假设, 每个包含:
- hypothesis: 可证伪假设文本
- dsl_expr: DSL因子表达式
- direction: long / short / neutral

要求: 表达式语法正确, 无未来函数, 避开花名单模板。
"""

    return prompt


# ============================================================
# 生成器主函数
# ============================================================

def is_crowding(expr: str) -> bool:
    """检查是否与黑名单模板过于相似 (§10.6: AST距离 < 0.15)"""
    try:
        tree = parse_and_validate(expr)
        for name, bt in BLACKLIST_ASTS.items():
            sim = ast_similarity(tree, bt)
            if sim > config.AST_SIMILARITY_THRESHOLD:
                return True
        return False
    except Exception:
        return True

def generate_candidates(round_num: int, total_so_far: int,
                        log_summary: str = "",
                        families_covered: List[str] = None) -> List[Candidate]:
    client = get_client()
    user_prompt = build_user_prompt(round_num, total_so_far, log_summary,
                                     families_covered or [])

    try:
        raw_candidates = client.generate_candidates(SYSTEM_PROMPT, user_prompt,
                                                     config.CANDIDATES_PER_ROUND)
    except Exception as e:
        print(f"LLM生成失败: {e}")
        return []

    # 后处理: DSL校验 + 拥挤度检测 + 去重
    validated = []
    seen_exprs = set()

    for c in raw_candidates:
        if c.dsl_expr in seen_exprs:
            continue

        # DSL 校验
        try:
            parse_and_validate(c.dsl_expr)
        except Exception as e:
            print(f"DSL校验失败 [{c.dsl_expr[:40]}...]: {e}")
            continue

        # 拥挤度检测
        if is_crowding(c.dsl_expr):
            print(f"拥挤度否决: {c.dsl_expr[:40]}...")
            continue

        seen_exprs.add(c.dsl_expr)
        validated.append(c)

    return validated
