"""
下载 A 股财务指标 (AKShare)
输出: data/financial/latest.parquet
"""
import time, sys
from pathlib import Path
import pandas as pd
import akshare as ak

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import DATA_DIR


def fetch_financial_single(code: str) -> pd.DataFrame:
    """获取单只股票关键财务指标"""
    # 使用东方财富利润表获取营收、净利润等
    try:
        profit = ak.stock_profit_sheet_by_report_em(symbol=code)
        if profit.empty:
            return pd.DataFrame()
        # 取最近一期
        profit = profit.iloc[:1]
        result = {'code': code, 'report_date': profit['REPORT_DATE'].iloc[0] if 'REPORT_DATE' in profit.columns else None}

        # 映射字段
        field_map = {
            'TOTAL_OPERATE_INCOME': 'revenue',
            'OPERATE_PROFIT': 'operate_profit',
            'TOTAL_PROFIT': 'total_profit',
            'INCOME_NET': 'net_profit',
            'OPERATE_COST': 'operate_cost',
        }
        for eng, cn in field_map.items():
            if eng in profit.columns:
                result[cn] = float(profit[eng].iloc[0]) if profit[eng].iloc[0] else 0.0

        return pd.DataFrame([result])
    except:
        return pd.DataFrame()


def fetch_valuation_batch(codes: list, batch_size: int = 100) -> pd.DataFrame:
    """批量获取估值数据（PE/PB/市值等）"""
    all_dfs = []
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        try:
            # 使用实时行情获取估值
            spot = ak.stock_zh_a_spot_em()
            spot = spot[spot['代码'].isin(batch)]
            spot = spot.rename(columns={
                '代码': 'code', '总市值': 'market_cap',
                '流通市值': 'circulating_market_cap',
                '市盈率-动态': 'pe_ratio', '市净率': 'pb_ratio',
            })
            all_dfs.append(spot[['code', 'market_cap', 'circulating_market_cap', 'pe_ratio', 'pb_ratio']])
        except Exception as e:
            print(f"  batch {i} 失败: {e}")
        time.sleep(0.5)
    if all_dfs:
        return pd.concat(all_dfs, ignore_index=True)
    return pd.DataFrame()


def run():
    print("[财务数据下载]")
    # 先获取所有股票列表
    codes = ak.stock_zh_a_spot_em()['代码'].tolist()
    print(f"  共 {len(codes)} 只股票")

    # 获取估值数据
    val = fetch_valuation_batch(codes)
    print(f"  估值数据: {len(val)} 行")

    # 保存
    path = DATA_DIR / 'financial' / 'latest.parquet'
    val.to_parquet(path, index=False)
    print(f"  -> {path}")


if __name__ == '__main__':
    run()
