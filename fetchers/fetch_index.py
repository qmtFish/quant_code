"""
下载指数行情 (AKShare)
输出: data/index/hs300.parquet, data/index/zz500.parquet
"""
import sys
from pathlib import Path
import pandas as pd
import akshare as ak

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import DATA_DIR


def fetch_index(symbol: str, name: str, start_date: str = "2020-01-01"):
    """下载指数行情"""
    df = ak.index_zh_a_hist(symbol=symbol, period="daily",
                             start_date=start_date, end_date="20260630")
    if df.empty:
        print(f"  {name}: 无数据")
        return
    df = df.rename(columns={'日期': 'date', '收盘': 'close'})
    df['date'] = pd.to_datetime(df['date'])
    df = df[['date', 'close']].sort_values('date')
    path = DATA_DIR / 'index' / f'{name}.parquet'
    df.to_parquet(path, index=False)
    print(f"  {name} ({symbol}): {len(df)} 行 -> {path}")


def run():
    print("[指数行情下载]")
    fetch_index("000300", "hs300")
    fetch_index("000905", "zz500")
    # 申万一级行业指数
    fetch_index("801010", "sw_agriculture")  # 示例


if __name__ == '__main__':
    run()
