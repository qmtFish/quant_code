"""
市场/行业因子。

指数因子: hs300 / zz500 的 5、20 日收益率（从原始列 hs300_close / zz500_close 计算）。
行业因子: 按 industry 列等权合成行业日收益，再计算
          ind_ret_5d / ind_ret_20d   行业 5、20 日收益率
          ind_vol_20d                行业 20 日收益波动率
          ind_alpha_20d              行业 20 日收益 - hs300 20 日收益

注意: 行业归属取每只股票最后一条记录的分类（认为基本不变）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """df: 全市场原始长表, index=[date, code]; 返回同 index 的因子表。"""
    result = pd.DataFrame(index=df.index)
    dates = df.index.get_level_values('date')
    codes = df.index.get_level_values('code')

    # ---- 指数收益率（同一交易日所有股票相同）----
    for idx_name in ('hs300', 'zz500'):
        col = f'{idx_name}_close'
        if col not in df.columns:
            continue
        close_by_date = df[col].groupby(level='date').first()
        for period in (5, 20):
            result[f'{idx_name}_ret_{period}d'] = _map_by_date(
                close_by_date.pct_change(period), dates)

    # ---- 行业因子 ----
    stock_ret = df['close'].groupby(level='code').pct_change()  # 个股日收益

    industry = df['industry'].groupby(level='code').last()       # code -> industry
    ind_of_stock = industry.reindex(codes).to_numpy()

    tmp = pd.DataFrame({
        'date': dates,
        'industry': ind_of_stock,
        'ret': stock_ret.to_numpy(),
    })
    ind_daily = tmp.groupby(['date', 'industry'], as_index=False)['ret'].mean()
    ind_wide = ind_daily.pivot(index='date', columns='industry', values='ret')

    ind_ret5 = (1 + ind_wide).rolling(5).apply(np.prod, raw=True) - 1
    ind_ret20 = (1 + ind_wide).rolling(20).apply(np.prod, raw=True) - 1
    ind_vol20 = ind_wide.rolling(20).std()

    pairs = pd.MultiIndex.from_arrays([dates, ind_of_stock])
    result['ind_ret_5d'] = _map_by_pair(ind_ret5, pairs)
    result['ind_ret_20d'] = _map_by_pair(ind_ret20, pairs)
    result['ind_vol_20d'] = _map_by_pair(ind_vol20, pairs)

    if 'hs300_ret_20d' in result.columns:
        result['ind_alpha_20d'] = result['ind_ret_20d'] - result['hs300_ret_20d']

    return result.astype('float64')


def _map_by_date(s: pd.Series, dates: pd.Index) -> np.ndarray:
    """按日期把 Series 的值映射回每一行。"""
    return s.reindex(dates).to_numpy()


def _map_by_pair(s, pairs: pd.MultiIndex) -> np.ndarray:
    """按 (date, industry) 对把 Series 的值映射回每一行。"""
    if isinstance(s, pd.DataFrame):
        s = s.stack()
    return s.reindex(pairs).to_numpy()
