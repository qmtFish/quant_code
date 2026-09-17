# factors/ 因子插件目录

因子处理引擎：`engine.py`，运行方式 `python factors/engine.py`。

## 新增因子的步骤

1. 在 `factors/` 下新建一个 `.py` 文件，例如 `momentum.py`
2. 实现且**只**实现一个 `compute(df)` 函数（签名必须是 `compute(df)`）
3. 运行 `python factors/engine.py`，引擎会自动发现、执行并合并

## compute(df) 接口

| 项目 | 说明 |
| --- | --- |
| 入参 df | 全市场原始长表，index 为 MultiIndex `[date, code]`，列 = 原始 CSV 全部列 |
| 返回值 | `pd.DataFrame`，index 与 df 完全一致，每列一个因子，列名即因子名 |
| 约束 | 不得修改入参 df；允许 NaN；建议每个文件只负责一组逻辑相关的因子 |

## 模板

```python
import pandas as pd


def compute(df: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=df.index)
    # 例：5 日收益率（按股票分组计算，不包含未来信息）
    close = df['close'].unstack('code')
    result['ret_5d'] = close.pct_change(5).stack().reindex(df.index)
    return result.astype('float64')
```

## 规则与提示

- `base.py` / `engine.py` / `__init__.py` 不会被当作因子加载，请勿改动
- 文件名以 `_` 开头的文件也会被忽略
- 长回看窗口（如 60 日）在数据起始处会产生 NaN，属正常现象；
  用 `--start` 过滤日期时建议多留 60 天预热数据
- 高效写法：先把列 `unstack('code')` 成“日期×股票”宽表，
  用 pandas 的 rolling / ewm 向量化计算，再 `stack().reindex(df.index)` 回到长表
