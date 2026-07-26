"""
因子函数接口定义。
每个因子插件只需实现 compute() 函数，签名如下。
"""
from typing import List, Dict, Optional
import pandas as pd


def compute(date: pd.Timestamp,
            stocks: List[str],
            daily: pd.DataFrame,
            financial: pd.DataFrame,
            index: Dict[str, pd.DataFrame],
            industry: pd.DataFrame) -> pd.DataFrame:
    """
    计算一组因子。

    参数:
        date     : 当前截面日期
        stocks   : 需要计算的股票代码列表
        daily    : 全市场日线行情
                   multi-index=[date, code], columns=[open,high,low,close,volume,amount]
        financial: 财务指标
                   multi-index=[code, report_date], columns=[pe_ratio,pb_ratio,...]
        index    : 指数行情, {'hs300': df, 'zz500': df}, df.index=date, df.close
        industry : 行业分类, index=code, column=industry_code

    返回:
        pd.DataFrame, index=stocks, columns=因子名(原始值,非zscore)
    """
    raise NotImplementedError("每个因子插件必须实现 compute()")
