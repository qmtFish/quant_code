"""
市场/行业因子插件。
参考 factor_builder.py 中的 market factors 部分。
"""
from typing import List, Dict
import pandas as pd
import numpy as np


def compute(date: pd.Timestamp,
            stocks: List[str],
            daily: pd.DataFrame,
            financial: pd.DataFrame,
            index: Dict[str, pd.DataFrame],
            industry: pd.DataFrame) -> pd.DataFrame:
    """
    计算市场/行业因子。

    返回列:
        ind_ret_5d, ind_ret_20d, ind_vol_20d, ind_alpha_20d,
        hs300_ret_5d, hs300_ret_20d,
        zz500_ret_5d, zz500_ret_20d,
        size_log_z
    """
    result = pd.DataFrame(index=stocks)

    # --- 指数收益率 ---
    for idx_name, periods in [('hs300', [5, 20]), ('zz500', [5, 20])]:
        idx_df = index.get(idx_name)
        if idx_df is None or idx_df.empty:
            continue
        idx_close = idx_df['close']
        idx_close = idx_close[idx_close.index <= pd.Timestamp(date)]

        for p in periods:
            label = f'{idx_name}_ret_{p}d'
            if len(idx_close) >= p:
                result[label] = (idx_close.iloc[-1] / idx_close.iloc[-p] - 1)
            else:
                result[label] = 0.0

    # --- 行业收益率 ---
    # 取 date 前 60 日日线
    hist = daily.loc[:date].tail(60).copy()
    if hist.empty:
        result['ind_ret_20d'] = 0.0
        result['ind_vol_20d'] = 0.0
        result['ind_alpha_20d'] = 0.0
        return result.fillna(0)

    hist = hist[hist.index.get_level_values('code').isin(stocks)]
    close = hist['close'].unstack('code')
    ret = close.pct_change().fillna(0)
    n = len(close)

    # 行业分类映射
    if industry is not None and 'industry_code' in industry.columns:
        ind_map = industry['industry_code'].to_dict()
    else:
        ind_map = {}

    # 简单等权全市场平均收益率作为行业收益率近似
    # 更精确做法：按行业分组计算
    if n >= 20:
        ind_ret_ts = ret.iloc[-20:].mean(axis=1)  # 每日全市场平均
        result['ind_ret_20d'] = (1 + ind_ret_ts).prod() - 1
        result['ind_vol_20d'] = ind_ret_ts.std()

        # alpha = 行业收益率 - hs300收益率
        hs300_close = index.get('hs300', pd.DataFrame()).get('close', pd.Series(dtype=float))
        if not hs300_close.empty:
            hs300_close = hs300_close[hs300_close.index <= pd.Timestamp(date)]
            if len(hs300_close) >= 20:
                hs300_ret_20d = hs300_close.iloc[-1] / hs300_close.iloc[-20] - 1
                result['ind_alpha_20d'] = result['ind_ret_20d'] - hs300_ret_20d
            else:
                result['ind_alpha_20d'] = 0.0
        else:
            result['ind_alpha_20d'] = 0.0
    else:
        result['ind_ret_20d'] = 0.0
        result['ind_vol_20d'] = 0.0
        result['ind_alpha_20d'] = 0.0

    return result.fillna(0)
