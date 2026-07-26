"""
回测结果可视化模块 —— 生成聚宽风格的图表报告。

图表类型:
  1. 累计收益曲线（策略 vs 基准）
  2. 回撤曲线
  3. 月度收益热力图
  4. 年度收益柱状图
  5. 滚动夏普比率
  6. 多空曲线（如有）
"""
from __future__ import annotations
from typing import List, Optional, Dict
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import date, datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.colors import TwoSlopeNorm
import matplotlib.dates as mdates

# 中文字体支持
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


# ─────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────

def _ensure_numpy(arr) -> np.ndarray:
    """确保输入为 numpy 数组"""
    if isinstance(arr, pd.Series):
        return arr.values
    if isinstance(arr, list):
        return np.array(arr)
    return np.asarray(arr, dtype=float)


def _calc_monthly_returns(returns: np.ndarray, dates: List) -> pd.DataFrame:
    """将日收益率聚合为月度收益率矩阵 (年 x 月)"""
    if len(returns) == 0 or len(dates) == 0:
        return pd.DataFrame()

    df = pd.DataFrame({
        'return': returns,
        'date': pd.to_datetime(dates) if not isinstance(dates[0], pd.Timestamp) else dates,
    })
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month

    monthly = df.groupby(['year', 'month'])['return'].apply(
        lambda x: (1 + x).prod() - 1
    ).reset_index()
    monthly.columns = ['year', 'month', 'return']

    pivot = monthly.pivot(index='year', columns='month', values='return')
    pivot.columns = [f'{m}月' for m in pivot.columns]
    pivot.index.name = None
    return pivot


def _calc_annual_returns(returns: np.ndarray, dates: List) -> pd.Series:
    """计算每年收益率"""
    if len(returns) == 0 or len(dates) == 0:
        return pd.Series(dtype=float)

    df = pd.DataFrame({
        'return': returns,
        'year': pd.to_datetime(dates).year,
    })
    annual = df.groupby('year')['return'].apply(lambda x: (1 + x).prod() - 1)
    return annual


# ─────────────────────────────────────────────────────────────
# 图表生成函数
# ─────────────────────────────────────────────────────────────

def plot_cumulative_return(returns: np.ndarray,
                           benchmark_returns: Optional[np.ndarray] = None,
                           dates: Optional[List] = None,
                           title: str = '累计收益曲线',
                           save_path: str = None) -> plt.Figure:
    """
    绘制累计收益曲线。
    """
    returns = _ensure_numpy(returns)
    cum = (1 + returns).cumprod()

    fig, ax = plt.subplots(figsize=(14, 6))

    x = range(len(cum)) if dates is None else dates

    ax.plot(x, cum, label='策略', color='#1f77b4', lw=1.5)
    ax.fill_between(x, 1.0, cum, alpha=0.1, color='#1f77b4')

    if benchmark_returns is not None:
        bench = _ensure_numpy(benchmark_returns)
        cum_bench = (1 + bench).cumprod()
        # 对齐长度
        min_len = min(len(cum), len(cum_bench))
        ax.plot(x[:min_len], cum_bench[:min_len], label='基准',
                color='#d62728', lw=1.2, ls='--')
        ax.fill_between(x[:min_len], 1.0, cum_bench[:min_len], alpha=0.05, color='#d62728')

    ax.axhline(1.0, color='gray', lw=0.5, ls='--')
    ax.set_title(title, fontsize=13, pad=10)
    ax.set_ylabel('净值', fontsize=11)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # 格式化 Y 轴为百分比
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f'{y:.2f}'))

    if dates is not None and len(dates) > 20:
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45)

    plt.tight_layout()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  [图表] 累计收益 -> {save_path}")
    return fig


def plot_drawdown(returns: np.ndarray,
                  dates: Optional[List] = None,
                  title: str = '回撤曲线',
                  save_path: str = None) -> plt.Figure:
    """绘制回撤曲线"""
    returns = _ensure_numpy(returns)
    cum = (1 + returns).cumprod()
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak

    fig, ax = plt.subplots(figsize=(14, 4))
    x = range(len(dd)) if dates is None else dates

    ax.fill_between(x, 0, dd * 100, color='#d62728', alpha=0.5, lw=0)
    ax.plot(x, dd * 100, color='#d62728', lw=1.0)
    ax.axhline(0, color='gray', lw=0.5)

    # 标注最大回撤
    min_idx = np.argmin(dd)
    ax.annotate(f'最大回撤 {dd[min_idx]*100:.2f}%',
                xy=(x[min_idx], dd[min_idx] * 100),
                xytext=(x[min_idx], dd[min_idx] * 100 - 8),
                arrowprops=dict(arrowstyle='->', color='black', lw=0.8),
                fontsize=10, color='darkred',
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))

    ax.set_title(title, fontsize=13, pad=10)
    ax.set_ylabel('回撤 (%)', fontsize=11)
    ax.set_ylim(dd.min() * 100 - 15, 5)
    ax.grid(True, alpha=0.3)

    if dates is not None and len(dates) > 20:
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45)

    plt.tight_layout()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  [图表] 回撤 -> {save_path}")
    return fig


