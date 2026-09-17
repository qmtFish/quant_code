"""
趋势/通道因子 —— 用几何特征描述一只股票的 K 线趋势（下跌通道/上涨通道）。

人眼看到的"下跌通道" = 价格沿一条斜向下的直线运行、反弹无力、高点不断降低。
这里把它拆成可计算的因子（均为截至当日的历史回看值，不含未来信息）：

    trend_slope_20d / trend_slope_60d   趋势斜率（%/日）：收盘价对时间线性回归的斜率，
                                        负值 = 下行，绝对值 = 下跌速度
    trend_r2_20d / trend_r2_60d         趋势强度：回归拟合优度 R²（0~1），
                                        越接近 1 通道越"直"、越规整
    channel_pos_20d                     通道位置（0~1）：(close - 下轨) / (上轨 - 下轨)，
                                        0 = 贴下轨，1 = 贴上轨；下跌通道中应长期偏小
    bounce_5d                           反弹力度（0~1）：近 5 日最高点相对 20 日最低点的
                                        反弹幅度 ÷ 20 日总波幅，小 = 弱反弹（下跌中继）
    lower_high_5d                       高点结构（0/1）：近 5 日最高价 < 前 5 日最高价
                                        记为 1（高点更低，下跌通道的标志）
    ma_align_20d                        均线排列：(ma20 - ma60) / ma60，负 = 空头排列
    drawdown_60d                        回撤深度：close / 60 日最高价 - 1（<=0）

计算均用"日期×股票"宽表 + pandas rolling 向量化，与 price_factors.py 风格一致。
线性回归用滚动协方差：slope = cov(close, t) / var(t)，R² = corr(close, t)²，
残差标准差由 Var(y)·(1-R²) 直接推出，无需逐股循环。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 连续 n 个整数序号的样本方差（ddof=1）：n(n+1)/12，用于把滚动协方差换算成斜率
def _t_var(n: int) -> float:
    return n * (n + 1) / 12.0


def _linreg(close: pd.DataFrame, n: int):
    """对每只股票做滚动线性回归 close ~ t（t 为 K 线序号）。

    返回 (slope, r2, fit, resid_std)：
        slope      斜率（价格/根K线）
        r2         拟合优度 0~1
        fit        窗口末端回归拟合值（即通道中轨当前值）
        resid_std  残差标准差（通道半宽）
    """
    t = pd.Series(np.arange(len(close)), index=close.index)
    cov = close.rolling(n).cov(t)
    slope = cov / _t_var(n)
    r2 = close.rolling(n).corr(t) ** 2
    mean_close = close.rolling(n).mean()
    fit = mean_close + slope * (n - 1) / 2.0          # 窗口末端拟合价
    resid_std = close.rolling(n).std() * np.sqrt((1 - r2).clip(lower=0))
    return slope, r2, fit, resid_std


def _to_long(wide: pd.DataFrame, df: pd.DataFrame) -> pd.Series:
    """宽表(日期×股票)堆回长表，并严格按 df.index 对齐。"""
    return wide.stack().reindex(df.index)


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """df: 全市场原始长表, index=[date, code]; 返回同 index 的因子表。"""
    close = df['close'].unstack('code')
    high = df['high'].unstack('code')

    result = pd.DataFrame(index=df.index)

    # ---- 趋势斜率 + 强度 ----
    for n in (20, 60):
        slope, r2, _, _ = _linreg(close, n)
        # 斜率归一化为 %/日（除以当日收盘价），便于跨股票比较
        result[f'trend_slope_{n}d'] = _to_long(slope / close * 100.0, df)
        result[f'trend_r2_{n}d'] = _to_long(r2, df)

    # ---- 通道位置：相对 ±1 倍残差标准差通道 ----
    _, _, fit20, resid20 = _linreg(close, 20)
    upper = fit20 + resid20
    lower = fit20 - resid20
    result['channel_pos_20d'] = _to_long(
        ((close - lower) / (upper - lower)).clip(0, 1), df)

    # ---- 反弹力度：近5日最高 相对 20日最低的反弹 ÷ 20日总波幅 ----
    hhv20 = close.rolling(20).max()
    llv20 = close.rolling(20).min()
    hhv5 = high.rolling(5).max()
    result['bounce_5d'] = _to_long(
        ((hhv5 - llv20) / (hhv20 - llv20)).clip(0, 1), df)

    # ---- 高点结构：近5日最高 < 前5日最高 → 1（高点更低） ----
    hh5 = high.rolling(5).max()
    prev_hh5 = hh5.shift(5)
    lower_high = (hh5 < prev_hh5).where(hh5.notna() & prev_hh5.notna(), np.nan)
    result['lower_high_5d'] = _to_long(lower_high.astype(float), df)

    # ---- 均线排列：空头排列为负 ----
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    result['ma_align_20d'] = _to_long((ma20 - ma60) / ma60, df)

    # ---- 回撤深度：<=0，越负回撤越深 ----
    result['drawdown_60d'] = _to_long(close / close.rolling(60).max() - 1.0, df)

    return result.astype('float64')
