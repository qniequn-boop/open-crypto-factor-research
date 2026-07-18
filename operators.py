# btclab/operators.py
# DSL算子实现 —— 严格按照 PROJECT_DOC.md 10.2 算子签名表
# 所有算子均为向量化实现, 只用 t 及之前数据(无未来函数)

import numpy as np
import pandas as pd
from typing import Dict, Callable, Any

class OperatorRegistry:
    _operators: Dict[str, dict] = {}

    @classmethod
    def register(cls, name: str, func: Callable, arity: int, signature: str, description: str):
        cls._operators[name] = {"func": func, "arity": arity, "signature": signature, "description": description, "safe": True}

    @classmethod
    def get(cls, name: str):
        return cls._operators.get(name)

    @classmethod
    def exists(cls, name: str):
        return name in cls._operators

    @classmethod
    def list_all(cls):
        return list(cls._operators.keys())

FIELD_NAMES = {"close", "open", "high", "low", "volume"}

# ---- operators ----
def _close_fn(data): return data["close"].copy()
def _open_fn(data): return data["open"].copy()
def _high_fn(data): return data["high"].copy()
def _low_fn(data): return data["low"].copy()
def _volume_fn(data): return data["volume"].copy()
def _returns(s, n): return (s - s.shift(n)) / s.shift(n)
def _log_returns(s, n): return np.log(s / s.shift(n))
def _diff(s, n): return s - s.shift(n)
def _ema(s, n): return s.ewm(span=n, adjust=False).mean()
def _sma(s, n): return s.rolling(window=n).mean()
def _ts_mean(s, n): return _sma(s, n)
def _atr(h, l, c, n):
    tr = pd.concat([h - l, (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(span=n, adjust=False).mean()
def _std(s, n): return s.rolling(window=n).std(ddof=0)
def _rsi(c, n):
    d = c.diff(); g = d.clip(lower=0); l = (-d).clip(lower=0)
    ag = g.ewm(span=n, adjust=False).mean(); al = l.ewm(span=n, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))
def _ts_rank(s, n): return s.rolling(window=n).apply(lambda x: pd.Series(x).rank().iloc[-1] / len(x), raw=False)
def _quantile(s, n, q): return s.rolling(window=n).quantile(q)
def _zscore(s, n):
    m = s.rolling(window=n).mean(); d = s.rolling(window=n).std(ddof=0)
    return (s - m) / d.replace(0, np.nan)
def _bb_bw(c, n, k):
    m = c.rolling(window=n).mean(); d = c.rolling(window=n).std(ddof=0)
    u = m + k * d; l = m - k * d
    return (u - l) / m
def _bb_pctb(c, n, k):
    m = c.rolling(window=n).mean(); d = c.rolling(window=n).std(ddof=0)
    u = m + k * d; l = m - k * d
    return (c - l) / (u - l)
def _squeeze(h, l, c, bn, bk, kn, kk):
    m = c.rolling(window=bn).mean(); d = c.rolling(window=bn).std(ddof=0)
    bu = m + bk * d; bl = m - bk * d
    at = _atr(h, l, c, kn)
    km = c.rolling(window=kn).mean(); ku = km + kk * at; kl = km - kk * at
    return ((bu <= ku) & (bl >= kl)).astype(float)
def _ts_max(s, n): return s.rolling(window=n).max()
def _ts_min(s, n): return s.rolling(window=n).min()
def _ts_corr(s1, s2, n): return s1.rolling(window=n).corr(s2)
def _ts_delay(s, n): return s.shift(n)
def _add(s1, s2): return s1 + s2
def _sub(s1, s2): return s1 - s2
def _mul(s1, s2): return s1 * s2
def _div(s1, s2): return s1 / s2.replace(0, np.nan)
def _max_f(s1, s2): return pd.concat([s1, s2], axis=1).max(axis=1)
def _min_f(s1, s2): return pd.concat([s1, s2], axis=1).min(axis=1)
def _abs_f(s): return s.abs()
def _neg(s): return -s
def _if_f(c, s1, s2): return pd.Series(np.where(c.values > 0, np.asarray(s1) if np.isscalar(s1) else s1.values, np.asarray(s2) if np.isscalar(s2) else s2.values), index=c.index)
def _gt(s1, s2): return (s1 > s2).astype(float)
def _lt(s1, s2): return (s1 < s2).astype(float)

def _register_all():
    r = OperatorRegistry
    r.register("close", _close_fn, 0, "close -> Series", "")
    r.register("open", _open_fn, 0, "open -> Series", "")
    r.register("high", _high_fn, 0, "high -> Series", "")
    r.register("low", _low_fn, 0, "low -> Series", "")
    r.register("volume", _volume_fn, 0, "volume -> Series", "")
    r.register("returns", _returns, 2, "returns(series,n) -> Series", "")
    r.register("log_returns", _log_returns, 2, "log_returns(series,n) -> Series", "")
    r.register("diff", _diff, 2, "diff(series,n) -> Series", "")
    r.register("ema", _ema, 2, "ema(series,n) -> Series", "")
    r.register("sma", _sma, 2, "sma(series,n) -> Series", "")
    r.register("ts_mean", _ts_mean, 2, "ts_mean(series,n) -> Series", "")
    r.register("atr", _atr, 4, "atr(high,low,close,n) -> Series", "")
    r.register("std", _std, 2, "std(series,n) -> Series", "")
    r.register("rsi", _rsi, 2, "rsi(close,n) -> Series", "")
    r.register("ts_rank", _ts_rank, 2, "ts_rank(series,n) -> Series", "")
    r.register("quantile", _quantile, 3, "quantile(series,n,q) -> Series", "")
    r.register("zscore", _zscore, 2, "zscore(series,n) -> Series", "")
    r.register("bb_bw", _bb_bw, 3, "bb_bw(close,n,k) -> Series", "")
    r.register("bb_pctb", _bb_pctb, 3, "bb_pctb(close,n,k) -> Series", "")
    r.register("squeeze", _squeeze, 7, "squeeze(high,low,close,bb_n,bb_k,kc_n,kc_k) -> Series", "")
    r.register("ts_max", _ts_max, 2, "ts_max(series,n) -> Series", "")
    r.register("ts_min", _ts_min, 2, "ts_min(series,n) -> Series", "")
    r.register("ts_corr", _ts_corr, 3, "ts_corr(s1,s2,n) -> Series", "")
    r.register("ts_delay", _ts_delay, 2, "ts_delay(series,n) -> Series", "")
    r.register("add", _add, 2, "add(s1,s2) -> Series", "")
    r.register("sub", _sub, 2, "sub(s1,s2) -> Series", "")
    r.register("mul", _mul, 2, "mul(s1,s2) -> Series", "")
    r.register("div", _div, 2, "div(s1,s2) -> Series", "")
    r.register("max", _max_f, 2, "max(s1,s2) -> Series", "")
    r.register("min", _min_f, 2, "min(s1,s2) -> Series", "")
    r.register("abs", _abs_f, 1, "abs(series) -> Series", "")
    r.register("neg", _neg, 1, "neg(series) -> Series", "")
    r.register("if", _if_f, 3, "if(cond,s1,s2) -> Series", "")
    r.register("gt", _gt, 2, "gt(s1,s2) -> Series", "")
    r.register("lt", _lt, 2, "lt(s1,s2) -> Series", "")
    # Python keyword workaround
    r._operators["_if"] = r._operators["if"]

_register_all()
