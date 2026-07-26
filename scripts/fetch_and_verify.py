"""
全量下载日线 (Sina源) + 因子计算 + 与CSV对比验证
"""
import sys, time, json
from pathlib import Path
import pandas as pd, numpy as np
import akshare as ak
from scipy.stats import zscore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import DATA_DIR

OUT_DIR = DATA_DIR / 'daily'
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS = {}

# 1. 获取股票列表
print("[1/5] 获取股票列表...")
stocks = ak.stock_info_a_code_name()
def code_to_symbol(code):
    if code.startswith(('6','9')): return f"sh{code}"
    elif code.startswith(('0','3')): return f"sz{code}"
    elif code.startswith(('4','8')): return f"bj{code}"
    return code
stocks['symbol'] = stocks['code'].apply(code_to_symbol)
print(f"  共 {len(stocks)} 只股票")
RESULTS['total_stocks'] = len(stocks)

# 2. 下载日线（只下 2024 年的数据作为验证）
print("[2/5] 下载日线 (2024-06 ~ 2024-07)...")
all_daily = []
success = 0
t0 = time.time()
for _, row in stocks.iterrows():
    try:
        df = ak.stock_zh_a_daily(symbol=row['symbol'], start_date="20240601", end_date="20240710", adjust="qfq")
        if not df.empty:
            df['code'] = row['code']
            all_daily.append(df)
            success += 1
    except:
        pass
    time.sleep(0.2)
    if success % 500 == 0 and success > 0:
        print(f"  已下载 {success}/{len(stocks)}...")

elapsed = time.time() - t0
daily = pd.concat(all_daily, ignore_index=True) if all_daily else pd.DataFrame()
print(f"  成功: {success}/{len(stocks)}, 耗时: {elapsed:.0f}s, 共 {len(daily)} 行")
RESULTS['download'] = {'success': success, 'total': len(stocks), 'rows': len(daily), 'time': elapsed}

# 3. 保存
daily['date'] = pd.to_datetime(daily['date'])
for year, grp in daily.groupby(daily['date'].dt.year):
    path = OUT_DIR / f'{year}.parquet'
    grp.to_parquet(path, index=False)
    print(f"  保存: {path} ({len(grp)} 行)")

# 4. 计算 ret_5d 并与 CSV 对比
print("[3/5] 计算 ret_5d 并验证...")
calc_date = '2024-07-05'
csv = pd.read_csv(r'C:\Users\Cat\Desktop\code\data\20240629_20260629.csv')
csv_date = csv[csv['date'] == calc_date]
csv_map = csv_date.set_index('code')['ret_5d_z'].to_dict()

comparison = {'matched': 0, 'total': 0, 'diff_sum': 0}
our_vals = {}
for _, row in stocks.iterrows():
    code = row['code']
    h = daily[(daily['code'] == code) & (daily['date'] <= calc_date)].sort_values('date')
    if len(h) >= 5:
        ret = h['close'].iloc[-1] / h['close'].iloc[-5] - 1
        our_vals[code] = ret

# 全截面 zscore
codes_list = list(our_vals.keys())
ret_vals = np.array([our_vals[c] for c in codes_list])
mean_r, std_r = np.mean(ret_vals), np.std(ret_vals)
if std_r > 0:
    our_z = {c: (our_vals[c] - mean_r) / std_r for c in codes_list}
else:
    our_z = {c: 0 for c in codes_list}

for csv_code, csv_z in csv_map.items():
    code = csv_code.split('.')[0]
    if code in our_z:
        comparison['total'] += 1
        diff = abs(our_z[code] - csv_z)
        comparison['diff_sum'] += diff
        if diff < 0.5:
            comparison['matched'] += 1

RESULTS['validation'] = comparison
if comparison['total'] > 0:
    avg_diff = comparison['diff_sum'] / comparison['total']
    match_pct = comparison['matched'] / comparison['total'] * 100
    print(f"  对比 {comparison['total']} 只股票:")
    print(f"    平均 |zscore差异|: {avg_diff:.3f}")
    print(f"    差异<0.5的比例: {match_pct:.1f}%")
    print(f"    {'✓ 基本一致' if match_pct > 80 else '? 差异较大'}")

# 5. 保存验证报告
report_path = Path(__file__).resolve().parent / 'fetch_verify_report.json'
with open(report_path, 'w') as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n验证报告: {report_path}")
