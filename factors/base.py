"""
factors/ 因子插件接口规范。

每个因子文件（一个 .py 文件）只需实现一个 compute(df) 函数，
引擎（engine.py）会自动发现并执行本目录下所有符合该格式的插件。

接口格式
--------
def compute(df: pd.DataFrame) -> pd.DataFrame:
    ...

入参 df:
    index  : MultiIndex [date, code]
             - date 已转为 datetime，升序
             - code 为字符串，升序
             - 整体按 (code, date) 排序
    columns: 原始 CSV 的全部列
             close, open, high, low, volume, money, turnover_ratio,
             pe_ratio, pb_ratio, market_cap, industry,
             hs300_close, zz500_close, ...

返回值:
    pd.DataFrame，index 必须与 df.index 完全一致（引擎会自动 reindex 对齐），
    每列为一个因子，列名即因子名，数值类型为 float。

注意事项
--------
- 不要修改传入的 df（引擎会在多个插件间复用它）。
- 因子值允许 NaN；引擎不做自动填充，可用 --zscore 做截面标准化。
- 建议每个文件只负责一组逻辑相关的因子。
- 文件命名随意（如 momentum.py），引擎按文件名顺序执行。
- base.py / engine.py / __init__.py 不会被当作因子加载。
"""
from __future__ import annotations

import pandas as pd


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """接口模板：新增因子文件时复制本函数并实现即可。"""
    raise NotImplementedError("每个因子插件必须实现 compute(df) -> pd.DataFrame")
