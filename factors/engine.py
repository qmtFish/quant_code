"""
因子处理引擎 —— 一键从原始 CSV 计算全部因子。

用法
----
    python factors/engine.py                                     # 默认输入/输出
    python factors/engine.py --list                              # 只列出已发现因子
    python factors/engine.py --input 文件.csv --output 输出.csv
    python factors/engine.py --start 2025-01-01 --end 2026-07-24
    python factors/engine.py --only price_factors,fund_factors
    python factors/engine.py --zscore                            # 因子列按日期截面 zscore
    python factors/engine.py --drop-raw                          # 输出不含原始列
    python factors/engine.py --format parquet                    # 输出 parquet

默认输入: data/all_raw_data/raw_stock_data_2023-07-17_2026-07-24.csv
默认输出: data/all_processed_data/factor_data_2023-07-17_2026-07-24.csv

新增因子
--------
在 factors/ 目录下新建一个 .py 文件，实现 compute(df) -> pd.DataFrame 即可，
引擎会自动发现、执行并合并（接口规范见 base.py）。
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import re
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

FACTOR_DIR = Path(__file__).resolve().parent
ROOT_DIR = FACTOR_DIR.parent
DEFAULT_INPUT = ROOT_DIR / 'data' / 'all_raw_data' / 'raw_stock_data_2023-07-17_2026-07-24.csv'
DEFAULT_OUTPUT_DIR = ROOT_DIR / 'data' / 'all_processed_data'
ZSCORE_CAP = 5.0

_SKIP_MODULES = {'__init__', 'base', 'engine'}


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def _dtype_map(path: Path) -> Dict[str, str]:
    """根据表头生成 dtype 映射：数值列用 float32 省内存。"""
    header = pd.read_csv(path, nrows=0)
    dtypes: Dict[str, str] = {}
    for col in header.columns:
        if col in ('code', 'date'):
            dtypes[col] = 'str'
        elif col == 'industry':
            dtypes[col] = 'int32'
        else:
            dtypes[col] = 'float32'
    return dtypes


def load_raw(path: Path) -> pd.DataFrame:
    """读取原始 CSV，整理成 (date, code) 双索引、按 (code, date) 排序的长表。"""
    print(f'[加载] {path}')
    t0 = time.time()
    df = pd.read_csv(path, dtype=_dtype_map(path), low_memory=False)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['code', 'date']).reset_index(drop=True)
    df = df.set_index(['date', 'code'])
    if df.index.duplicated().any():
        dup = int(df.index.duplicated().sum())
        print(f'[警告] 存在 {dup} 行重复 (date, code)，保留第一条')
        df = df[~df.index.duplicated(keep='first')]
    n_dates = df.index.get_level_values('date').nunique()
    n_codes = df.index.get_level_values('code').nunique()
    print(f'[加载] {len(df)} 行，{n_dates} 个交易日，{n_codes} 只股票，'
          f'耗时 {time.time() - t0:.0f}s')
    return df


# ---------------------------------------------------------------------------
# 插件发现与执行
# ---------------------------------------------------------------------------
def discover_factors() -> Dict[str, Callable]:
    """扫描 factors/ 下所有符合 compute(df) 格式的插件文件。"""
    factors: Dict[str, Callable] = {}
    for path in sorted(FACTOR_DIR.glob('*.py')):
        name = path.stem
        if name in _SKIP_MODULES or name.startswith('_'):
            continue
        spec = importlib.util.spec_from_file_location(f'_factor_plugin_{name}', path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            print(f'[跳过] {name}: 导入失败 -> {exc}')
            continue
        fn = getattr(module, 'compute', None)
        if not callable(fn):
            print(f'[跳过] {name}: 未定义 compute()')
            continue
        params = list(inspect.signature(fn).parameters)
        if params != ['df']:
            print(f'[跳过] {name}: compute() 签名必须为 compute(df)，实际 {params}')
            continue
        doc = (getattr(module, '__doc__') or '').strip().splitlines()
        desc = doc[0] if doc else ''
        factors[name] = fn
        print(f'[发现因子] {name}{" - " + desc if desc else ""}')
    return factors


def run_factors(df: pd.DataFrame, factors: Dict[str, Callable]) -> pd.DataFrame:
    """依次执行每个因子插件，返回合并后的因子表（index 与 df 一致）。"""
    parts: List[pd.DataFrame] = []
    for name, fn in factors.items():
        t0 = time.time()
        try:
            result = fn(df)
        except Exception as exc:
            print(f'[失败] {name}: {type(exc).__name__}: {exc}')
            continue
        if result is None:
            print(f'[失败] {name}: compute() 返回 None')
            continue
        if len(result) != len(df):
            print(f'[失败] {name}: 返回 {len(result)} 行，输入 {len(df)} 行，已跳过')
            continue
        if result.columns.empty:
            print(f'[警告] {name}: 未返回任何因子列')
            continue
        result = result.reindex(df.index)
        result = result.apply(pd.to_numeric, errors='coerce')
        parts.append(result)
        print(f'[完成] {name}: {len(result.columns)} 个因子 {list(result.columns)}，'
              f'耗时 {time.time() - t0:.1f}s')

    if not parts:
        raise RuntimeError('没有任何因子插件成功执行，请检查 factors/ 下的插件')

    merged = pd.concat(parts, axis=1)
    merged = merged.loc[:, ~merged.columns.duplicated(keep='first')]
    print(f'[合并] 因子列数: {len(merged.columns)}')
    return merged


# ---------------------------------------------------------------------------
# 输出组装
# ---------------------------------------------------------------------------
def assemble(df: pd.DataFrame, factor_df: pd.DataFrame, keep_raw: bool = True) -> pd.DataFrame:
    """组装最终输出：date, code, [原始列,] 因子列；重名时因子列优先。"""
    parts: List[pd.DataFrame] = []
    if keep_raw:
        parts.append(df.reset_index(drop=True))
    parts.append(factor_df.reset_index(drop=True))
    body = pd.concat(parts, axis=1)
    body = body.loc[:, ~body.columns.duplicated(keep='last')]
    out = pd.DataFrame({
        'date': df.index.get_level_values('date'),
        'code': df.index.get_level_values('code'),
    })
    return pd.concat([out, body], axis=1)


def zscore_cross_section(df: pd.DataFrame, cols: List[str], cap: float = ZSCORE_CAP) -> None:
    """按 date 截面 zscore 并截断到 ±cap（就地修改因子列）。"""
    if not cols:
        return
    g = df.groupby('date')[cols]
    mean = g.transform('mean')
    std = g.transform('std', ddof=0)
    z = (df[cols] - mean) / (std + 1e-12)
    z = z.mask(std == 0, 0.0)
    df[cols] = z.clip(-cap, cap)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def _default_output(input_path: Path, start: Optional[str], end: Optional[str],
                    fmt: str) -> Path:
    dates = re.findall(r'\d{4}-\d{2}-\d{2}', input_path.stem)
    if start or end:
        s = (start or (dates[0] if dates else 'start')).replace('-', '')
        e = (end or (dates[1] if len(dates) > 1 else 'end')).replace('-', '')
        name = f'factor_data_{s}_{e}.{fmt}'
    elif dates:
        name = f'factor_data_{"_".join(dates)}.{fmt}'
    else:
        name = f'factor_data.{fmt}'
    return DEFAULT_OUTPUT_DIR / name


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description='因子处理引擎：读取原始 CSV，自动执行 factors/ 下所有因子插件并保存结果。')
    parser.add_argument('--input', default=str(DEFAULT_INPUT), help='原始数据 CSV 路径')
    parser.add_argument('--output', default=None, help='输出文件路径（默认 data/all_processed_data/）')
    parser.add_argument('--start', default=None, help='起始日期 YYYY-MM-DD')
    parser.add_argument('--end', default=None, help='结束日期 YYYY-MM-DD')
    parser.add_argument('--only', default=None,
                        help='只运行指定插件，逗号分隔（如 price_factors,fund_factors）')
    parser.add_argument('--list', action='store_true', help='只列出已发现的因子插件')
    parser.add_argument('--zscore', action='store_true',
                        help='对因子列按日期截面做 zscore（截断 ±5）')
    parser.add_argument('--drop-raw', action='store_true',
                        help='输出不含原始列（只保留 date, code, 因子列）')
    parser.add_argument('--format', choices=['csv', 'parquet'], default='csv',
                        help='输出格式（默认 csv）')
    args = parser.parse_args(argv)

    factors = discover_factors()
    if args.list:
        return 0
    if not factors:
        print('未发现任何因子插件，请先在 factors/ 下添加 compute(df) 插件。')
        return 1

    if args.only:
        names = [n.strip() for n in args.only.split(',') if n.strip()]
        factors = {n: f for n, f in factors.items() if n in names}
        print(f'[过滤] 仅运行: {list(factors)}')
        if not factors:
            print('没有匹配的插件。')
            return 1

    input_path = Path(args.input)
    if not input_path.exists():
        print(f'输入文件不存在: {input_path}')
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

    factor_df = run_factors(df, factors)

    keep_raw = not args.drop_raw
    out_df = assemble(df, factor_df, keep_raw=keep_raw)

    if args.zscore:
        print(f'[标准化] 对 {len(factor_df.columns)} 个因子列做截面 zscore...')
        zscore_cross_section(out_df, list(factor_df.columns))

    output = Path(args.output) if args.output else _default_output(
        input_path, args.start, args.end, args.format)
    output.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if args.format == 'csv':
        out_df.to_csv(output, index=False)
    else:
        out_df.to_parquet(output, index=False)
    size_mb = output.stat().st_size / 1024 / 1024
    print(f'[保存] {output}（{size_mb:.0f} MB，{out_df.shape[0]} 行 × {out_df.shape[1]} 列，'
          f'耗时 {time.time() - t0:.0f}s）')
    print(f'[完成] 总耗时 {time.time() - t_start:.0f}s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
