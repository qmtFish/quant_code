"""
06 — 绩效报告：从回测结果生成可读报告和图表。
"""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from pipeline.config import RESULT_DIR


def load_portfolio(path: str = None) -> pd.DataFrame:
    if path is None:
        path = RESULT_DIR / 'portfolios' / 'portfolio.parquet'
    return pd.read_parquet(str(path))


def load_long_short(path: str = None) -> pd.DataFrame:
    if path is None:
        path = RESULT_DIR / 'portfolios' / 'long_short.parquet'
    return pd.read_parquet(str(path))


def run(port_path: str = None, ls_path: str = None, out_dir: str = None, fig_path: str = None):
    print("=" * 55)
    print("  06 — 绩效报告")
    print("=" * 55)

    if out_dir is None:
        out_dir = str(RESULT_DIR / 'reports')
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    if fig_path is None:
        fig_path = str(Path(out_dir) / 'performance.png')

    portfolio = load_portfolio(port_path)
    ls = load_long_short(ls_path)

    if portfolio.empty:
        print("  无回测数据")
        return

    dates = sorted(portfolio['date'].unique())
    print(f"  回测期: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)} 期)")

    # ========================
    # 计算各项指标
    # ========================
    lines = []
    lines.append("=" * 60)
    lines.append("Backtest Performance Report")
    lines.append("=" * 60)
    lines.append(f"Period: {dates[0].date()} ~ {dates[-1].date()} ({len(dates)} weeks)")
    lines.append("")

    groups = sorted(portfolio['group'].unique())
    lines.append(f"{'Group':>6s} {'Avg Ret':>10s} {'Cum Ret':>10s} {'Win Rate':>10s} {'Sharpe':>8s} {'MaxDD':>10s}")
    lines.append("-" * 60)

    group_metrics = {}
    for g in groups:
        grp = portfolio[portfolio['group'] == g].sort_values('date')
        returns = grp['net_return'].values
        cum = grp['cum_return'].values
        final_cum = cum[-1] - 1
        avg_r = returns.mean()
        win = (returns > 0).mean()
        sharpe = avg_r / returns.std() * np.sqrt(52) if returns.std() > 0 else 0
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        maxdd = dd.min()
        group_metrics[g] = {'avg_ret': avg_r, 'cum': final_cum, 'win': win, 'sharpe': sharpe, 'maxdd': maxdd}
        lines.append(f"{g:>6s} {avg_r:>+10.4f} {final_cum:>+10.4f} {win:>10.2%} {sharpe:>8.2f} {maxdd:>10.2%}")

    # 多空
    if 'long_short' in ls.columns:
        ls_ret = ls['long_short'].values
        ls_cum = ls['cum_ls'].values
        final_ls = ls_cum[-1] - 1
        avg_ls = ls_ret.mean()
        std_ls = ls_ret.std()
        win_ls = (ls_ret > 0).mean()
        sharpe_ls = avg_ls / std_ls * np.sqrt(52) if std_ls > 0 else 0
        t_ls = avg_ls / (std_ls / np.sqrt(len(ls_ret))) if std_ls > 0 else 0
        peak_ls = np.maximum.accumulate(ls_cum)
        dd_ls = (ls_cum - peak_ls) / peak_ls
        maxdd_ls = dd_ls.min()

        lines.append("-" * 60)
        top_g = f'Q{len(groups)}'
        lines.append(f"{top_g}-Q1: {avg_ls:>+10.4f} {final_ls:>+10.4f} {win_ls:>10.2%} {sharpe_ls:>8.2f} {maxdd_ls:>10.2%}")
        lines.append(f"")
        lines.append(f"Additional Metrics:")
        lines.append(f"  LS t-statistic:  {t_ls:.3f}")
        lines.append(f"  LS IC:           {avg_ls:.4f}")

    lines.append("")
    lines.append("=" * 60)

    report = '\n'.join(lines)

    # 写文本报告
    report_path = Path(out_dir) / 'report.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n  报告: {report_path}")

    # 生成图表
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(3, 1, figsize=(14, 10))

        # 1. 各组累计收益
        ax = axes[0]
        for g in groups:
            grp = portfolio[portfolio['group'] == g].sort_values('date')
            ax.plot(grp['date'], grp['cum_return'], label=g, lw=1.0)
        ax.set_title('Group Cumulative Returns', fontsize=12)
        ax.legend(loc='best', fontsize=8)
        ax.axhline(1.0, color='gray', ls='--', lw=0.5)

        # 2. 多空累计收益
        ax = axes[1]
        if 'cum_ls' in ls.columns:
            ax.plot(ls.index, ls['cum_ls'], color='green', lw=1.5, label='Long-Short')
            ax.axhline(1.0, color='gray', ls='--', lw=0.5)
            ax.fill_between(ls.index, 1.0, ls['cum_ls'], alpha=0.15, color='green')
        ax.set_title('Long-Short Cumulative Return', fontsize=12)
        ax.legend()

        # 3. 多空周收益直方图
        ax = axes[2]
        if 'long_short' in ls.columns:
            colors = ['#d62728' if v < 0 else '#2ca02c' for v in ls['long_short']]
            ax.bar(range(len(ls)), ls['long_short'], color=colors, width=0.7)
            ax.axhline(0, color='black', lw=0.5)
            ax.axhline(ls['long_short'].mean(), color='blue', ls='--', lw=0.8,
                       label=f'Mean={ls["long_short"].mean():.4f}')
            ax.set_title('Weekly Long-Short Returns', fontsize=12)
            ax.set_xlabel('Week')
            ax.legend()

        plt.tight_layout()
        plt.savefig(fig_path, dpi=120)
        print(f"  图表: {fig_path}")
    except Exception as e:
        print(f"  图表生成失败: {e}")

    print(report)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port-path', type=str, default=None)
    parser.add_argument('--ls-path', type=str, default=None)
    parser.add_argument('--out-dir', type=str, default=None)
    args = parser.parse_args()
    run(args.port_path, args.ls_path, args.out_dir)
