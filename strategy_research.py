"""Low-turnover strategy layer diagnostics for BTC factor research.

This script evaluates simple, interpretable signal-to-position rules on the
existing IS/Validation/Holdout split. It is intentionally separate from the LLM
factor loop because the current factor backtest maps every signal through a
rolling z-score, which can create avoidable turnover.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import config
import data as data_module
from backtest import annualized_sharpe, directional_accuracy, max_drawdown


PUBLIC_CONFIG_KEYS = [
    "INST_ID",
    "BAR",
    "HISTORY_DAYS",
    "SPLIT_RATIOS",
    "COST_BPS",
    "SLIPPAGE_BPS",
    "FUNDING_INTERVAL",
    "INITIAL_CAPITAL",
    "LEVERAGE",
]


def _periods_per_year() -> int:
    if config.BAR == "15m":
        return 365 * 24 * 4
    if config.BAR == "1H":
        return 365 * 24
    if config.BAR == "4H":
        return 365 * 6
    return 365 * 24


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _rolling_vwap(df: pd.DataFrame, window: int) -> pd.Series:
    dollar_volume = (df["close"] * df["volume"]).rolling(window, min_periods=window).sum()
    volume = df["volume"].rolling(window, min_periods=window).sum()
    return dollar_volume / volume.replace(0, np.nan)


def _update_mask(index: pd.DatetimeIndex, update: str) -> pd.Series:
    if update == "hourly":
        return pd.Series(True, index=index)
    s = pd.Series(index=index, data=index)
    if update == "daily":
        bucket = s.dt.floor("D")
    elif update == "weekly":
        iso = s.dt.isocalendar()
        bucket = iso["year"].astype(str) + "-" + iso["week"].astype(str)
    else:
        raise ValueError(f"unknown update frequency: {update}")
    return bucket.ne(bucket.shift(1)).fillna(True)


def _hold_to_update(desired: pd.Series, update: str) -> pd.Series:
    desired = desired.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    mask = _update_mask(desired.index, update)
    held = desired.where(mask).ffill().fillna(0.0)
    return held.clip(-1.0, 1.0)


def _pos_from_bool(long_cond: pd.Series, short_cond: pd.Series | None = None) -> pd.Series:
    pos = pd.Series(0.0, index=long_cond.index)
    pos[long_cond.fillna(False)] = 1.0
    if short_cond is not None:
        pos[short_cond.fillna(False)] = -1.0
    return pos


def _position_backtest(
    desired_position: pd.Series,
    ohlcv: pd.DataFrame,
    cost_bps: int | None = None,
    slippage_bps: int | None = None,
    funding_rate_series: pd.Series | None = None,
) -> dict:
    cost_bps = config.COST_BPS if cost_bps is None else cost_bps
    slippage_bps = config.SLIPPAGE_BPS if slippage_bps is None else slippage_bps

    desired_position = desired_position.reindex(ohlcv.index).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    position = desired_position.shift(1).fillna(0.0).clip(-1.0, 1.0)
    ret = ohlcv["close"].pct_change().fillna(0.0)
    gross_pnl = position * ret
    turnover = position.diff().abs().fillna(position.abs())
    cost = turnover * (cost_bps + slippage_bps) / 10000.0
    if funding_rate_series is None:
        funding_cost = pd.Series(0.0, index=ohlcv.index)
        funding_observations = 0
    else:
        funding_aligned = funding_rate_series.reindex(ohlcv.index)
        funding_observations = int(funding_aligned.notna().sum())
        funding = funding_aligned.fillna(0.0)
        funding_cost = position * funding * getattr(config, "LEVERAGE", 1)
    net_pnl = (gross_pnl - cost - funding_cost).fillna(0.0)
    no_cost_pnl = gross_pnl.fillna(0.0)

    return {
        "sharpe": float(annualized_sharpe(net_pnl, _periods_per_year())),
        "no_cost_sharpe": float(annualized_sharpe(no_cost_pnl, _periods_per_year())),
        "max_drawdown": float(max_drawdown(net_pnl)),
        "win_rate": float((net_pnl > 0).mean()),
        "expectancy": float(net_pnl.mean()),
        "total_return": float(net_pnl.sum()),
        "gross_return": float(no_cost_pnl.sum()),
        "cost_paid": float(cost.sum()),
        "funding_paid": float(funding_cost.sum()),
        "funding_abs_paid": float(funding_cost.abs().sum()),
        "funding_observations": funding_observations,
        "turnover": float(turnover.mean()),
        "trades": int((turnover > 0).sum()),
        "exposure": float((position != 0).mean()),
        "long_frac": float((position > 0).mean()),
        "short_frac": float((position < 0).mean()),
        "directional_accuracy": float(directional_accuracy(position, ret)),
    }


def _split_results(
    position: pd.Series,
    splits: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    funding_rate_series: pd.Series | None = None,
) -> dict:
    names = ["IS", "Val", "Holdout"]
    return {
        name: _position_backtest(position.reindex(df.index), df, funding_rate_series=funding_rate_series)
        for name, df in zip(names, splits)
    }


def _val_subperiods(
    position: pd.Series,
    val_data: pd.DataFrame,
    parts: int = 2,
    funding_rate_series: pd.Series | None = None,
) -> list[dict]:
    out = []
    for idx in np.array_split(np.arange(len(val_data)), parts):
        part = val_data.iloc[idx]
        out.append(_position_backtest(position.reindex(part.index), part, funding_rate_series=funding_rate_series))
    return out


def _lagged_funding_features(df: pd.DataFrame, funding_rates: pd.Series | None) -> dict[str, pd.Series]:
    if funding_rates is None or funding_rates.empty:
        return {}

    funding = funding_rates.sort_index().reindex(df.index, method="ffill").shift(1)
    mean_90d = funding.rolling(24 * 90, min_periods=24 * 30).mean()
    std_90d = funding.rolling(24 * 90, min_periods=24 * 30).std()
    zscore = ((funding - mean_90d) / std_90d.replace(0, np.nan)).clip(-5, 5)
    return {
        "funding": funding,
        "funding_zscore": zscore,
    }


def _make_positions(df: pd.DataFrame, funding_rates: pd.Series | None = None) -> dict[str, pd.Series]:
    close = df["close"]
    ema20 = _ema(close, 20)
    ema50 = _ema(close, 50)
    ema100 = _ema(close, 100)
    ema200 = _ema(close, 200)
    atr14 = _atr(df, 14)
    atr_pct = atr14 / close
    atr_median = atr_pct.rolling(120, min_periods=60).median()
    vwap72 = _rolling_vwap(df, 72)
    vwap168 = _rolling_vwap(df, 168)
    rsi14 = _rsi(close, 14)
    bb_mid = close.rolling(20, min_periods=20).mean()
    bb_std = close.rolling(20, min_periods=20).std()
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std
    high72 = close.rolling(72, min_periods=72).max().shift(1)
    low72 = close.rolling(72, min_periods=72).min().shift(1)
    ema20_rank = ema20.rolling(100, min_periods=60).rank(pct=True)
    vol_rank = df["volume"].rolling(120, min_periods=60).rank(pct=True)
    ret24 = close.pct_change(24)
    ret20 = close.pct_change(20)
    mean50 = close.rolling(50, min_periods=50).mean()
    rng = np.random.default_rng(20260703)
    random_noise = pd.Series(rng.standard_normal(len(df)), index=df.index)
    positions = {
        "buy_hold_direct": pd.Series(1.0, index=df.index),
        "random_noise_control": _pos_from_bool(random_noise > 0, random_noise < 0),
        "naive_momentum_20_long_short": _pos_from_bool(ret20 > 0, ret20 < 0),
        "naive_momentum_20_long_flat": _pos_from_bool(ret20 > 0),
        "naive_mean_reversion_50_long_short": _pos_from_bool(close < mean50, close > mean50),
        "naive_mean_reversion_50_long_flat": _pos_from_bool(close < mean50),
        "ema50_200_long_short": _pos_from_bool(ema50 > ema200, ema50 < ema200),
        "ema50_200_long_flat": _pos_from_bool(ema50 > ema200),
        "close_ema200_long_short": _pos_from_bool(close > ema200, close < ema200),
        "close_ema200_long_flat": _pos_from_bool(close > ema200),
        "ema200_slope_long_short": _pos_from_bool(ema200 > ema200.shift(24), ema200 < ema200.shift(24)),
        "ema100_slope_long_flat": _pos_from_bool(ema100 > ema100.shift(24)),
        "slow_ema_rank_band_long_short": _pos_from_bool(ema20_rank > 0.60, ema20_rank < 0.40),
        "slow_ema_rank_band_long_flat": _pos_from_bool(ema20_rank > 0.60),
        "vwap72_trend_long_short": _pos_from_bool(close > vwap72, close < vwap72),
        "vwap168_trend_long_flat": _pos_from_bool(close > vwap168),
        "vwap72_reversion_long_short": _pos_from_bool(close < vwap72 * 0.995, close > vwap72 * 1.005),
        "vol_compression_trend_long_flat": _pos_from_bool((close > ema200) & (atr_pct < atr_median)),
        "atr_expansion_short_filter": _pos_from_bool(close > ema200, (close < ema200) & (atr_pct > atr_median)),
        "breakout72_long_short": _pos_from_bool(close > high72, close < low72),
        "breakout72_low_vol_long_flat": _pos_from_bool((close > high72) & (atr_pct < atr_median)),
        "rsi_reversal_14_long_short": _pos_from_bool(rsi14 < 30, rsi14 > 70),
        "bollinger_reversion_long_short": _pos_from_bool(close < bb_lower, close > bb_upper),
        "volume_confirmed_momentum": _pos_from_bool((ret24 > 0) & (vol_rank > 0.55), (ret24 < 0) & (vol_rank > 0.55)),
        "volume_exhaustion_reversal": _pos_from_bool((ret24 < 0) & (vol_rank > 0.80), (ret24 > 0) & (vol_rank > 0.80)),
    }
    funding_features = _lagged_funding_features(df, funding_rates)
    if funding_features:
        funding = funding_features["funding"]
        funding_z = funding_features["funding_zscore"]
        positions.update(
            {
                "funding_carry_long_short": _pos_from_bool(funding < -0.00002, funding > 0.00007),
                "funding_extreme_reversal_long_short": _pos_from_bool(funding_z < -1.5, funding_z > 1.5),
                "trend_carry_aligned_long_short": _pos_from_bool(
                    (close > ema200) & (funding <= 0.00005),
                    (close < ema200) & (funding >= 0.0),
                ),
                "trend_no_euphoria_long_flat": _pos_from_bool((close > ema200) & (funding_z < 1.0)),
            }
        )
    return positions


def _sort_key(row: dict) -> tuple:
    val = row["splits"]["Val"]
    hold = row["splits"]["Holdout"]
    min_val_sub = min(part["sharpe"] for part in row["val_subperiods"])
    return (
        val["sharpe"] > 0,
        hold["sharpe"] > -0.50,
        min_val_sub > -0.25,
        val["sharpe"],
        hold["sharpe"],
    )


def main() -> int:
    df = data_module.load_data(config.INST_ID, config.BAR, config.HISTORY_DAYS)
    funding_rates = data_module.load_funding_rates(config.INST_ID, config.HISTORY_DAYS)
    splits = data_module.split_data(df)
    ranges = data_module.get_time_ranges(df)
    base_positions = _make_positions(df, funding_rates)
    rows = []

    for rule_name, desired in base_positions.items():
        for update in ["hourly", "daily", "weekly"]:
            held = _hold_to_update(desired, update)
            split_metrics = _split_results(held, splits, funding_rates)
            val_subperiods = _val_subperiods(held, splits[1], funding_rate_series=funding_rates)
            val = split_metrics["Val"]
            hold = split_metrics["Holdout"]
            min_val_sub = min(part["sharpe"] for part in val_subperiods)
            status = "reject"
            if val["sharpe"] > 0 and min_val_sub > -0.25:
                status = "val_candidate"
            if status == "val_candidate" and hold["sharpe"] >= -0.50 and hold["max_drawdown"] <= 0.45:
                status = "holdout_survived"

            rows.append(
                {
                    "rule": rule_name,
                    "update": update,
                    "status": status,
                    "splits": split_metrics,
                    "val_subperiods": val_subperiods,
                }
            )

    rows = sorted(rows, key=_sort_key, reverse=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "created_at_utc": timestamp,
        "config": {key: getattr(config, key, None) for key in PUBLIC_CONFIG_KEYS},
        "time_ranges": {key: str(value) for key, value in ranges.items()},
        "selection_note": "Diagnostics only. Holdout is audit evidence, not a tuning target.",
        "rows": rows,
    }

    out_path = Path(config.LOG_DIR) / f"strategy_research_report_{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"WROTE {out_path}")
    print("TOP_DIAGNOSTICS")
    for row in rows[:20]:
        val = row["splits"]["Val"]
        hold = row["splits"]["Holdout"]
        is_ = row["splits"]["IS"]
        min_val_sub = min(part["sharpe"] for part in row["val_subperiods"])
        print(
            f"{row['status']:16s} {row['rule']:32s} {row['update']:6s} "
            f"IS {is_['sharpe']:6.2f} Val {val['sharpe']:6.2f} "
            f"ValSubMin {min_val_sub:6.2f} Hold {hold['sharpe']:6.2f} "
            f"DD {hold['max_drawdown']:5.2%} Turn {val['turnover']:.4f} Cost {val['cost_paid']:.4f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
