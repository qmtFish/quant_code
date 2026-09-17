# 全局配置
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / 'data' / 'all_data'
FACTOR_DIR = ROOT / 'data' / 'factors'
RESULT_DIR = ROOT / 'results'
COEF_DIR = ROOT / 'coefficients'

for d in [DATA_DIR, FACTOR_DIR, RESULT_DIR, COEF_DIR,
          DATA_DIR/'daily', DATA_DIR/'financial', DATA_DIR/'index']:
    d.mkdir(parents=True, exist_ok=True)

# ════════════════════════════════════════════
# 股票池配置
# ════════════════════════════════════════════
STOCK_POOL = 'ALL'  # 'ALL' | 'HS300' | 'ZZ500'
MIN_LIST_DAYS = 365   # 上市至少1年
EXCLUDE_ST = True
EXCLUDE_PAUSED = True

# ════════════════════════════════════════════
# 模型训练配置
# ════════════════════════════════════════════
TRAIN_WINDOW = 180    # 训练窗口天数
TRAIN_MODEL = 'catboost'
BACKTEST_START = '2024-07-05'
BACKTEST_END = '2026-06-12'
TOP_N = 5             # 分5组
COMMISSION = 0.0003   # 万3
SLIPPAGE = 0.001      # 千1滑点

# ════════════════════════════════════════════
# 因子计算配置
# ════════════════════════════════════════════
ZSCORE_CAP = 5.0      # zscore 截断
MIN_STOCKS = 50       # 少于该数量跳过该期

# ════════════════════════════════════════════
# 新回测引擎配置
# ════════════════════════════════════════════
INITIAL_CASH = 10_000_000    # 初始资金 1000万
BENCHMARK_CODE = 'hs300'     # 基准指数
COMMISSION_RATE = 0.00025    # 佣金万2.5
MIN_COMMISSION = 5.0         # 最低佣金5元
STAMP_TAX_RATE = 0.001       # 印花税千1
TRANSFER_FEE_RATE = 0.00001  # 过户费万0.1
SLIPPAGE_MODE = 'fixed'      # 滑点模式: fixed | price_related | volume_related
BASE_SLIPPAGE = 0.002        # 基础滑点千2
ORDER_VOLUME_RATIO = 0.25    # 单笔订单不超过日成交额25%
MIN_ORDER_VALUE = 1000       # 最小调仓金额
MAX_STOCK_WEIGHT = 0.10      # 单只股票最大权重10%
REBALANCE_FREQ = 'weekly'    # 调仓频率: weekly | biweekly | monthly
TOP_K = 10                   # 全局选股数量

# ════════════════════════════════════════════
# 统一数据路径
# ════════════════════════════════════════════
# factor_data(特征+industry) + label_data(next_ret) 合并产物，见 scripts/merge_factor_label.py
DATA_PATH = str(ROOT / 'data' / 'all_processed_data' / 'train_data_2023-07-17_2026-07-24.csv')

# 权重文件路径
WEIGHT_FILE = str(COEF_DIR / 'factor_coefficients_6m_rolling.json')
