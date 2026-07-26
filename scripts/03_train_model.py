"""
03 — 模型训练：从因子矩阵训练滚动模型，输出系数。
"""
import sys, json, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import COEF_DIR, TRAIN_WINDOW, TRAIN_MODEL

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


def load_factor_matrix(path: str = None) -> pd.DataFrame:
    """加载因子矩阵"""
    if path is None:
        path = Path(__file__).resolve().parent.parent.parent / 'data' / 'factors' / 'factor_matrix.parquet'
    df = pd.read_parquet(str(path))
    df['date'] = pd.to_datetime(df['date'])
    return df.sort_values(['date', 'code']).reset_index(drop=True)


def get_model(name: str):
    """返回模型实例"""
    name = name.lower()
    if name == 'ols':
        from sklearn.linear_model import LinearRegression
        return LinearRegression(n_jobs=-1), 'coef_'
    elif name == 'ridge':
        from sklearn.linear_model import Ridge
        return Ridge(alpha=1.0), 'coef_'
    elif name == 'catboost':
        from catboost import CatBoostRegressor
        return CatBoostRegressor(iterations=200, depth=4, learning_rate=0.1,
                                  min_data_in_leaf=50, verbose=0, random_seed=42), 'importance_'
    else:
        raise ValueError(f"Unknown model: {name}")


def run(factor_path: str = None, window: int = None, model_name: str = None, out_path: str = None):
    if window is None:
        window = TRAIN_WINDOW
    if model_name is None:
        model_name = TRAIN_MODEL
    if out_path is None:
        out_path = str(COEF_DIR / f'rolling_coefs_{model_name}_{window}d.json')

    print("=" * 55)
    print(f"  模型训练: {model_name.upper()} | {window}天滚动窗口")
    print("=" * 55)

    # 加载因子矩阵
    df = load_factor_matrix(factor_path)
    dates = sorted(df['date'].unique())
    print(f"  因子矩阵: {len(df)} 行, {len(dates)} 个周截面")

    # 检查可用因子列
    available = [c for c in FACTOR_COLS if c in df.columns]
    missing = [c for c in FACTOR_COLS if c not in df.columns]
    if missing:
        print(f"  缺失因子(将被跳过): {len(missing)}")
    print(f"  可用因子: {len(available)}")

    # 行业哑变量
    ind_dum = pd.get_dummies(df['industry'], prefix='ind').iloc[:, 1:]
    X = pd.concat([df[available], ind_dum], axis=1)
    target_col = 'next_ret'
    if target_col not in df.columns:
        print("  警告: 因子矩阵中无 next_ret 列，无法训练")
        return
    y = df[target_col]

    min_weeks = 4
    output = []
    nw = 0
    t0 = time.time()

    for d in dates:
        ws = d - pd.Timedelta(days=window)
        train_dates = [dt for dt in dates if ws <= dt < d]
        if len(train_dates) < min_weeks:
            continue
        nw += 1
        train_mask = df['date'].isin(train_dates)
        test_mask = df['date'] == d

        model, attr = get_model(model_name)
        model.fit(X[train_mask].values, y[train_mask].values)

        if attr == 'coef_':
            full_coefs = model.coef_
            factor_coefs = {col: round(float(full_coefs[j]), 8) for j, col in enumerate(available)}
        else:
            imp = model.feature_importances_
            factor_coefs = {col: round(float(imp[j]), 8) for j, col in enumerate(available)}

        output.append({"date": str(d.date()), "factor_coefficients": factor_coefs})

        # 评估
        y_pred = model.predict(X[test_mask].values)
        y_true = y[test_mask].values
        from scipy.stats import spearmanr
        ic, _ = spearmanr(y_pred, y_true)
        mse = np.mean((y_true - y_pred) ** 2)

        if nw % 10 == 0:
            print(f"  [{nw}/{len(dates)}] {d.date()}  IC={ic:.4f}  MSE={mse:.6f}")

    elapsed = time.time() - t0
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  完成: {nw} 周, {elapsed:.0f}s")
    print(f"  输出: {out_path}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--factor-path', type=str, default=None)
    parser.add_argument('--window', type=int, default=None)
    parser.add_argument('--model', type=str, default=None)
    parser.add_argument('--out', type=str, default=None)
    args = parser.parse_args()
    run(args.factor_path, args.window, args.model, args.out)
