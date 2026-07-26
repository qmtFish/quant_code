"""
一键全流程回测脚本。

执行顺序:
  1. fetch_all       — 下载数据（日线、财务、指数）
  2. build_factors   — 构建因子矩阵
  3. train_model     — 训练模型（OLS/CatBoost）
  4. predict         — 生成预测信号
  5. backtest        — 事件驱动回测
  6. report          — 可视化报告 + 归因分析

用法:
    python run_pipeline.py                         # 全流程
    python run_pipeline.py --steps 1-3             # 只跑前3步
    python run_pipeline.py --strategy my_strat.py  # 指定策略
"""
from __future__ import annotations
import sys, os, time, json, subprocess as sp
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline.config import (DATA_DIR, FACTOR_DIR, RESULT_DIR, COEF_DIR,
                               BACKTEST_START, BACKTEST_END,
                               INITIAL_CASH, WEIGHT_FILE)


# ─────────────────────────────────────────────────────────────
# 步骤执行函数
# ─────────────────────────────────────────────────────────────

def step_fetch(start: str = '2023-01-01', end: str = None):
    """下载数据"""
    print("\n" + "=" * 60)
    print(f"  Step 1/6: 下载数据")
    print("=" * 60)

    from pipeline.fetchers.fetch_daily import run as fetch_daily
    from pipeline.fetchers.fetch_financial import run as fetch_financial
    from pipeline.fetchers.fetch_index import run as fetch_index

    t0 = time.time()

    print("  [1.1] 日线行情...")
    fetch_daily(start_date=start, end_date=end)

    print("  [1.2] 财务数据...")
    try:
        fetch_financial()
    except Exception as e:
        print(f"  [跳过] 财务数据: {e}")

    print("  [1.3] 指数行情...")
    try:
        fetch_index()
    except Exception as e:
        print(f"  [跳过] 指数数据: {e}")

    print(f"  数据下载完成, 耗时 {time.time()-t0:.0f}s\n")


def step_build_factors(start: str = None, end: str = None):
    """构建因子矩阵"""
    print("\n" + "=" * 60)
    print("  Step 2/6: 构建因子矩阵")
    print("=" * 60)

    from pipeline.scripts.run_build_factors import run as build_factors
    build_factors(start_date=start, end_date=end)


def step_train(window: int = 180, model: str = 'ols'):
    """训练模型（统一接口，读CSV + 输出到 coefficients/）"""
    print("\n" + "=" * 60)
    print("  Step 3/6: 训练模型")
    print("=" * 60)

    from pipeline.scripts.train_unified import run as train_unified
    train_unified(
        input_path=None,  # 使用 config.DATA_PATH
        window=window,
        model_name=model,
    )


def step_predict(coef_path: str = None):
    """生成预测信号（统一接口）"""
    print("\n" + "=" * 60)
    print("  Step 4/6: 生成预测信号")
    print("=" * 60)

    # 预测即用最新训练好的系数执行回测
    # 如果已有 coefficients/ 下的文件，直接进入 backtest
    print("  [提示] 预测信号集成在回测引擎中，引擎启动时自动加载系数")
    print("         跳过独立步骤，直接进入回测")