def plot_monthly_heatmap(returns: np.ndarray,
                         dates: Optional[List] = None,
                         title: str = '月度收益率热力图 (%)',
                         save_path: str = None) -> plt.Figure:
    """绘制月度收益率热力图"""
    returns = _ensure_numpy(returns)
    if dates is None:
        return plt.figure()

    monthly = _calc_monthly_returns(returns, dates)
    if monthly.empty:
        return plt.figure()

    data = monthly.values * 100  # 转为百分比
    years = monthly.index.values
    months = monthly.columns.values

    vmax = max(abs(data.min()), abs(data.max()), 0.5)
    norm = TwoSlopeNorm(vmin=-vmax, vcenter=0, vmax=vmax)

    fig, ax = plt.subplots(figsize=(12, max(4, len(years) * 0.5 + 2)))
    im = ax.imshow(data, aspect='auto', cmap='RdYlGn', norm=norm, interpolation='nearest')

    # 标注数值
    for i in range(len(years)):
        for j in range(len(months)):
            val = data[i, j]
            if np.isnan(val):
                continue
            color = 'white' if abs(val) > vmax * 0.6 else 'black'
            ax.text(j, i, f'{val:.1f}', ha='center', va='center',
                    fontsize=8, color=color, fontweight='bold')

    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(months, fontsize=9)
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels([str(y) for y in years], fontsize=9)
    ax.set_title(title, fontsize=13, pad=10)

    plt.colorbar(im, ax=ax, shrink=0.6, label='收益率 (%)')

    plt.tight_layout()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  [图表] 月度热力图 -> {save_path}")
    return fig


