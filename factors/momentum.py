"""
示例因子：10 日动量（新增因子的最小模板）。

只需实现 compute(df) 并返回“index 与 df 一致、每列一个因子”的 DataFrame，
引擎就会自动发现并合并该文件。
"""
from __future__ import annotations

import pandas as pd


def compute(df: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=df.index)
    close = df['close'].unstack('code')
    result['ret_10d'] = close.pct_change(10).stack().reindex(df.index)
    return result.astype('float64')