def step_backtest(strategy_path: str = None,
                  start: str = None, end: str = None,
                  cash: float = None):
    """执行事件驱动回测"""
    print("\n" + "=" * 60)
    print("  Step 5/6: 事件驱动回测")
    print("=" * 60)

    # 如果未指定策略，使用示例策略
    if strategy_path is None:
        strategy_path = str(Path(__file__).resolve().parent / 'example_strategy.py')

    # BacktestEngine 定义在 pipeline/scripts/05_backtest.py
    import importlib
    bt_spec = importlib.util.spec_from_file_location(
        'backtest_engine',
        str(Path(__file__).resolve().parent / 'pipeline' / 'scripts' / '05_backtest.py')
    )
    bt_mod = importlib.util.module_from_spec(bt_spec)
    bt_spec.loader.exec_module(bt_mod)
    BacktestEngine = bt_mod.BacktestEngine

    # 动态加载策略
    import importlib.util
    spec = importlib.util.spec_from_file_location('strategy_mod', strategy_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    strategy_class = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and hasattr(obj, 'initialize') and name != 'Strategy':
            strategy_class = obj
            break

    if strategy_class is None:
        print("  错误: 策略文件中未找到有效策略类")
        return

    engine = BacktestEngine(
        strategy_class=strategy_class,
        initial_cash=cash or INITIAL_CASH,
        start_date=start or BACKTEST_START,
        end_date=end or BACKTEST_END,
    )
    summary = engine.run()
    return summary


def step_report(output_dir: str = None):
    """生成可视化报告 + 归因分析"""
    print("\n" + "=" * 60)
    print("  Step 6/6: 生成报告")
    print("=" * 60)

    if output_dir is None:
        output_dir = str(RESULT_DIR / 'reports')

    # 6.1 可视化报告
    print("  [6.1] 可视化图表...")
    try:
        from pipeline.metrics.visualization import run_from_engine
        portfolio_csv = str(RESULT_DIR / 'portfolios' / 'daily_portfolio.csv')
        if Path(portfolio_csv).exists():
            run_from_engine(portfolio_csv, output_dir=output_dir)
        else:
            print(f"  [跳过] 未找到 {portfolio_csv}，请先运行回测")
    except Exception as e:
        print(f"  [跳过] 可视化: {e}")

    # 6.2 归因分析
    print("  [6.2] 归因分析...")
    try:
        from pipeline.metrics.attribution import brinson_attribution, factor_attribution, industry_attribution
        # 读取持仓和交易数据
        orders_csv = str(RESULT_DIR / 'portfolios' / 'orders.csv')
        portfolio_csv = str(RESULT_DIR / 'portfolios' / 'daily_portfolio.csv')

        if Path(portfolio_csv).exists():
            df = pd.read_csv(portfolio_csv)
            print(f"  归因数据: {len(df)} 个交易日")
            # 简单归因摘要
            from pipeline.metrics.performance import PerformanceMetrics
            pm = PerformanceMetrics(daily_returns=df['return'].values)
            report = pm.full_report()
            with open(Path(output_dir) / 'attribution_report.txt', 'w') as f:
                f.write(report)
            print(f"  -> {output_dir}/attribution_report.txt")
    except Exception as e:
        print(f"  [跳过] 归因分析: {e}")

    print(f"\n  报告生成完成: {output_dir}/")


# ─────────────────────────────────────────────────────────────
# 主控制函数
# ─────────────────────────────────────────────────────────────

def run_pipeline(steps: str = '1-6',
                 strategy_path: str = None,
                 fetch_start: str = '2023-01-01',
                 fetch_end: str = None,
                 backtest_start: str = None,
                 backtest_end: str = None,
                 cash: float = None,
                 skip_fetch: bool = False):
    """
    运行全流程回测。

    Args:
        steps: 步骤范围，如 '1-6' 或 '1,3,5'
        strategy_path: 策略文件路径
        fetch_start: 数据下载起始日期
        fetch_end: 数据下载结束日期
        backtest_start: 回测起始日期
        backtest_end: 回测结束日期
        cash: 初始资金
        skip_fetch: 跳过数据下载（如果已有数据）
    """
    t_all = time.time()

    # 解析步骤
    if '-' in steps:
        parts = steps.split('-')
        step_range = list(range(int(parts[0]), int(parts[1]) + 1))
    elif ',' in steps:
        step_range = [int(s) for s in steps.split(',')]
    else:
        step_range = [int(s) for s in steps.split(',')]

    # 设置默认日期
    if backtest_start is None:
        backtest_start = BACKTEST_START
    if backtest_end is None:
        backtest_end = BACKTEST_END

    print("=" * 60)
    print("  CodeWhale 回测全流程")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  步骤: {steps} -> {step_range}")
    print(f"  回测期: {backtest_start} ~ {backtest_end}")
    print(f"  初始资金: {cash or INITIAL_CASH:,.0f}")
    print("=" * 60)

    for step in step_range:
        t_step = time.time()

        if step == 1:
            if skip_fetch:
                print("  [跳过] Step 1: 数据已存在")
            else:
                step_fetch(fetch_start, fetch_end)

        elif step == 2:
            step_build_factors(backtest_start, backtest_end)

        elif step == 3:
            step_train()

        elif step == 4:
            step_predict()

        elif step == 5:
            step_backtest(strategy_path, backtest_start, backtest_end, cash)

        elif step == 6:
            step_report()

        else:
            print(f"  [警告] 未知步骤: {step}")

        print(f"  步骤{step}耗时: {time.time()-t_step:.0f}s")

    print(f"\n  全流程完成, 总耗时: {time.time()-t_all:.0f}s\n")


# ─────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='回测全流程')
    parser.add_argument('--steps', type=str, default='2-6',
                        help='步骤范围，如 1-6 或 1,3,5 (默认 2-6 跳过数据下载)')
    parser.add_argument('--strategy', type=str, default=None,
                        help='策略文件路径 (默认 example_strategy.py)')
    parser.add_argument('--fetch-start', type=str, default='2023-01-01',
                        help='数据下载起始日期')
    parser.add_argument('--fetch-end', type=str, default=None)
    parser.add_argument('--start', type=str, default=None,
                        help='回测起始日期')
    parser.add_argument('--end', type=str, default=None,
                        help='回测结束日期')
    parser.add_argument('--cash', type=float, default=None,
                        help='初始资金')
    parser.add_argument('--skip-fetch', action='store_true',
                        help='跳过数据下载')

    args = parser.parse_args()

    run_pipeline(
        steps=args.steps,
        strategy_path=args.strategy,
        backtest_start=args.start,
        backtest_end=args.end,
        cash=args.cash,
        skip_fetch=args.skip_fetch or args.steps != '1-6',
    )
