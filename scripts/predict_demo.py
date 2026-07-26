"""
单独调用 predict 的示例脚本 —— 不依赖回测引擎。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.model import FactorModel
from pipeline.core.data_loader import load_factor_csv
from pipeline.config import DATA_PATH, COEF_DIR

# ── 配置 ──
TARGET_DATE = '2026-04-10'
TOP_K = 20
COEF_FILE = 'factor_coefficients_6m_rolling.json'

# 1. 加载数据
df = load_factor_csv(DATA_PATH)
print(f"数据: {df.shape}, 日期范围: {df['date'].min().date()} ~ {df['date'].max().date()}")

# 2. 初始化模型
model = FactorModel()
coef_path = str(Path(COEF_DIR) / COEF_FILE)

# 3. 预测
scores = model.predict(
    df=df,
    coef_path=coef_path,
    date=TARGET_DATE,
    industry_zscore=False,
)

# 4. 输出 Top 20
print(f"\n  {TARGET_DATE} 全市场评分 Top {TOP_K}")
print(f"  {'代码':>14s}  {'评分':>10s}  {'排名%':>6s}")
print(f"  " + "-" * 35)
for _, r in scores.head(TOP_K).iterrows():
    print(f"  {r['code']:>14s}  {r['score']:>+10.6f}  {r['rank_pct']:>5.1%}")

# 5. 统计信息
print(f"\n  统计: 共 {len(scores)} 只股票")
print(f"  评分范围: {scores['score'].min():.4f} ~ {scores['score'].max():.4f}")
print(f"  评分均值: {scores['score'].mean():.4f}")
