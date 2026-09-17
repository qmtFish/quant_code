"""
量价/技术因子（每个因子均为截至当日的“历史回看”值，不包含未来信息）。

计算:
    ret_5d / ret_20d / ret_60d   区间收益率
    volatility_20d               20 日波动率（日收益标准差）
    hl_range_5d                  5 日振幅 (HHV - LLV) / close
    vol_ma_ratio                 量比: 5 日均量 / 20 日均量
    ma_div_20d                   乖离率: close / MA20 - 1
    rsi_14d                      RSI(14, Wilder 平滑)
    macd_dif / macd_dea / macd_hist   MACD(12, 26, 9)
    kdj_k / kdj_d / kdj_j        KDJ(9, 3, 3)
    boll_bias                    BOLL 偏差: (close - MB20) / (2 * std20)
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """df: 全市场原始长表, index=[date, code]; 返回同 index 的因子表。"""
    # 先展开成 日期×股票 的宽表，用 pandas 向量化计算（比逐股循环快很多）
    close = df['close'].unstack('code')
    high = df['high'].unstack('code')
    low = df['low'].unstack('code')
    volume = df['volume'].unstack('code')

    result = pd.DataFrame(index=df.index)

    ret = close.pct_change()

    result['ret_5d'] = _to_long(close.pct_change(5), df)
    result['ret_20d'] = _to_long(close.pct_change(20), df)
    result['ret_60d'] = _to_long(close.pct_change(60), df)
    result['volatility_20d'] = _to_long(ret.rolling(20).std(), df)
    result['hl_range_5d'] = _to_long(
        (high.rolling(5).max() - low.rolling(5).min()) / close, df)

    vol_ma5 = volume.rolling(5).mean()
    vol_ma20 = volume.rolling(20).mean()
    result['vol_ma_ratio'] = _to_long(vol_ma5 / vol_ma20, df)

    ma20 = close.rolling(20).mean()
    result['ma_div_20d'] = _to_long(close / ma20 - 1, df)

    result['rsi_14d'] = _to_long(_rsi(close, 14), df)

    dif, dea, hist = _macd(close)
    result['macd_dif'] = _to_long(dif, df)
    result['macd_dea'] = _to_long(dea, df)
    result['macd_hist'] = _to_long(hist, df)

    k, d, j = _kdj(high, low, close)
    result['kdj_k'] = _to_long(k, df)
    result['kdj_d'] = _to_long(d, df)
    result['kdj_j'] = _to_long(j, df)

    std20 = close.rolling(20).std()
    result['boll_bias'] = _to_long((close - ma20) / (2 * std20), df)

    return result.astype('float64')


def _to_long(wide: pd.DataFrame, df: pd.DataFrame) -> pd.Series:
    """宽表(日期×股票)堆回长表，并严格按 df.index 对齐。"""
    return wide.stack().reindex(df.index)


def _rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """RSI：用 Wilder 平滑（ewm alpha=1/n）。"""
    ret = close.pct_change()
    gain = ret.clip(lower=0)
    loss = (-ret).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def _macd(close: pd.DataFrame, fast: int = 12, slow: int = 26,
          signal: int = 9):
    """MACD：返回 (DIF, DEA, 柱)。柱 = (DIF - DEA) * 2，与国内行情软件一致。"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def _kdj(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame,
         n: int = 9):
    """KDJ：RSV(9)，K/D 用 1/3 平滑，J = 3K - 2D。"""
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n) * 100
    rsv = rsv.fillna(50.0)  # 区间为 0 时给中性值
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j
