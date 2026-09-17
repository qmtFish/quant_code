"""
因子配置 —— 所有因子列名的唯一来源。

其他文件统一从这里 import，不重复定义。
"""
# ── 数据泄露（leak）列前缀：以这些前缀开头的列一律不允许作为因子 ──
# fwd_*  = 未来 N 日收益/超额收益（forward，未来信息）
# up_*   = 未来 N 日是否上涨
# rank_* = 未来 N 日收益排名
# 2026-08 核对：label_data_*.csv 中 24 个 fwd_*/up_*/rank_* 列全部属于此类，
# 已全部剔除，不作为因子。
LEAK_PREFIXES = ('fwd_', 'up_', 'rank_')

# ── 非因子列（标识/标签，不参与建模） ──
NON_FACTOR_COLS = {'date', 'code', 'industry', 'next_ret'}

# ── 29 个标准因子列（对应 CSV 中的列名） ──
# 2026-08 依据 data/all_processed_data/factor_data_*.csv / local_train_data_*.csv 逐列核对：
#   29 个全部存在于数据中（factor_data 缺 fair_price_deviation 一个，local_train_data 全有）
#   剔除 6 个"同日常数"因子（同一交易日对所有股票取值相同，横截面无区分度）：
#     hs300_ret_5d / hs300_ret_20d / zz500_ret_5d / zz500_ret_20d / hs300_close / zz500_close
#   剔除 24 个 fwd_*/up_*/rank_* 未来信息列（数据泄露）
FACTOR_COLS = [
    'pe_ratio', 'pb_ratio', 'ps_ratio', 'pcf_ratio',
    'market_cap', 'circulating_market_cap', 'roe', 'roa',
    'gross_profit_margin', 'net_profit_margin', 'inc_revenue_year_on_year',
    'inc_net_profit_year_on_year', 'ret_5d', 'ret_20d', 'ret_60d',
    'volatility_20d', 'hl_range_5d', 'vol_ma_ratio', 'fair_price_deviation',
    'ma_div_20d', 'rsi_14d', 'macd_dif', 'macd_hist', 'kdj_k', 'boll_bias',
    'ind_ret_5d', 'ind_ret_20d', 'ind_vol_20d', 'ind_alpha_20d',
    # ── 趋势/通道因子（2026-08 新增，见 factors/trend_factors.py）──
    # 描述 K 线趋势：斜率(方向/速度)、R²(通道规整度)、通道位置、反弹力度、
    # 高低点结构、均线排列、回撤深度
    'trend_slope_20d', 'trend_slope_60d', 'trend_r2_20d',
    'channel_pos_20d', 'bounce_5d', 'lower_high_5d',
    'ma_align_20d', 'drawdown_60d',
    # trend_r2_60d 与 trend_r2_20d 强相关，暂不启用（如需可移回上面）：
    # 'trend_r2_60d',
    # 以下为剔除的同日常数市场因子，如需恢复可移回上面：
    # 'hs300_ret_5d', 'hs300_ret_20d', 'zz500_ret_5d', 'zz500_ret_20d',
    # 'hs300_close', 'zz500_close',
    # 数据中存在 *_z 截面标准化列，与原值 1:1 冗余（强共线），不启用：
    # 'pe_ratio_z', 'pb_ratio_z', 'ps_ratio_z',
    # 'pcf_ratio_z', 'market_cap_z', 'roe_z', 'roa_z',
    # 'gross_profit_margin_z', 'net_profit_margin_z',
    # 'inc_revenue_year_on_year_z', 'inc_net_profit_year_on_year_z',
    # 'ret_5d_z', 'ret_20d_z', 'ret_60d_z', 'volatility_20d_z',
    # 'hl_range_5d_z', 'vol_ma_ratio_z', 'fair_price_deviation_z',
    # 'ma_div_20d_z', 'rsi_14d_z', 'macd_dif_z', 'macd_hist_z', 'kdj_k_z',
    # 'boll_bias_z', 'size_log_z'
]


def available_factor_cols(columns) -> list:
    """从数据实际列中筛出可用因子。

    规则（以数据实际包含的列为基础，剔除会 leak 的因子）：
      1. 只取 FACTOR_COLS 白名单中数据里真实存在的列
      2. 自动剔除 LEAK_PREFIXES（fwd_*/up_*/rank_* 未来信息列）
      3. 自动剔除 NON_FACTOR_COLS（date/code/industry/next_ret）

    保证任何输入数据都不会把未来收益类列误当作因子。
    """
    cols = set(columns)
    return [c for c in FACTOR_COLS
            if c in cols
            and not c.startswith(LEAK_PREFIXES)
            and c not in NON_FACTOR_COLS]

# ── 基础因子（需要做 Z-Score 的），不含市场因子 ──
BASE_FACTOR_NAMES = [
    'pe_ratio', 'pb_ratio', 'ps_ratio', 'pcf_ratio',
    'fair_price_deviation',
    'roe', 'roa', 'gross_profit_margin', 'net_profit_margin',
    'inc_revenue_year_on_year', 'inc_net_profit_year_on_year',
    'ret_5d', 'ret_20d', 'ret_60d',
    'volatility_20d', 'hl_range_5d', 'vol_ma_ratio',
]
