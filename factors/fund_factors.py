"""
基本面因子（原始财务列透传 + 衍生因子）。

透传: pe_ratio, pb_ratio, ps_ratio, pcf_ratio, market_cap,
      circulating_market_cap, roe, roa, gross_profit_margin,
      net_profit_margin, inc_revenue_year_on_year, inc_net_profit_year_on_year
衍生: size_log         对数市值
      earnings_yield   盈利收益率 1/PE（仅 PE>0）
      book_to_price    市净率的倒数 1/PB（仅 PB>0）
      revenue_yield    市销率的倒数 1/PS（仅 PS>0）
      cashflow_yield   市现率的倒数 1/PCF（仅 PCF>0）
      peg              PE / 净利润同比增速（PE>0 且增速>0）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

PASSTHROUGH = [
    'pe_ratio', 'pb_ratio', 'ps_ratio', 'pcf_ratio',
    'market_cap', 'circulating_market_cap', 'roe', 'roa',
    'gross_profit_margin', 'net_profit_margin',
    'inc_revenue_year_on_year', 'inc_net_profit_year_on_year',
]


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """df: 全市场原始长表, index=[date, code]; 返回同 index 的因子表。"""
    result = pd.DataFrame(index=df.index)

    for col in PASSTHROUGH:
        if col in df.columns:
            result[col] = df[col]

    result['size_log'] = np.log(df['market_cap'])
    result['earnings_yield'] = 1.0 / df['pe_ratio'].where(df['pe_ratio'] > 0)
    result['book_to_price'] = 1.0 / df['pb_ratio'].where(df['pb_ratio'] > 0)
    result['revenue_yield'] = 1.0 / df['ps_ratio'].where(df['ps_ratio'] > 0)
    result['cashflow_yield'] = 1.0 / df['pcf_ratio'].where(df['pcf_ratio'] > 0)

    pe = df['pe_ratio']
    growth = df['inc_net_profit_year_on_year']
    result['peg'] = (pe / growth).where((pe > 0) & (growth > 0))

    return result.astype('float64')
