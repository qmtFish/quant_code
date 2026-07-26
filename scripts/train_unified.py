"""
训练入口 —— 委托给 pipeline.model.FactorModel。

输出: coefficients/factor_coefficients_{window}d_{model_type}.json

用法:
    python pipeline/scripts/train_unified.py
    python pipeline/scripts/train_unified.py --window 60 --model ridge
    python pipeline/scripts/train_unified.py --model catboost --start 2025-02-01 --end 2026-06-12
"""
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import DATA_PATH
from pipeline.model import FactorModel
from pipeline.core.data_loader import load_factor_csv


def run(input_path: str = None, window: int = 180,
        model_name: str = 'ols', min_weeks: int = 4,
        output_path: str = None,
        start_date: str = None, end_date: str = None,
        force: bool = False):
    """训练模型。默认禁止覆盖已有文件，加 --force 可强制覆盖。"""
    # 保护：输出文件已存在且未加 --force
    if output_path and Path(output_path).exists() and not force:
        raise FileExistsError(
            f"输出文件已存在: {output_path}\n"
            f"如需覆盖请加 --force"
        )
    pkl_path = output_path.replace('.json', '.pkl') if output_path else None
    if pkl_path and Path(pkl_path).exists() and not force:
        raise FileExistsError(
            f"对应的模型文件已存在: {pkl_path}\n"
            f"如需覆盖请加 --force"
        )

    df = load_factor_csv(input_path)
    if start_date:
        df = df[df['date'] >= start_date]
    if end_date:
        df = df[df['date'] <= end_date]
    print(f"  时间范围: {df['date'].min().date()} ~ {df['date'].max().date()} ({df['date'].nunique()} 截面)")
    model = FactorModel({
        'window': window,
        'model_type': model_name,
        'min_weeks': min_weeks,
    })
    return model.train(df, output_path)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=str, default=None)
    parser.add_argument('--window', type=int, default=180)
    parser.add_argument('--model', type=str, default='ols',
                        choices=['ols', 'ridge', 'lasso', 'rf', 'catboost'])
    parser.add_argument('--output', type=str, default=None)
    parser.add_argument('--min-weeks', type=int, default=4)
    parser.add_argument('--start', type=str, default=None, help='训练起始日期 YYYY-MM-DD')
    parser.add_argument('--end', type=str, default=None, help='训练结束日期 YYYY-MM-DD')
    parser.add_argument('--force', action='store_true', help='强制覆盖已有文件')
    args = parser.parse_args()
    run(args.input, args.window, args.model, args.min_weeks, args.output,
        args.start, args.end, args.force)
