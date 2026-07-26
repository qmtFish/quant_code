"""
统一数据加载器：以 CSV 为唯一输入源。

数据格式约定:
  文件: data/20240629_20260629.csv 或 config 中指定的路径
  列: code, date, industry, next_ret, 因子1_z, 因子2_z, ...

模型参数约定:
  目录: coefficients/
  格式: [{"date": "YYYY-MM-DD", "factor_coefficients": {"因子1": 0.01, ...}}, ...]
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Callable
from pathlib import Path
from datetime import date, datetime
import pandas as pd
import numpy as np
import json

from pipeline.config import DATA_DIR, COEF_DIR
from pipeline.factor_config import FACTOR_COLS


# ═══════════════════════════════════════════════════════════════
# 1. CSV 数据加载
# ═══════════════════════════════════════════════════════════════

_PATTERNS = {'train': 'local_train_data*.csv', 'pred': 'pred_local_train_data*.csv'}


def load_factor_csv(path: str = None, mode: str = 'train') -> pd.DataFrame:
    """
    加载因子 CSV 文件。

    Parameters
    ----------
    path : str, optional
    mode : 'train' or 'pred'

    Returns
    -------
    pd.DataFrame
    """
    print(f"  [数据] 加载 {path}")
    df = pd.read_csv(path)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values(['date', 'code']).reset_index(drop=True)

    # 按 factor_config 裁剪：只保留 code, date, industry + 已有因子 + next_ret(train)
    keep = ['code', 'date', 'industry']
    if mode == 'train' and 'next_ret' in df.columns:
        keep.append('next_ret')
    available = get_available_factor_cols(df)
    keep += [c for c in available if c in df.columns and c not in keep]
    df = df[keep]

    print(f"  [数据] {df.shape}, 日期 {df['date'].min().date()} ~ {df['date'].max().date()}, "
          f"{df['date'].nunique()} 个截面, {len(available)} 个因子")
    return df


def load_pred_factor_csv(path: str = None) -> pd.DataFrame:
    """兼容旧接口：等价于 load_factor_csv(path, mode='pred')"""
    return load_factor_csv(path=path, mode='pred')


def get_available_factor_cols(df: pd.DataFrame) -> List[str]:
    """从 DataFrame 中自动识别因子列"""
    return [c for c in FACTOR_COLS if c in df.columns]


def filter_by_date(df: pd.DataFrame, start_date: str = None,
                   end_date: str = None) -> pd.DataFrame:
    """按日期范围过滤"""
    if start_date:
        df = df[df['date'] >= start_date]
    if end_date:
        df = df[df['date'] <= end_date]
    return df


def get_weekly_dates_csv(df: pd.DataFrame) -> List[pd.Timestamp]:
    """从 CSV 数据获取周频截面日期（取每周最后一个交易日）"""
    dates = df['date'].unique()
    weekly = pd.Series(dates).sort_values().to_series().resample('W-FRI').last().dropna()
    return sorted(weekly.tolist())


def filter_stocks(df: pd.DataFrame, valid_codes: set = None) -> pd.DataFrame:
    """过滤股票池"""
    if valid_codes:
        df = df[df['code'].isin(valid_codes)]
    return df


# ═══════════════════════════════════════════════════════════════
# 2. 模型参数加载 (coefficients/)
# ═══════════════════════════════════════════════════════════════

def load_latest_coefficients(coef_path: str = None,
                              current_date: date = None) -> Tuple[dict, date]:
    """
    从 coefficients/ 目录加载最近一期的因子权重。

    Args:
        coef_path: 系数 JSON 文件路径，默认取 COEF_DIR 中最近的 rolling 文件
        current_date: 当前日期，用于查找最接近的不超过该日期的权重

    Returns:
        (coef_dict: {因子名: 权重}, coef_date: date)
    """
    if coef_path is None:
        coef_path = _find_latest_coef_file()

    with open(coef_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, dict):
        records = (data.get('records') or data.get('data') or [data])
    elif isinstance(data, list):
        records = data
    else:
        return {}, None

    candidates = []
    for record in records:
        if not isinstance(record, dict):
            continue

        # 提取系数
        coef = (record.get('factor_coefficients')
                or record.get('coefficients')
                or record.get('weights')
                or {})
        if not isinstance(coef, dict) or len(coef) < 3:
            continue

        # 提取日期
        rec_date = _extract_date(record)
        if rec_date is None:
            continue
        if current_date is None or rec_date <= current_date:
            candidates.append((rec_date, coef))

    if not candidates:
        return {}, None

    # 取最近一期
    candidates.sort(key=lambda x: x[0])
    latest_date, latest_coef = candidates[-1]

    # 清洗数值
    clean = {}
    for k, v in latest_coef.items():
        try:
            clean[str(k)] = float(v)
        except (ValueError, TypeError):
            continue

    return clean, latest_date


def load_all_coefficients(coef_path: str = None) -> pd.DataFrame:
    """
    加载所有期的系数为一个 DataFrame，方便分析系数变化趋势。
    返回: DataFrame, index=date, columns=因子名
    """
    if coef_path is None:
        coef_path = _find_latest_coef_file()

    with open(coef_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, dict):
        records = (data.get('records') or data.get('data') or [data])
    elif isinstance(data, list):
        records = data

    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        coef = (record.get('factor_coefficients')
                or record.get('coefficients')
                or record.get('weights')
                or {})
        rec_date = _extract_date(record)
        if rec_date is None or not coef:
            continue
        row = {'date': rec_date}
        row.update({k: float(v) for k, v in coef.items()})
        rows.append(row)

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.set_index('date').sort_index()
    return result


def _find_latest_coef_file() -> str:
    """
    从 COEF_DIR 中找到最新的 rolling 系数文件。

    优先级:
      1. 包含窗口天数的文件: factor_coefficients_{window}d_{model}.json
      2. 包含 rolling 的文件
      3. 任意 json 文件
    """
    coef_dir = Path(COEF_DIR)

    # 优先级1: 带滚动窗口的系数文件（格式: factor_coefficients_{N}m/d_rolling.json，排除 test_ 开头文件）
    windowed = sorted(f for f in coef_dir.glob('*_*m_*.json') if not f.name.startswith('test'))
    d_windowed = sorted(f for f in coef_dir.glob('*_*d_*.json') if not f.name.startswith('test'))
    all_windowed = sorted(windowed + d_windowed)
    if all_windowed:
        return str(all_windowed[-1])

    # 优先级2: 含 rolling 关键词的文件（排除旧版无 date 字段的因子系数）
    rolling = sorted(coef_dir.glob('*_rolling.json'))
    if rolling:
        return str(rolling[-1])

    # 优先级3: 含 rolling 关键词的任意文件
    rolling_all = sorted(coef_dir.glob('*rolling*.json'))
    if rolling_all:
        return str(rolling_all[-1])

    # 降级：取任意 json 文件
    json_files = sorted(coef_dir.glob('*.json'))
    if json_files:
        return str(json_files[-1])
    raise FileNotFoundError(f"coefficients/ 目录未找到 JSON 文件: {COEF_DIR}")


def _extract_date(record: dict) -> Optional[date]:
    """从记录中提取日期"""
    for key in ['date', 'trade_date', 'calc_date', 'train_end_date',
                'train_end', 'end_date', 'period_id']:
        val = record.get(key)
        if val is None:
            continue
        try:
            if isinstance(val, str) and len(val) >= 8:
                return pd.Timestamp(val).date()
            return pd.Timestamp(val).date()
        except Exception:
            continue
    return None


# ═══════════════════════════════════════════════════════════════
# 3. 工具函数
# ═══════════════════════════════════════════════════════════════

def get_prices_from_csv(df: pd.DataFrame, date: date) -> Dict[str, float]:
    """
    从 CSV 中模拟获取某日价格（用 next_ret 反推）。
    
    注意: CSV 只有因子和 next_ret，不含实际价格。
    对于回测引擎，价格来自日线 parquet。
    此函数仅用于信号生成等场景。
    """
    # 回退到从 daily parquet 获取
    from pipeline.core.data_loader import load_daily
    try:
        daily = load_daily(str(date), str(date))
        dt = pd.Timestamp(date)
        if dt in daily.index:
            today = daily.loc[dt]
            if isinstance(today, pd.Series):
                return {today.name: float(today['close'])}
            return {code: float(row['close']) for code, row in today.iterrows()}
    except Exception:
        pass
    return {}


def get_industry_map(df: pd.DataFrame) -> Dict[str, List[str]]:
    """从 CSV 生成 {行业代码: [股票列表]} 映射"""
    latest = df.groupby('date').apply(lambda g: g[['code', 'industry']].drop_duplicates('code'))
    latest = latest.reset_index(drop=True)
    ind_map = {}
    for _, row in latest.iterrows():
        ind = str(row['industry'])
        if ind not in ind_map:
            ind_map[ind] = []
        ind_map[ind].append(row['code'])
    return ind_map
