"""
基本面因子插件。
参考 factor_builder.py 中的 fundamental 部分。
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
    计算估值 + 盈利能力 + 成长类基本面因子。

    返回列:
        pe_ratio, pb_ratio, ps_ratio, pcf_ratio,
        market_cap, roe, roa,
        gross_profit_margin, net_profit_margin,
        inc_revenue_yoy, inc_net_profit_yoy
    """
    # 取最新的财务数据（小于等于 date 的最新报告期）
    fin = financial.reset_index()
    fin = fin[fin['report_date'] <= pd.Timestamp(date)]
    fin = fin.loc[fin.groupby('code')['report_date'].idxmax()]  # 每只股票取最新一期
    fin = fin[fin['code'].isin(stocks)].set_index('code')

    if fin.empty:
        return pd.DataFrame(index=stocks)

    # 选择需要的列
    fund_cols = ['pe_ratio', 'pb_ratio', 'ps_ratio', 'pcf_ratio',
                 'market_cap', 'roe', 'roa',
                 'gross_profit_margin', 'net_profit_margin',
                 'inc_revenue_yoy', 'inc_net_profit_yoy']

    available = [c for c in fund_cols if c in fin.columns]
    result = fin[available].copy()

    # 填充缺失值
    result = result.fillna(0)

    return result
