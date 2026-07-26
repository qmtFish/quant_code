"""
因子配置 —— 所有因子列名的唯一来源。

其他文件统一从这里 import，不重复定义。
"""
# ── 27 个标准因子列（对应 CSV 中的列名） ──
FACTOR_COLS = [
    'pe_ratio', 'pb_ratio', 'ps_ratio', 'pcf_ratio',
    'market_cap', 'circulating_market_cap', 'roe', 'roa',
    'gross_profit_margin', 'net_profit_margin', 'inc_revenue_year_on_year',
    'inc_net_profit_year_on_year', 'ret_5d', 'ret_20d', 'ret_60d',
    'volatility_20d', 'hl_range_5d', 'vol_ma_ratio', 'fair_price_deviation',
    'ma_div_20d', 'rsi_14d', 'macd_dif', 'macd_hist', 'kdj_k', 'boll_bias',
    'ind_ret_5d', 'ind_ret_20d', 'ind_vol_20d', 'ind_alpha_20d',
    'hs300_ret_5d', 'hs300_ret_20d', 'zz500_ret_5d', 'zz500_ret_20d',
    'hs300_close', 'zz500_close',
    # 'pe_ratio_z', 'pb_ratio_z', 'ps_ratio_z',
    # 'pcf_ratio_z', 'market_cap_z', 'roe_z', 'roa_z',
    # 'gross_profit_margin_z', 'net_profit_margin_z',
    # 'inc_revenue_year_on_year_z', 'inc_net_profit_year_on_year_z',
    # 'ret_5d_z', 'ret_20d_z', 'ret_60d_z', 'volatility_20d_z',
    # 'hl_range_5d_z', 'vol_ma_ratio_z', 'fair_price_deviation_z',
    # 'ma_div_20d_z', 'rsi_14d_z', 'macd_dif_z', 'macd_hist_z', 'kdj_k_z',
    # 'boll_bias_z', 'size_log_z'
]

# ── 基础因子（需要做 Z-Score 的），不含市场因子 ──
BASE_FACTOR_NAMES = [
    'pe_ratio', 'pb_ratio', 'ps_ratio', 'pcf_ratio',
    'fair_price_deviation',
    'roe', 'roa', 'gross_profit_margin', 'net_profit_margin',
    'inc_revenue_year_on_year', 'inc_net_profit_year_on_year',
    'ret_5d', 'ret_20d', 'ret_60d',
    'volatility_20d', 'hl_range_5d', 'vol_ma_ratio',
]
