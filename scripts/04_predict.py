"""
04 — 预测信号生成：用训练好的模型系数对最新截面打分。
"""
import sys, json
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import COEF_DIR

FACTOR_COLS = [
    'pe_ratio_z','pb_ratio_z','ps_ratio_z','pcf_ratio_z',
    'fair_price_deviation_z','roe_z','roa_z','gross_profit_margin_z',
    'net_profit_margin_z','inc_revenue_year_on_year_z',
    'inc_net_profit_year_on_year_z','size_log_z','market_cap_z',
    'ret_5d_z','ret_20d_z','ret_60d_z','volatility_20d_z',
    'hl_range_5d_z','vol_ma_ratio_z',
    'ind_ret_5d_z','ind_ret_20d_z','ind_vol_20d_z','ind_alpha_20d_z',
    'hs300_ret_5d_z','hs300_ret_20d_z',
    'zz500_ret_5d_z','zz500_ret_20d_z',
]


def load_coefficients(path: str) -> list:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_factor_matrix(path: str = None) -> pd.DataFrame:
    if path is None:
        path = Path(__file__).resolve().parent.parent.parent / 'data' / 'factors' / 'factor_matrix.parquet'
    df = pd.read_parquet(str(path))
    df['date'] = pd.to_datetime(df['date'])
    return df


def run(factor_path: str = None, coef_path: str = None, out_dir: str = None):
    print("=" * 55)
    print("  04 - Predict & Generate Signals")
    print("=" * 55)

    if coef_path is None:
        coef_dir = Path(__file__).resolve().parent.parent.parent / 'coefficients'
        coef_files = list(coef_dir.glob('*.json'))
        if not coef_files:
            print("  ERROR: No coefficient files found. Run 03_train_model.py first.")
            return
        coef_path = str(coef_files[-1])
        print(f"  Auto-selected: {coef_path}")

    if out_dir is None:
        out_dir = str(Path(__file__).resolve().parent.parent.parent / 'results' / 'signals')
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    coefs = load_coefficients(coef_path)
    print(f"  Coefficients: {len(coefs)} periods from {coef_path}")

    df = load_factor_matrix(factor_path)
    dates = sorted(df['date'].unique())
    print(f"  Factor matrix: {len(df)} rows, {len(dates)} weeks")

    available = [c for c in FACTOR_COLS if c in df.columns]

    signals_list = []
    for entry in coefs:
        d = pd.Timestamp(entry['date'])
        if d not in dates:
            continue
        mask = df['date'] == d
        codes = df.loc[mask, 'code'].values
        X_cur = df.loc[mask, available].values
        factor_c = entry['factor_coefficients']
        raw_coefs = np.array([factor_c.get(col, 0.0) for col in available])
        scores = X_cur @ raw_coefs
        sub = pd.DataFrame({'date': d, 'code': codes, 'score': scores})
        sub['rank'] = sub['score'].rank(pct=True)
        signals_list.append(sub)

    if not signals_list:
        print("  No results")
        return

    signals = pd.concat(signals_list, ignore_index=True)
    parquet_file = str(Path(out_dir) / 'signals.parquet')
    csv_file = str(Path(out_dir) / 'signals.csv')
    signals.to_parquet(parquet_file, index=False)
    signals.to_csv(csv_file, index=False)
    print(f"\n  Signals: {len(signals)} rows, {signals['date'].nunique()} periods")
    print(f"  -> {parquet_file}")
    print(f"  -> {csv_file}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--factor-path', type=str, default=None)
    parser.add_argument('--coef-path', type=str, default=None)
    parser.add_argument('--out-dir', type=str, default=None)
    args = parser.parse_args()
    run(args.factor_path, args.coef_path, args.out_dir)
