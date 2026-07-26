"""
因子生产入口：从原始 parquet 数据计算因子矩阵。
"""
import sys, time
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import DATA_DIR, FACTOR_DIR
from pipeline.core.data_loader import load_daily, load_financial, load_all_index, load_industry, get_weekly_dates
from pipeline.core.factor_engine import build_factor_matrix


def run(start_date: str = None, end_date: str = None):
    print("=" * 55)
    print("  因子生产")
    print("=" * 55)

    # 1. 加载数据
    print("[1/4] 加载日线行情...")
    daily = load_daily(start_date, end_date)
    print(f"      {len(daily)} 行, {daily.index.get_level_values('date').nunique()} 个交易日")

    print("[2/4] 加载财务数据...")
    try:
        financial = load_financial()
        print(f"      {len(financial)} 行")
    except FileNotFoundError:
        print("      财务数据未找到，使用日线替代")
        financial = pd.DataFrame()

    print("[3/4] 加载指数数据...")
    try:
        index = load_all_index()
        for k, v in index.items():
            print(f"      {k}: {len(v)} 行")
    except FileNotFoundError:
        print("      指数数据未找到")
        index = {}

    print("[4/4] 加载行业分类...")
    try:
        industry = load_industry()
        print(f"      {len(industry)} 只股票")
    except FileNotFoundError:
        print("      行业分类未找到，使用默认行业")
        industry = pd.DataFrame()

    # 2. 确定周频截面日期
    weekly_dates = get_weekly_dates(daily)
    print(f"\n  共 {len(weekly_dates)} 个周截面")

    if start_date:
        weekly_dates = [d for d in weekly_dates if str(d.date()) >= start_date]
    if end_date:
        weekly_dates = [d for d in weekly_dates if str(d.date()) <= end_date]
    print(f"  过滤后 {len(weekly_dates)} 个周截面")

    # 3. 每个截面的股票列表
    stocks_list = []
    for d in weekly_dates:
        codes = daily.loc[d].index.tolist() if d in daily.index else []
        stocks_list.append(codes)

    # 4. 计算因子矩阵
    print("\n  开始计算因子...")
    t0 = time.time()
    result = build_factor_matrix(weekly_dates, stocks_list, daily, financial, index, industry)
    elapsed = time.time() - t0

    if result.empty:
        print("  因子矩阵为空！")
        return

    print(f"\n  因子矩阵: {result.shape}")
    print(f"  耗时: {elapsed:.0f}s")
    print(f"  因子列: {[c for c in result.columns if c not in ['code','date','industry']][:5]}...")

    # 5. 保存
    path = FACTOR_DIR / 'factor_matrix.parquet'
    result.to_parquet(path, index=False)
    print(f"\n  已保存: {path}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=str, default=None)
    parser.add_argument('--end', type=str, default=None)
    args = parser.parse_args()
    run(args.start, args.end)
