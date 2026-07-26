"""
因子引擎：自动发现 factors/ 下的插件，按日期截面调度计算。
"""
import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import List, Dict, Callable
import pandas as pd
import numpy as np

from pipeline.config import ZSCORE_CAP


def discover_factors() -> Dict[str, Callable]:
    """扫描 factors/ 目录，发现所有实现了 compute() 的插件。"""
    factors = {}
    plugin_dir = Path(__file__).resolve().parent.parent / 'factors'

    for importer, modname, ispkg in pkgutil.iter_modules([str(plugin_dir)]):
        if modname == 'base':
            continue
        module = importlib.import_module(f'pipeline.factors.{modname}')
        if hasattr(module, 'compute') and callable(module.compute):
            sig = inspect.signature(module.compute)
            params = list(sig.parameters.keys())
            if params == ['date', 'stocks', 'daily', 'financial', 'index', 'industry']:
                factors[modname] = module.compute
                print(f"  [发现因子] {modname}")
            else:
                print(f"  [跳过] {modname}: compute() 签名不匹配 -> {params}")
    return factors


def zscore_series(s: pd.Series, cap: float = ZSCORE_CAP) -> pd.Series:
    """截面 zscore，带极值截断。"""
    std = s.std()
    if std == 0 or s.isna().all():
        return pd.Series(0.0, index=s.index)
    z = (s - s.mean()) / std
    return z.clip(-cap, cap)


def build_factor_matrix(dates: List[pd.Timestamp],
                        stocks_list: List[List[str]],
                        daily: pd.DataFrame,
                        financial: pd.DataFrame,
                        index: Dict[str, pd.DataFrame],
                        industry: pd.DataFrame) -> pd.DataFrame:
    """
    遍历所有日期截面，运行所有因子插件，输出完整的因子矩阵。

    返回:
        DataFrame, columns=[code, date, industry, 因子1_z, 因子2_z, ...]
    """
    factor_fns = discover_factors()
    if not factor_fns:
        raise RuntimeError("未发现任何因子插件！请在 factors/ 下添加因子文件。")

    all_rows = []

    for idx, date in enumerate(dates):
        stocks = stocks_list[idx]

        # 运行每个因子插件
        factor_parts = []
        for name, fn in factor_fns.items():
            try:
                result = fn(date, stocks, daily, financial, index, industry)
                if result is not None and not result.empty:
                    factor_parts.append(result)
            except Exception as e:
                print(f"  [警告] {name} 在 {date.date()} 计算失败: {e}")

        if not factor_parts:
            continue

        # 合并所有因子
        combined = pd.concat(factor_parts, axis=1)
        # 去重
        combined = combined.loc[:, ~combined.columns.duplicated()]

        # zscore 标准化
        zscored = pd.DataFrame(index=combined.index)
        for col in combined.columns:
            zscored[col + '_z'] = zscore_series(combined[col].astype(float))

        # 写入行
        for code in stocks:
            if code not in zscored.index:
                continue
            row = {'code': code, 'date': date,
                   'industry': industry.loc[code, 'industry_code'] if code in industry.index else None}
            for col in zscored.columns:
                row[col] = zscored.loc[code, col]
            all_rows.append(row)

        if (idx + 1) % 10 == 0:
            print(f"  [{idx+1}/{len(dates)}] {date.date()} 完成, "
                  f"{len(stocks)} 只股票, {len(combined.columns)} 个因子")

    result_df = pd.DataFrame(all_rows)
    return result_df
