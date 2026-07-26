"""
辅助脚本：将已有的 CSV 数据转换为 parquet 格式，以便测试 pipeline。
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import DATA_DIR


def convert_daily_from_csv(csv_path: str):
    """从已有 CSV 生成日线 parquet"""
    print(f"[转换日线] {csv_path}")
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])

    # 构造日线所需列
    # 已有的 CSV 没有完整的 OHLCV，用模拟数据填充
    # 但至少我们可以提取 date, code, close, volume
    has_close = 'close' in df.columns or any('close' in c.lower() for c in df.columns)

    # 按日期+股票聚合
    daily = df[['date', 'code']].copy()
    daily['open'] = 0.0
    daily['high'] = 0.0
    daily['low'] = 0.0
    daily['close'] = 0.0  # 无实际日线
    daily['volume'] = 0.0
    daily['amount'] = 0.0
    daily['turnover'] = 0.0

    # 按年分文件保存
    for year, grp in daily.groupby(daily['date'].dt.year):
        path = DATA_DIR / 'daily' / f'{year}.parquet'
        grp.to_parquet(path, index=False)
        print(f"  -> {path} ({len(grp)} 行)")


def convert_index_from_csv(csv_path: str):
    """从已有 CSV 提取指数数据"""
    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])

    # 从 hs300_ret_5d, zz500_ret_5d 反推指数 close？
    # 更好的办法：直接构造空索引数据，标为待下载
    print("指数数据需要从 AKShare 下载，暂无法从因子 CSV 还原")
    for name in ['hs300', 'zz500']:
        path = DATA_DIR / 'index' / f'{name}.parquet'
        if not path.exists():
            # 创建空文件占位
            pd.DataFrame({'date': [], 'close': []}).to_parquet(path, index=False)
            print(f"  创建空文件: {path}")


def convert_financial_from_csv(csv_path: str):
    """从已有 CSV 提取财务数据"""
    df = pd.read_csv(csv_path)

    # CSV 中的因子列
    fund_cols = ['pe_ratio_z','pb_ratio_z','ps_ratio_z','pcf_ratio_z',
                 'market_cap_z','roe_z','roa_z',
                 'gross_profit_margin_z','net_profit_margin_z',
                 'inc_revenue_year_on_year_z','inc_net_profit_year_on_year_z']

    # 只取每只股票最新一期财务
    fin = df.groupby('code').last().reset_index()
    fin = fin[['code'] + [c for c in fund_cols if c in fin.columns]]
    fin = fin.rename(columns={c: c.replace('_z', '') for c in fund_cols if c in fin.columns})
    fin['report_date'] = pd.Timestamp('2026-06-01')

    path = DATA_DIR / 'financial' / 'latest.parquet'
    fin.to_parquet(path, index=False)
    print(f"  -> {path} ({len(fin)} 行)")


def convert_industry_from_csv(csv_path: str):
    """从已有 CSV 提取行业分类"""
    df = pd.read_csv(csv_path)
    ind = df[['code', 'industry']].drop_duplicates('code')
    ind = ind.rename(columns={'industry': 'industry_code'})

    path = DATA_DIR / 'industry.parquet'
    ind.to_parquet(path, index=False)
    print(f"  -> {path} ({len(ind)} 只股票)")


if __name__ == '__main__':
    csv = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\Cat\Desktop\code\data\20240629_20260629.csv'
    print("=" * 50)
    print(f"  从 {csv} 转换数据")
    print("=" * 50)
    convert_daily_from_csv(csv)
    convert_financial_from_csv(csv)
    convert_industry_from_csv(csv)
    convert_index_from_csv(csv)
    print("\n完成。")
