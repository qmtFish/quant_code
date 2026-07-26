"""
合并指定文件夹下的所有原始 CSV 文件，去重后输出到目标文件夹。

功能：
  1. 扫描输入文件夹下所有 *.csv 文件
  2. 读取所有文件，自动对齐列（取列并集，缺失列填充 NaN）
  3. 纵向合并
  4. 按 (date, code) 去重，保留后出现的行
  5. 输出一个完整的合并 CSV 文件到输出文件夹
  6. 不进行训练/预测拆分

用法：
  python merge_new_data.py --input-dir data/new_raw_data --output-dir data/all_data
  python merge_new_data.py -i data/new_raw_data -o data/merged
"""

import argparse
import pandas as pd
from pathlib import Path

# ============================
#  命令行参数
# ============================
parser = argparse.ArgumentParser(
    description="合并原始 CSV 数据，去重，不拆分训练/预测数据"
)
parser.add_argument(
    "--input-dir", "-i",
    type=str,
    required=True,
    help="原始 CSV 文件所在文件夹路径，会扫描其中所有 *.csv",
)
parser.add_argument(
    "--output-dir", "-o",
    type=str,
    required=True,
    help="合并去重后 CSV 的输出文件夹路径",
)
args = parser.parse_args()

# ============================
#  路径校验
# ============================
input_dir = Path(args.input_dir)
output_dir = Path(args.output_dir)

if not input_dir.exists():
    raise NotADirectoryError(f"输入文件夹不存在: {input_dir}")
if not input_dir.is_dir():
    raise NotADirectoryError(f"输入路径不是文件夹: {input_dir}")

output_dir.mkdir(parents=True, exist_ok=True)

# ============================
#  扫描 CSV 文件
# ============================
csv_files = sorted(input_dir.glob("*.csv"))
if not csv_files:
    raise FileNotFoundError(
        f"输入文件夹中没有 CSV 文件: {input_dir}"
    )

print(f"[1/4] 输入文件夹: {input_dir}")
print(f"      找到 {len(csv_files)} 个 CSV 文件:")
for f in csv_files:
    size_mb = f.stat().st_size / 1024 / 1024
    print(f"        {f.name}  ({size_mb:.1f} MB)")

# ============================
#  读取 & 合并
# ============================
print(f"\n[2/4] 读取 CSV 文件...")

all_cols: set[str] = set()
dataframes: list[pd.DataFrame] = []

for f in csv_files:
    df = pd.read_csv(f)
    print(f"        {f.name}: {len(df):>10,} 行, {len(df.columns)} 列")
    dataframes.append(df)
    all_cols.update(df.columns)

all_cols = sorted(all_cols)
print(f"      所有文件列并集: {len(all_cols)} 列")

# 对齐列（缺失列填充 NaN）
aligned: list[pd.DataFrame] = []
for f, df in zip(csv_files, dataframes):
    missing = [c for c in all_cols if c not in df.columns]
    if missing:
        print(f"        {f.name}: 缺失 {len(missing)} 列，已填充 NaN")
    aligned.append(df.reindex(columns=all_cols))

print(f"\n[3/4] 纵向合并 & 去重...")
df_merged = pd.concat(aligned, ignore_index=True)
before_dedup = len(df_merged)
print(f"      合并后总行数: {before_dedup:,}")

# ============================
#  去重
# ============================
if "date" not in df_merged.columns:
    raise ValueError("数据中缺少 'date' 列，无法按 (date, code) 去重")
if "code" not in df_merged.columns:
    raise ValueError("数据中缺少 'code' 列，无法按 (date, code) 去重")

df_merged.drop_duplicates(subset=["date", "code"], keep="last", inplace=True)
after_dedup = len(df_merged)
dupes = before_dedup - after_dedup
print(f"      按 (date, code) 去重，移除 {dupes:,} 行")
print(f"      去重后共 {after_dedup:,} 行")

# ============================
#  输出
# ============================
print(f"\n[4/4] 输出合并结果...")

dates = pd.to_datetime(df_merged["date"])
min_date = dates.min().strftime("%Y-%m-%d")
max_date = dates.max().strftime("%Y-%m-%d")

# 从第一个文件名提取前缀（去掉最后两个下划线分隔的日期段）
prefix = csv_files[0].stem
parts = prefix.rsplit("_", 2)
if len(parts) == 3 and len(parts[1]) == 10 and len(parts[2]) == 10:
    prefix = parts[0]

out_name = f"{prefix}_{min_date}_{max_date}.csv"
out_path = output_dir / out_name

df_merged.to_csv(out_path, index=False)
out_size_mb = out_path.stat().st_size / 1024 / 1024

print(f"      输出文件: {out_path}")
print(f"      数据范围: {min_date} ~ {max_date}")
print(f"      总行数:   {after_dedup:,}")
print(f"      文件大小: {out_size_mb:.1f} MB")
print(f"\n完成！")
