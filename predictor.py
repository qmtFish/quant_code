"""
批预测模块 —— 对一段时间内的每个交易日进行预测，输出 JSON。

用法:
    from pipeline.predictor import run_batch_predict

    run_batch_predict(
        start_date='2026-05-01',
        end_date='2026-06-12',
        top_k=20,
        output_path='results/predictions.json',
    )

命令行:
    python -m pipeline.predictor --start 2026-05-01 --end 2026-06-12
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Optional
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.model import FactorModel
from pipeline.core.data_loader import load_factor_csv
from pipeline.config import DATA_PATH, COEF_DIR


def run_batch_predict(
    start_date: str,
    end_date: str,
    input_path: str = None,
    coef_path: str = None,
    top_k: int = 20,
    industry_zscore: bool = False,
    output_path: str = None,
    model_type: str = None,
) -> str:
    """
    对指定时间段内的每个交易日进行预测，结果保存为 JSON。

    Args:
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        coef_path: 系数文件路径，默认取 coefficients/ 下最新文件
        top_k: 每个交易日保留的 Top K 只股票
        industry_zscore: 是否行业内 Z-Score（False=全市场直接打分）
        output_path: 输出 JSON 路径，默认 results/predictions.json

    Returns:
        output_path: JSON 文件路径

    JSON 结构:
        {
            "meta": {
                "start_date": "2026-05-01",
                "end_date": "2026-06-12",
                "coefficient_file": "factor_coefficients_6m_rolling.json",
                "top_k": 20,
                "total_dates": 7,
                "generated_at": "2026-07-14T10:30:00"
            },
            "predictions": [
                {
                    "date": "2026-05-01",
                    "coef_date": "2026-04-24",
                    "n_stocks": 5204,
                    "top": [
                        {"code": "603990.XSHG", "score": 0.0389, "rank_pct": 1.0},
                        ...
                    ]
                },
                ...
            ]
        }
    """
    # ── 自动选择系数文件 ──
    if coef_path is None:
        if model_type:
            matched = sorted(f for f in Path(COEF_DIR).glob(f'*{model_type}*.json')
                             if not f.name.startswith('test'))
            if matched:
                if model_type in ('rf', 'catboost'):
                    for f in reversed(matched):
                        if f.with_suffix('.pkl').exists():
                            coef_path = str(f)
                            break
                else:
                    coef_path = str(matched[-1])

        if coef_path is None:
            rolling_files = sorted(f for f in Path(COEF_DIR).glob('*_*m_*.json')
                                   if not f.name.startswith('test'))
            if not rolling_files:
                rolling_files = sorted(f for f in Path(COEF_DIR).glob('*.json')
                                       if not f.name.startswith('test'))
            coef_path = str(rolling_files[-1])

    # ── 从系数文件中提取历史 IC 和胜率 ──
    mean_ic, win_rate = None, None
    try:
        with open(coef_path, 'r', encoding='utf-8') as f:
            coef_data = json.load(f)
        if isinstance(coef_data, list):
            ics = [r['metrics']['rank_ic'] for r in coef_data
                   if 'metrics' in r and 'rank_ic' in r['metrics']]
        elif isinstance(coef_data, dict):
            records = coef_data.get('records') or coef_data.get('data') or []
            ics = [r['metrics']['rank_ic'] for r in records
                   if 'metrics' in r and 'rank_ic' in r['metrics']]
        else:
            ics = []
        if ics:
            mean_ic = float(np.mean(ics))
            win_rate = float(np.mean([ic > 0 for ic in ics]))
    except Exception:
        pass

    if output_path is None:
        stem = model_type or "auto"
        if mean_ic is not None and win_rate is not None:
            ic_str = f"{mean_ic:.3g}"
            wr_str = f"{win_rate * 100:.0f}"
            stem = f"{stem}_ic{ic_str}_wr{wr_str}"
        output_path = str(Path(DATA_PATH).resolve().parent.parent / 'results' / f'{stem}_predictions.json')

    coef_name = Path(coef_path).name
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 55)
    print(f"  批预测 | {start_date} ~ {end_date}")
    print(f"  系数: {coef_name}")
    if mean_ic is not None:
        print(f"  历史IC: {mean_ic:.4f}  胜率: {win_rate * 100:.0f}%")
    print(f"  Top K: {top_k}")
    print("=" * 55)

    # ── 1. 加载数据 ──
    print("\n[1/3] 加载因子数据...")
    df = load_factor_csv(path=input_path, mode='pred')
    all_dates = sorted(df['date'].unique())
    target_dates = [d for d in all_dates
                    if start_date <= str(d.date()) <= end_date]
    print(f"  目标交易日: {len(target_dates)} 个")

    # ── 2. 初始化模型 ──
    print("[2/3] 初始化模型...")
    model = FactorModel()

    # ── 3. 逐日预测 ──
    print(f"[3/3] 逐日预测...")
    predictions = {}
    t0 = time.time()

    for i, dt in enumerate(target_dates):
        try:
            scores = model.predict(
                df=df,
                coef_path=coef_path,
                date=dt,
                industry_zscore=industry_zscore,
                model_type=model_type,
            )
        except (ValueError, FileNotFoundError) as e:
            print(f"  [{i+1}/{len(target_dates)}] {dt.date()} 跳过: {e}")
            continue

        # 取 Top K
        top = scores.head(top_k)

        # 构建当日预测记录
        day_pred = {
            "n_stocks": len(scores),
            "top": []
        }

        # 从 scores 中提取 coef_date（因为 predict 不返回这个信息）
        # 通过 model 的 coef_date 属性补上
        for _, row in top.iterrows():
            day_pred["top"].append(
                row["code"]
            )

        predictions[str(dt.date() + timedelta(3))] = day_pred

        if (i + 1) % 5 == 0 or i == len(target_dates) - 1:
            print(f"  [{i+1}/{len(target_dates)}] {dt.date()}  "
                  f"完成 ({len(scores)}只→Top{top_k})")

    elapsed = time.time() - t0

    # ── 4. 保存 JSON ──
    result = {
        "meta": {
            "start_date": start_date,
            "end_date": end_date,
            "coefficient_file": coef_name,
            "top_k": top_k,
            "total_dates": len(predictions),
            "model_type": model_type or "auto",
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "elapsed_sec": round(elapsed, 1),
        },
        "predictions": predictions,
    }
    if mean_ic is not None:
        result["meta"]["mean_ic"] = round(mean_ic, 6)
        result["meta"]["win_rate"] = round(win_rate, 4)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n  完成: {len(predictions)} 个交易日, 耗时 {elapsed:.0f}s")
    print(f"  输出: {output_path}")
    print(f"  文件大小: {Path(output_path).stat().st_size / 1024:.0f} KB")

    return output_path


# ── 单独使用 ──
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='批预测')
    parser.add_argument('--start', default='2026-05-01', help='起始日期')
    parser.add_argument('--end', default='2026-06-12', help='结束日期')
    parser.add_argument('--input', default=None, help='因子数据文件路径')
    parser.add_argument('--coef', default=None, help='系数文件路径')
    parser.add_argument('--top-k', type=int, default=100, help='Top K')
    parser.add_argument('--output', default=None, help='输出路径')
    parser.add_argument('--model-type', default=None,
                        help='模型类型 (ols/ridge/lasso/rf/catboost)，默认从JSON自动检测')
    args = parser.parse_args()

    run_batch_predict(
        start_date=args.start,
        end_date=args.end,
        input_path=args.input,
        coef_path=args.coef,
        top_k=args.top_k,
        output_path=args.output,
        model_type=args.model_type,
    )
