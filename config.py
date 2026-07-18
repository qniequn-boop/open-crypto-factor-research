# btclab/config.py
# 所有配置参数 —— 严格按照 PROJECT_DOC.md §10.4

# === 数据 ===
import json as _json
import os as _os
from pathlib import Path as _Path

INST_ID = 'BTC-USDT-SWAP'
BAR = '1H'  # 从15m切到1H: 噪声降4倍, 成本降4倍
HISTORY_DAYS = 730  # 约2年

# === 多资产因子研究 ===
# The registry is the source of truth. Historical eligibility is computed from
# lagged data; this frozen candidate pool is never backfilled as a static rank.
PANEL_UNIVERSE_REGISTRY = str(_Path(__file__).with_name('PANEL_UNIVERSE_REGISTRY.json'))
with _Path(PANEL_UNIVERSE_REGISTRY).open(encoding='utf-8') as _fh:
    _PANEL_UNIVERSE = _json.load(_fh)
PANEL_INST_IDS = [row['inst_id'] for row in _PANEL_UNIVERSE['assets']]
PANEL_HISTORY_DAYS = 730
PANEL_MIN_ASSETS = 20
PANEL_REBALANCE_HOURS = 24
PANEL_UNIVERSE_TARGET_SIZE = _PANEL_UNIVERSE['point_in_time_rules']['target_size']

# === 数据切分 (D6, 跟 HypCrypto 50:17:33) ===
SPLIT_RATIOS = (0.50, 0.17, 0.33)  # IS / Validation / Holdout
# 切点在数据加载后按 bar 数固定, 全程不变

# === 回测成本 (D5, D9) ===
COST_BPS = 5          # taker 0.05% 单边
SLIPPAGE_BPS = 2      # 固定滑点, 纸上交易校准
FUNDING_INTERVAL = 8  # 1H * 8 = 8h

# === 资金 (D9) ===
INITIAL_CAPITAL = 300  # USDT
LEVERAGE = 5           # 逐仓

# === 过拟合检测 (D3) ===
OOS_SHARPE_FLOOR = 0.6     # Validation夏普 >= IS夏普 * 0.6
PARAM_SENSITIVITY_PCT = 0.20  # 参数 +-20% 扫描
MAX_CORRELATION = 0.7     # 与已晋升候选的最大相关性
MAX_DRAWDOWN = 0.30       # 回撤超过30%直接否决 (D9)

# === LLM (假设生成器) ===
LLM_BASE_URL = 'https://api.deepseek.com'      # 填API地址(兼容OpenAI格式)
LLM_API_KEY = _os.environ.get('LLM_API_KEY', '')
LLM_MODEL = 'deepseek-v4-pro'         # 填模型名
LLM_TIMEOUT = 60       # 秒
CANDIDATES_PER_ROUND = 20  # 每轮生成候选数
MAX_ROUNDS = 10

# === 多样性 (D8) ===
MIN_FAMILIES_PER_ROUND = 3   # 每轮至少覆盖3个因子家族
AST_SIMILARITY_THRESHOLD = 0.85  # AST相似度上限, 超过则丢弃

# === 纸上交易 ===
PAPER_TRADE_DAYS = 14  # 纸上交易持续天数

# === 数据缓存 ===
CACHE_DIR = 'data_cache'
LOG_DIR = 'logs'

# === 随机种子(可复现) ===
RANDOM_SEED = 42

# === OKX API 参数 ===
OKX_BASE_URL = 'https://www.okx.com'
OKX_RATE_LIMIT = 0.12  # 秒间隔
