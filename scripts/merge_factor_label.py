# -*- coding: utf-8 -*-
"""
合并 factor_data（因子+行业）与 label_data（next_ret 标签），
按 (date, code) 补全 next_ret，生成完整训练集。

- 不改动原始两个文件
- 标签只取 next_ret（fwd_*/up_*/rank_* 未来信息列一律不带入，避免泄露）
- next_ret 缺失值(NaN，新股无未来收益) 填 -1（与 model.py 的"无标签占位"约定一致，训练时自动过滤）
- 两文件键集合已实测完全一致（3744669 行一一对应），merge 无丢失
- 分块读取 factor_data（float32 + chunksize），避免 3.6GB CSV 全量加载 OOM

用法:
    python scripts/merge_factor_label.py [--output data/all_processed_data/train_data_2023-07-17_2026-07-24.csv]
"""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

P_FACTOR = r'data/all_processed_data/factor_data_2023-07-17_2026-07-24.csv'
P_LABEL = r'data/all_processed_data/label_data_2023-07-17_2026-07-24.csv'
DEFAULT_OUT = r'data/all_processed_data/train_data_2023-07-17_2026-07-24.csv'
CHUNK = 500_000


def _dtype_map(path) -> dict:
    """数值列用 float32 省内存（全量 float64 会 OOM）。"""
    header = pd.read_csv(path, nrows=0)
    dtypes = {}
    for col in header.columns:
        if col in ('code', 'date'):
            dtypes[col] = 'str'
        elif col == 'industry':
            dtypes[col] = 'int32'
        else:
            dtypes[col] = 'float32'
    return dtypes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=str, default=DEFAULT_OUT)
    args = parser.parse_args()

    print(f'[1/4] 读取 label_data (仅取 date/code/next_ret) ...')
    lab = pd.read_csv(P_LABEL, usecols=['date', 'code', 'next_ret'],
                      dtype={'next_ret': 'float32'})
    n_nan = int(lab['next_ret'].isna().sum())
    lab['next_ret'] = lab['next_ret'].fillna(-1)
    lab = lab.set_index(['date', 'code'])
    print(f'      {lab.shape[0]} 行, next_ret NaN {n_nan} 行 -> 填 -1 占位（训练时自动过滤）')

    print(f'[2/4] 分块读取 factor_data 并按 (date, code) 合并 ...')
    n_rows, n_miss, n_chunk = 0, 0, 0
    first = True
    for chunk in pd.read_csv(P_FACTOR, dtype=_dtype_map(P_FACTOR),
                             low_memory=False, chunksize=CHUNK):
        merged = chunk.set_index(['date', 'code']).join(lab, how='left')
        miss = int(merged['next_ret'].isna().sum())
        assert miss == 0, f'块内仍有 {miss} 行缺 next_ret'
        n_miss += miss
        merged = merged.reset_index()
        cols = ['date', 'code', 'industry', 'next_ret'] + \
               [c for c in merged.columns if c not in ('date', 'code', 'industry', 'next_ret')]
        merged[cols].to_csv(args.output, index=False,
                            mode='w' if first else 'a', header=first)
        first = False
        n_rows += len(merged)
        n_chunk += 1
        print(f'      [块 {n_chunk}] {len(merged):,} 行 -> 累计 {n_rows:,}')

    print(f'[3/4] 校验 ...')
    tail = pd.read_csv(args.output, nrows=5)
    print(f'      输出列: {tail.columns[:8].tolist()} ... 共 {tail.shape[1]} 列')

    print(f'[4/4] 完成: {args.output}')
    size_mb = Path(args.output).stat().st_size / 1024 / 1024
    print(f'      {n_rows:,} 行, {size_mb:.0f} MB, next_ret 缺失 {n_miss} 行')


if __name__ == '__main__':
    main()