def plot_annual_returns(returns: np.ndarray,
                        benchmark_returns: Optional[np.ndarray] = None,
                        dates: Optional[List] = None,
                        title: str = '年度收益率对比',
                        save_path: str = None) -> plt.Figure:
    """绘制年度收益率柱状图"""
    returns = _ensure_numpy(returns)
    if dates is None:
        return plt.figure()

    annual = _calc_annual_returns(returns, dates)
    if annual.empty:
        return plt.figure()

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(annual))
    colors = ['#d62728' if v < 0 else '#2ca02c' for v in annual.values]

    bars = ax.bar(x, annual.values * 100, color=colors, width=0.6, label='策略', alpha=0.8)

    # 标注数值
    for i, (bar, val) in enumerate(zip(bars, annual.values)):
        ax.text(bar.get_x() + bar.get_width() / 2,
                1 if val > 0 else bar.get_height() - 3,
                f'{val*100:.1f}%', ha='center', va='bottom' if val > 0 else 'top',
                fontsize=10, fontweight='bold')

    # 基准对比
    if benchmark_returns is not None:
        bench = _ensure_numpy(benchmark_returns)
        bench_annual = _calc_annual_returns(bench, dates)
        bench_annual = bench_annual[bench_annual.index.isin(annual.index)]
        if len(bench_annual) > 0:
            ax.plot(x[:len(bench_annual)], bench_annual.values * 100,
                    'D-', color='#1f77b4', lw=1.5, markersize=6, label='基准')

    ax.axhline(0, color='black', lw=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels([str(y) for y in annual.index], fontsize=9)
    ax.set_ylabel('收益率 (%)', fontsize=11)
    ax.set_title(title, fontsize=13, pad=10)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  [图表] 年度收益 -> {save_path}")
    return fig


def plot_rolling_sharpe(returns: np.ndarray,
                        dates: Optional[List] = None,
                        window: int = 60,
                        rf_annual: float = 0.02,
                        title: str = '滚动夏普比率',
                        save_path: str = None) -> plt.Figure:
    """绘制滚动夏普比率"""
    returns = _ensure_numpy(returns)
    if len(returns) < window + 10:
        return plt.figure()

    rf_period = (1 + rf_annual) ** (1 / 252) - 1
    excess = returns - rf_period
    rolling = pd.Series(excess).rolling(window).apply(
        lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0
    ).dropna().values

    fig, ax = plt.subplots(figsize=(14, 4))
    x = range(len(rolling)) if dates is None else dates[window-1:]

    colors = ['#d62728' if v < 0 else '#2ca02c' for v in rolling]
    ax.bar(x, rolling, color=colors, width=0.8 if dates is None else 1, alpha=0.7)
    ax.axhline(0, color='gray', lw=0.5)

    # 标注均值线
    mean_sharpe = np.mean(rolling)
    ax.axhline(mean_sharpe, color='#1f77b4', ls='--', lw=0.8,
               label=f'均值={mean_sharpe:.2f}')

    ax.set_title(f'{title} (窗口={window}天)', fontsize=13, pad=10)
    ax.set_ylabel('夏普比率', fontsize=11)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    if dates is not None and len(dates) > 20:
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.xticks(rotation=45)

    plt.tight_layout()
    if save_path:
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  [图表] 滚动夏普 -> {save_path}")
    return fig


# ─────────────────────────────────────────────────────────────
# 综合报告生成
# ─────────────────────────────────────────────────────────────

def generate_visual_report(returns: np.ndarray,
                            benchmark_returns: Optional[np.ndarray] = None,
                            dates: Optional[List] = None,
                            output_dir: str = 'results/reports',
                            prefix: str = 'backtest') -> Dict[str, str]:
    """
    生成全套可视化报告，返回 {图表名: 路径} 字典。

    Args:
        returns: 策略每日收益率序列
        benchmark_returns: 基准每日收益率（可选）
        dates: 对应的日期列表
        output_dir: 输出目录
        prefix: 文件名前缀
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    paths = {}

    # 1. 累计收益
    p = str(out / f'{prefix}_cumulative_return.png')
    plot_cumulative_return(returns, benchmark_returns, dates, save_path=p)
    paths['cumulative_return'] = p

    # 2. 回撤
    p = str(out / f'{prefix}_drawdown.png')
    plot_drawdown(returns, dates, save_path=p)
    paths['drawdown'] = p

    # 3. 月度热力图
    p = str(out / f'{prefix}_monthly_returns.png')
    plot_monthly_heatmap(returns, dates, save_path=p)
    paths['monthly_heatmap'] = p

    # 4. 年度收益
    p = str(out / f'{prefix}_annual_returns.png')
    plot_annual_returns(returns, benchmark_returns, dates, save_path=p)
    paths['annual_returns'] = p

    # 5. 滚动夏普
    p = str(out / f'{prefix}_rolling_sharpe.png')
    plot_rolling_sharpe(returns, dates, save_path=p)
    paths['rolling_sharpe'] = p

    print(f"\n  报告生成完毕: {out}/")
    return paths


def run_from_engine(portfolio_csv: str, benchmark_code: str = 'hs300',
                     output_dir: str = None) -> Dict[str, str]:
    """
    从引擎输出的 daily_portfolio.csv 生成可视化报告。

    Args:
        portfolio_csv: daily_portfolio.csv 路径
        benchmark_code: 基准代码
        output_dir: 输出目录
    """
    # 读取持仓数据
    df = pd.read_csv(portfolio_csv)
    df['date'] = pd.to_datetime(df['date'])

    returns = df['return'].values
    dates = df['date'].tolist()
    values = df['total_value'].values

    if output_dir is None:
        output_dir = str(Path(portfolio_csv).parent.parent / 'reports')

    # 读取基准收益率（从 index parquet 中计算）
    from pipeline.core.data_loader import load_index
    try:
        idx = load_index(benchmark_code)
        idx = idx.sort_index()
        idx_rets = idx['close'].pct_change().fillna(0).values
        # 对齐到回测日期
        idx_dates = idx.index.tolist()
        date_set = set(d.date() for d in dates)
        aligned = []
        for d in dates:
            if d.date() in date_set and d in idx.index:
                i = list(idx.index).index(d)
                aligned.append(idx_rets[i] if i > 0 else 0.0)
            else:
                aligned.append(0.0)
        benchmark_returns = np.array(aligned)
    except Exception:
        benchmark_returns = None
        print("  [警告] 无法加载基准数据")

    return generate_visual_report(returns, benchmark_returns, dates, output_dir)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', type=str, default=None,
                        help='daily_portfolio.csv 路径')
    parser.add_argument('--output', type=str, default=None)
    parser.add_argument('--benchmark', type=str, default='hs300')
    args = parser.parse_args()

    run_from_engine(args.csv, args.benchmark, args.output)
