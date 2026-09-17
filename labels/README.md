# labels/ 预测标签生成

入口脚本：`make_labels.py`，运行 `python labels/make_labels.py`。

## 默认生成的标签

| 标签列 | 含义 |
| --- | --- |
| `fwd_ret_1d / 3d / 5d / 10d` | 未来 1/3/5/10 个交易日收益率（收盘价对收盘价） |
| `next_ret` | 未来 5 日收益率（与现有 `local_train_data` 的 `next_ret` 约定一致） |
| `up_Nd` | 涨跌二分类：未来 N 日收益 > 0 为 1，否则 0 |
| `rank_Nd` | 未来 N 日收益的当日截面分位（0~1，用于排序学习/分层回测） |
| `fwd_excess_mkt_Nd` | 未来 N 日收益 - 当日全市场等权平均收益（相对强弱） |
| `fwd_excess_hs300_Nd` | 未来 N 日收益 - 沪深300 同期收益 |
| `fwd_excess_zz500_Nd` | 未来 N 日收益 - 中证500 同期收益 |

所有标签都只用“未来”数据，不包含当日收盘信息之外的未来信息泄漏；数据末尾
每个股票的最后 N 行为 NaN（未来收益尚未发生），属正常现象。

## 常用命令

```bash
python labels/make_labels.py                                   # 默认 1/3/5/10 日
python labels/make_labels.py --horizons 1,3,5,10,20            # 自定义窗口
python labels/make_labels.py --benchmarks hs300                # 只用 hs300 做超额基准
python labels/make_labels.py --merge data/all_processed_data/factor_data_xxx.csv
python labels/make_labels.py --placeholder                     # 无标签行填 -1，兼容旧数据
python labels/make_labels.py --format parquet                  # 输出 parquet
```

`--merge` 会把标签按 `date + code` 合并进因子矩阵文件（csv/parquet 均可），
输出为 `xxx_labeled.csv`，可直接用于训练。

## 其他常用标签（可按需扩展）

- **行业中性超额收益**：未来 N 日收益 - 所属行业中位数/均值收益，消除行业轮动影响
- **风险调整后收益**：未来 N 日收益 / 未来 N 日波动率（近似 Sharpe，用于风险调整排序）
- **未来波动率**：未来 N 日日收益标准差（波动率预测任务的 label）
- **多分类标签**：按截面把未来收益切成 5/10 分位桶（分类任务、分层回测）
- **事件类标签**：是否涨停/跌停、是否停牌、是否创新高/新低
- **路径类标签**：未来 N 日最大回撤、最大反弹、连续上涨/下跌天数
- **量能类标签**：未来 N 日换手率/成交额变化（量价协同预测）
