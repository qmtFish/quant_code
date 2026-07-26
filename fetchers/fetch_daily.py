"""
下载 A 股日线行情 (AKShare)
输出: data/daily/YYYY.parquet (按年分文件)
"""
import time, sys
from pathlib import Path
import pandas as pd
import akshare as ak

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import DATA_DIR


def get_stock_list() -> list:
    """获取全部A股代码列表"""
    df = ak.stock_zh_a_spot_em()
    codes = df['代码'].tolist()
    print(f"  获取到 {len(codes)} 只股票")
    return codes


def fetch_daily_batch(codes: list, start_date: str, end_date: str,
                      batch_size: int = 100) -> pd.DataFrame:
    """批量下载日线"""
    all_dfs = []
    total = len(codes)
    for i in range(0, total, batch_size):
        batch = codes[i:i+batch_size]
        for code in batch:
            try:
                df = ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start_date, end_date=end_date,
                    adjust="qfq"
                )
                if df.empty:
                    continue
                # 标准化列名
                df = df.rename(columns={
                    '日期': 'date', '股票代码': 'code',
                    '开盘': 'open', '收盘': 'close',
                    '最高': 'high', '最低': 'low',
                    '成交量': 'volume', '成交额': 'amount',
                    '换手率': 'turnover',
                })
                df = df[['date', 'code', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']]
                all_dfs.append(df)
            except Exception as e:
                print(f"    跳过 {code}: {e}")
            time.sleep(0.3)  # 避免被封
        print(f"  [{i+len(batch)}/{total}] 完成")
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


def run(start_date: str = "2020-01-01", end_date: str = None):
    """入口函数"""
    from datetime import datetime
    if end_date is None:
        end_date = datetime.today().strftime("%Y-%m-%d")

    print(f"[日线下载] {start_date} ~ {end_date}")
    codes = get_stock_list()
    df = fetch_daily_batch(codes, start_date, end_date)

    if df.empty:
        print("  无数据")
        return

    # 按年分文件存储
    df['date'] = pd.to_datetime(df['date'])
    daily_dir = DATA_DIR / 'daily'
    for year, grp in df.groupby(df['date'].dt.year):
        path = daily_dir / f'{year}.parquet'
        # 增量追加
        if path.exists():
            old = pd.read_parquet(path)
            grp = pd.concat([old, grp]).drop_duplicates(subset=['date', 'code']).reset_index(drop=True)
        grp.to_parquet(path, index=False)
        print(f"  -> {path} ({len(grp)} 行)")


if __name__ == '__main__':
    run()
