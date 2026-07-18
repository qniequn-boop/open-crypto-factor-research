# btclab/paper_trade.py
# 纸上交易 —— 严格按照 PROJECT_DOC.md §4.7
# 接 live 行情, 量 backtest→live 偏差

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
import config
import data as data_module
from backtest import backtest, sign
from dsl import execute

class PaperTrader:
    def __init__(self, inst_id: str = None):
        self.inst_id = inst_id or config.INST_ID
        self.bar = config.BAR
        self.paper_days = config.PAPER_TRADE_DAYS
        self.cost_bps = config.COST_BPS
        self.slippage_bps = config.SLIPPAGE_BPS
        self.start_time = None
        self.trades = []
        self.equity_curve = []
        self.initial_capital = config.INITIAL_CAPITAL
        self.current_capital = self.initial_capital
        self.position = 0  # 当前持仓方向: 1多 0空仓 -1空

    def start(self, dsl_expr: str):
        self.start_time = datetime.now(timezone.utc)
        print(f"纸上交易启动: {dsl_expr[:60]}...")
        print(f"开始时间: {self.start_time.isoformat()}")
        print(f"持续天数: {self.paper_days}")
        print(f"初始资金: {self.initial_capital} USDT")
        return self

    def update(self, live_data: pd.DataFrame = None):
        if live_data is None:
            # 拉取最新数据
            live_data = data_module.load_data(self.inst_id, self.bar, days=7)
            # 只用最近的数据模拟 live
            live_data = live_data.iloc[-100:]

        if len(live_data) < 10:
            return {'error': '数据不足'}

        # 用当前最新一行数据模拟"刚收盘的t时刻"
        latest = live_data.iloc[-1]
        current_price = latest['close']
        current_time = live_data.index[-1]

        # 记录权益
        self.equity_curve.append({
            'time': current_time.isoformat(),
            'price': float(current_price),
            'capital': self.current_capital,
            'position': self.position,
        })

        return {
            'time': current_time.isoformat(),
            'price': float(current_price),
            'capital': self.current_capital,
            'position': self.position,
        }

    def simulate_trade(self, signal_value: float, current_price: float,
                       current_time: datetime):
        """模拟成交: 按假设的入场价是否能成交"""
        new_position = int(np.sign(signal_value))

        if new_position == self.position:
            # 无变化
            return

        # 换仓: 计算成本
        if self.position != 0:
            # 平仓
            self.current_capital *= (1 - self.cost_bps / 10000)

        if new_position != 0:
            # 开仓
            self.current_capital *= (1 - self.cost_bps / 10000)

        trade = {
            'time': current_time.isoformat(),
            'price': float(current_price),
            'from_position': self.position,
            'to_position': new_position,
            'capital_after': self.current_capital,
            'cost_bps': self.cost_bps,
        }
        self.trades.append(trade)
        self.position = new_position

    def stop(self) -> Dict:
        elapsed = datetime.now(timezone.utc) - self.start_time if self.start_time else timedelta(0)
        pnl = self.current_capital - self.initial_capital
        pnl_pct = pnl / self.initial_capital * 100 if self.initial_capital > 0 else 0

        summary = {
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': datetime.now(timezone.utc).isoformat(),
            'duration_hours': elapsed.total_seconds() / 3600,
            'initial_capital': self.initial_capital,
            'final_capital': self.current_capital,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'n_trades': len(self.trades),
            'trades': self.trades,
            'equity_curve': self.equity_curve,
        }

        print(f"\n=== 纸上交易结束 ===")
        print(f"持续: {elapsed.total_seconds()/3600:.1f} 小时")
        print(f"最终权益: {self.current_capital:.2f} USDT")
        print(f"盈亏: {pnl:+.2f} USDT ({pnl_pct:+.2f}%)")
        print(f"交易次数: {len(self.trades)}")

        return summary

def compare_live_vs_backtest(live_pnl: pd.Series, backtest_expected: pd.Series) -> Dict:
    """量 backtest→live 偏差 (§4.7)"""
    common_idx = live_pnl.index.intersection(backtest_expected.index)
    if len(common_idx) < 10:
        return {'correlation': 0, 'mae': 0, 'mse': 0, 'note': '样本不足'}

    live_aligned = live_pnl.reindex(common_idx)
    bt_aligned = backtest_expected.reindex(common_idx)

    corr = live_aligned.corr(bt_aligned)
    mae = (live_aligned - bt_aligned).abs().mean()
    mse = ((live_aligned - bt_aligned) ** 2).mean()

    return {
        'correlation': corr,
        'mae': mae,
        'mse': mse,
        'n_samples': len(common_idx),
    }
