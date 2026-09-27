"""
预测标签生成脚本 —— 从原始 CSV 计算监督学习所需的标签。

默认生成（horizons 可配置）:
    fwd_ret_Nd              未来 N 个交易日收益率（N=1/3/5/10）
    next_ret                未来 5 日收益率（兼容现有训练管线的标签列）
    up_Nd                   涨跌二分类: 未来 N 日收益 > 0 ? 1 : 0
    rank_Nd                 未来 N 日收益的当日截面分位（0~1，用于排序学习）
    fwd_excess_mkt_Nd       未来 N 日收益 - 当日全市场等权平均收益（相对强弱）
    fwd_excess_hs300_Nd     未来 N 日收益 - hs300 同期收益（相对基准超额）
    fwd_excess_zz500_Nd     未来 N 日收益 - zz500 同期收益

用法
----
    python labels/make_labels.py                                  # 默认输入/输出
    python labels/make_labels.py --horizons 1,3,5,10,20
    python labels/make_labels.py --benchmarks hs300               # 只用 hs300 做基准
    python labels/make_labels.py --merge data/all_processed_data/factor_data_xxx.csv
    python labels/make_labels.py --placeholder                    # 无标签行填 -1（兼容旧数据）
    python labels/make_labels.py --format parquet

默认输入: data/all_raw_data/raw_stock_data_2023-07-17_2026-07-24.csv
默认输出: data/all_processed_data/label_data_2023-07-17_2026-07-24.csv
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT_DIR / 'data' / 'all_raw_data' / 'raw_stock_data_2023-07-17_2026-07-24.csv'
DEFAULT_OUTPUT_DIR = ROOT_DIR / 'data' / 'all_processed_data'
NEXT_RET_HORIZON = 5  # 与现有 local_train_data 中 next_ret 的约定一致


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_raw(path: Path) -> pd.DataFrame:
    """只读取计算标签所需的列，整理成 (date, code) 双索引、按 (code, date) 排序的长表。"""
    print(f'[加载] {path}')
    t0 = time.time()
    header = pd.read_csv(path, nrows=0)
    use_cols = [c for c in ('date', 'code', 'close', 'hs300_close', 'zz500_close')
                if c in header.columns]
    dtypes: Dict[str, str] = {'date': 'str', 'code': 'str'}
    for col in use_cols:
        if col not in dtypes:
            dtypes[col] = 'float32'
    df = pd.read_csv(path, usecols=use_cols, dtype=dtypes, low_memory=False)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['code', 'date']).reset_index(drop=True)
    df = df.set_index(['date', 'code'])
    if df.index.duplicated().any():
        dup = int(df.index.duplicated().sum())
        print(f'[警告] 存在 {dup} 行重复 (date, code)，保留第一条')
        df = df[~df.index.duplicated(keep='first')]
    print(f'[加载] {len(df)} 行，{df.index.get_level_values("date").nunique()} 个交易日，'
          f'{df.index.get_level_values("code").nunique()} 只股票，耗时 {time.time() - t0:.0f}s')
    return df


# ---------------------------------------------------------------------------
# 标签计算
# ---------------------------------------------------------------------------
def compute_labels(df: pd.DataFrame, horizons: Sequence[int] = (1, 3, 5, 10),
                   benchmarks: Sequence[str] = ('hs300', 'zz500')) -> pd.DataFrame:
    """计算全部标签，返回 index 与 df 一致的标签表。"""
    result = pd.DataFrame(index=df.index)
    close = df['close']

    print("close head", close.head())

    for n in horizons:
        # 未来 N 日收益率：按股票分组把 close 前移 N 行
        fwd_close = close.groupby(level='code').shift(-n)
        r = fwd_close / close - 1

        result[f'fwd_ret_{n}d'] = r
        result[f'up_{n}d'] = (r > 0).astype('float64').mask(r.isna())
        result[f'rank_{n}d'] = r.groupby(level='date').rank(pct=True)

        # 相对全市场等权平均的超额（当日截面）
        mkt_mean = r.groupby(level='date').transform('mean')
        result[f'fwd_excess_mkt_{n}d'] = r - mkt_mean

        # 相对指数基准的超额
        for bench in benchmarks:
            bench_col = f'{bench}_close'
            if bench_col not in df.columns:
                continue
            bench_close = df[bench_col].groupby(level='date').first()
            bench_fwd = bench_close.shift(-n) / bench_close - 1
            bench_map = bench_fwd.reindex(df.index.get_level_values('date')).to_numpy()
            result[f'fwd_excess_{bench}_{n}d'] = r.to_numpy() - bench_map

    # 兼容旧训练数据的标签列（未来 5 日收益）
    if NEXT_RET_HORIZON in horizons:
        result['next_ret'] = result[f'fwd_ret_{NEXT_RET_HORIZON}d']

    return result.astype('float64')


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def _default_output(input_path: Path, start: Optional[str], end: Optional[str],
                    fmt: str) -> Path:
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', input_path.stem)
    if start or end:
        s = (start or (dates[0] if dates else 'start')).replace('-', '')
        e = (end or (dates[1] if len(dates) > 1 else 'end')).replace('-', '')
        name = f'label_data_{s}_{e}.{fmt}'
    elif dates:
        name = f'label_data_{"_".join(dates)}.{fmt}'
    else:
        name = f'label_data.{fmt}'
    return DEFAULT_OUTPUT_DIR / name


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='预测标签生成：未来 N 日收益、超额收益、涨跌分类、截面分位等。')
    parser.add_argument('--input', default=str(DEFAULT_INPUT), help='原始数据 CSV 路径')
    parser.add_argument('--output', default=None, help='输出文件路径')
    parser.add_argument('--horizons', default='1,3,5,10', help='未来交易日数，逗号分隔')
    parser.add_argument('--benchmarks', default='hs300,zz500',
                        help='超额收益的基准指数，逗号分隔（如 hs300,zz500 或空）')
    parser.add_argument('--start', default=None, help='起始日期 YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='结束日期 YYYY-MM-DD')
    parser.add_argument('--merge', default=None,
                        help='因子矩阵文件（csv/parquet），将标签按 date+code 合并进去后保存')
    parser.add_argument('--placeholder', action='store_true',
                        help='无标签行填 -1（兼容旧数据 next_ret == -1 的约定）')
    parser.add_argument('--format', choices=['csv', 'parquet'], default='csv')
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f'输入文件不存在: {input_path}')
        return 1

    horizons = tuple(int(x) for x in args.horizons.split(',') if x.strip())
    benchmarks = tuple(x.strip() for x in args.benchmarks.split(',') if x.strip())
    if not horizons:
        print('--horizons 不能为空')
        return 1

    t_start = time.time()
    df = load_raw(input_path)

    if args.start or args.end:
        date_level = df.index.get_level_values('date')
        mask = pd.Series(True, index=df.index)
        if args.start:
            mask &= date_level >= pd.Timestamp(args.start)
        if args.end:
            mask &= date_level <= pd.Timestamp(args.end)
        df = df[mask]
        print(f'[过滤] 日期范围 -> {len(df)} 行，'
              f'{df.index.get_level_values("date").nunique()} 个交易日')

    print(f'[计算] horizons={horizons}, benchmarks={benchmarks}')
    labels = compute_labels(df, horizons=horizons, benchmarks=benchmarks)

    if args.placeholder:
        labels = labels.fillna(-1.0)

    if args.merge:
        merge_path = Path(args.merge)
        if merge_path.suffix.lower() == '.parquet':
            factor_df = pd.read_parquet(merge_path)
        else:
            factor_df = pd.read_csv(merge_path)
        factor_df['date'] = pd.to_datetime(factor_df['date'])
        labels_df = labels.reset_index()
        merged = factor_df.merge(labels_df, on=['date', 'code'], how='left')
        output = Path(args.output) if args.output else merge_path.with_name(
            f'{merge_path.stem}_labeled{merge_path.suffix}')
        print(f'[合并] 因子矩阵 {factor_df.shape} + 标签 -> {merged.shape}')
    else:
        merged = pd.concat([
            pd.DataFrame({'date': df.index.get_level_values('date'),
                          'code': df.index.get_level_values('code')}),
            labels.reset_index(drop=True),
        ], axis=1)
        output = Path(args.output) if args.output else _default_output(
            input_path, args.start, args.end, args.format)

    output.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if output.suffix.lower() == '.parquet' or args.format == 'parquet':
        merged.to_parquet(output.with_suffix('.parquet'), index=False)
        output = output.with_suffix('.parquet')
    else:
        merged.to_csv(output, index=False)
    size_mb = output.stat().st_size / 1024 / 1024
    print(f'[保存] {output}（{size_mb:.0f} MB，{merged.shape[0]} 行 × {merged.shape[1]} 列，'
          f'耗时 {time.time() - t0:.0f}s）')
    print(f'[完成] 总耗时 {time.time() - t_start:.0f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
