"""
量价因子插件。
参考 factor_builder.py 中的 price factors 部分。
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
    计算量价因子。

    返回列:
        ret_5d, ret_20d, ret_60d,
        volatility_20d, hl_range_5d, vol_ma_ratio,
        fair_price_deviation, size_log
    """
    # 取 date 之前 120 个交易日的数据
    hist = daily.loc[:date].tail(120).copy()
    if hist.empty:
        return pd.DataFrame(index=stocks)

    # 只取需要的股票
    hist = hist[hist.index.get_level_values('code').isin(stocks)]

    close = hist['close'].unstack('code')
    high = hist['high'].unstack('code')
    low = hist['low'].unstack('code')
    volume = hist['volume'].unstack('code')

    if close.empty:
        return pd.DataFrame(index=stocks)

    ret = close.pct_change().fillna(0)
    n = min(len(close), 120)
    last_close = close.iloc[-1]

    result = pd.DataFrame(index=stocks)

    # 收益率因子
    for period, label in [(5, 'ret_5d'), (20, 'ret_20d'), (60, 'ret_60d')]:
        if n >= period:
            result[label] = (close.iloc[-1] / close.iloc[-period] - 1).reindex(stocks)
        else:
            result[label] = 0.0

    # 20日波动率
    if n >= 20:
        result['volatility_20d'] = ret.iloc[-20:].std().reindex(stocks)
    else:
        result['volatility_20d'] = 0.0

    # 5日振幅
    if n >= 5:
        result['hl_range_5d'] = (
            (high.iloc[-5:].max() - low.iloc[-5:].min()) / (last_close + 1e-6)
        ).reindex(stocks)
    else:
        result['hl_range_5d'] = 0.0

    # 量比 (5日均量 / 20日均量)
    if n >= 20:
        result['vol_ma_ratio'] = (
            volume.iloc[-5:].mean() / (volume.iloc[-20:].mean() + 1e-6)
        ).reindex(stocks)
    else:
        result['vol_ma_ratio'] = 0.0

    # 公允价值偏离（价格 vs 60日中位数）
    lookback = min(n, 60)
    if lookback >= 10:
        median_price = close.iloc[-lookback:].median()
        price_std = close.iloc[-lookback:].std()
        result['fair_price_deviation'] = (
            (median_price - last_close) / (price_std + 1e-6)
        ).reindex(stocks)
    else:
        result['fair_price_deviation'] = 0.0

    # 流通市值对数（从财务数据取，若无则用总市值）
    # market_cap 在 fund_factors 中计算，这里不重复

    result = result.fillna(0)
    return result
