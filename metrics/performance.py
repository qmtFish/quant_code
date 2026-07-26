"""
全套绩效指标计算 —— 类似聚宽绩效报告。
"""
from typing import List, Optional
import numpy as np
import pandas as pd


def calc_max_drawdown(values: np.ndarray) -> float:
    """计算最大回撤"""
    peak = np.maximum.accumulate(values)
    dd = (values - peak) / peak
    return float(dd.min())


def calc_max_drawdown_from_returns(returns: np.ndarray) -> float:
    """从收益率序列计算最大回撤"""
    cum = (1 + returns).cumprod()
    return calc_max_drawdown(cum)


class PerformanceMetrics:
    """
    全套绩效指标计算。

    用法:
        metrics = PerformanceMetrics(
            daily_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            rf_annual=0.02,
            trading_days_per_year=252
        )
        report = metrics.full_report()
    """

    def __init__(self,
                 daily_returns: np.ndarray,
                 benchmark_returns: Optional[np.ndarray] = None,
                 rf_annual: float = 0.02,
                 trading_days_per_year: int = 252):
        self.returns = np.asarray(daily_returns, dtype=float)
        self.benchmark = np.asarray(benchmark_returns, dtype=float) if benchmark_returns is not None else None
        self.rf_annual = rf_annual
        self.T = trading_days_per_year
        self.rf_period = (1 + rf_annual) ** (1 / self.T) - 1
        self.n = len(self.returns)

    def annual_return(self) -> float:
        """年化收益率"""
        total = (1 + self.returns).prod()
        return float(total ** (self.T / self.n) - 1) if self.n > 0 else 0.0

    def annual_volatility(self) -> float:
        """年化波动率"""
        return float(self.returns.std() * np.sqrt(self.T)) if self.n > 1 else 0.0

    def total_return(self) -> float:
        """累计收益率"""
        return float((1 + self.returns).prod() - 1) if self.n > 0 else 0.0

    def sharpe_ratio(self) -> float:
        """夏普比率"""
        if self.returns.std() < 1e-10 or self.n < 2:
            return 0.0
        excess = self.returns.mean() - self.rf_period
        return float(excess / self.returns.std() * np.sqrt(self.T))

    def sortino_ratio(self) -> float:
        """索提诺比率（仅用下行波动率）"""
        downside = self.returns[self.returns < self.rf_period]
        if len(downside) < 2 or downside.std() < 1e-10:
            return 0.0
        downside_std = downside.std() * np.sqrt(self.T)
        excess = (self.returns.mean() - self.rf_period) * self.T
        return float(excess / downside_std)

    def max_drawdown(self) -> float:
        """最大回撤"""
        return calc_max_drawdown_from_returns(self.returns)

    def calmar_ratio(self) -> float:
        """卡玛比率"""
        mdd = self.max_drawdown()
        if abs(mdd) < 1e-10:
            return 0.0
        return self.annual_return() / abs(mdd)

    def win_rate(self) -> float:
        """胜率"""
        if self.n == 0:
            return 0.0
        return float((self.returns > 0).mean())

    def profit_loss_ratio(self) -> float:
        """盈亏比"""
        wins = self.returns[self.returns > 0]
        losses = self.returns[self.returns < 0]
        if len(losses) == 0:
            return float('inf')
        return float(wins.mean() / abs(losses.mean())) if len(wins) > 0 else 0.0

    # ── 基准相关指标 ──

    def benchmark_return(self) -> float:
        """基准累计收益率"""
        if self.benchmark is None:
            return 0.0
        return float((1 + self.benchmark).prod() - 1)

    def benchmark_annual(self) -> float:
        """基准年化收益率"""
        if self.benchmark is None or self.n == 0:
            return 0.0
        total = (1 + self.benchmark).prod()
        return float(total ** (self.T / self.n) - 1)

    def excess_return(self) -> float:
        """超额累计收益"""
        if self.benchmark is None:
            return 0.0
        return self.total_return() - self.benchmark_return()

    def information_ratio(self) -> float:
        """信息比"""
        if self.benchmark is None or self.n < 2:
            return 0.0
        diff = self.returns - self.benchmark
        if diff.std() < 1e-10:
            return 0.0
        return float(diff.mean() / diff.std() * np.sqrt(self.T))

    def tracking_error(self) -> float:
        """跟踪误差"""
        if self.benchmark is None or self.n < 2:
            return 0.0
        diff = self.returns - self.benchmark
        return float(diff.std() * np.sqrt(self.T))

    def alpha_beta(self) -> tuple:
        """
        计算 Alpha 和 Beta（相对于基准）。
        返回 (alpha_annual, beta)
        """
        if self.benchmark is None or self.n < 2:
            return 0.0, 1.0

        bench_ret = self.benchmark
        port_ret = self.returns
        cov = np.cov(port_ret, bench_ret)
        beta = cov[0, 1] / cov[1, 1] if cov[1, 1] > 1e-10 else 1.0
        alpha_period = port_ret.mean() - self.rf_period - beta * (bench_ret.mean() - self.rf_period)
        alpha_annual = alpha_period * self.T
        return float(alpha_annual), float(beta)

    # ── 其它指标 ──

    def value_at_risk(self, confidence: float = 0.95) -> float:
        """VaR（历史模拟法）"""
        if self.n == 0:
            return 0.0
        return float(np.percentile(self.returns, (1 - confidence) * 100))

    def conditional_var(self, confidence: float = 0.95) -> float:
        """CVaR / Expected Shortfall"""
        var = self.value_at_risk(confidence)
        tail = self.returns[self.returns <= var]
        return float(tail.mean()) if len(tail) > 0 else var

    def turnover_ratio(self, portfolio_weights_history: List[np.ndarray] = None) -> float:
        """平均单边换手率（如果有权重历史）"""
        if portfolio_weights_history is None or len(portfolio_weights_history) < 2:
            return 0.0
        turnovers = []
        for i in range(1, len(portfolio_weights_history)):
            w_prev = portfolio_weights_history[i - 1]
            w_cur = portfolio_weights_history[i]
            turnovers.append(np.abs(w_cur - w_prev).sum() / 2)
        return float(np.mean(turnovers)) if turnovers else 0.0

    # ── 报告 ──

    def to_dict(self) -> dict:
        """返回所有指标字典"""
        alpha, beta = self.alpha_beta()
        d = {
            'total_return': self.total_return(),
            'annual_return': self.annual_return(),
            'annual_volatility': self.annual_volatility(),
            'sharpe_ratio': self.sharpe_ratio(),
            'sortino_ratio': self.sortino_ratio(),
            'max_drawdown': self.max_drawdown(),
            'calmar_ratio': self.calmar_ratio(),
            'win_rate': self.win_rate(),
            'profit_loss_ratio': self.profit_loss_ratio(),
            'value_at_risk_95': self.value_at_risk(0.95),
            'conditional_var_95': self.conditional_var(0.95),
        }
        if self.benchmark is not None:
            d.update({
                'benchmark_return': self.benchmark_return(),
                'benchmark_annual': self.benchmark_annual(),
                'excess_return': self.excess_return(),
                'information_ratio': self.information_ratio(),
                'tracking_error': self.tracking_error(),
                'alpha_annual': alpha,
                'beta': beta,
            })
        return d

    def full_report(self) -> str:
        """生成文本报告"""
        d = self.to_dict()
        lines = []
        lines.append("=" * 62)
        lines.append("  绩效报告 Performance Report")
        lines.append("=" * 62)
        lines.append(f"  回测周期: {self.n} 个交易日")
        lines.append(f"  无风险利率: {self.rf_annual:.1%}")
        lines.append("")

        lines.append("  ┌─────────────────────────────┬────────────┐")
        lines.append(f"  │ {'指标':>25s} │ {'数值':>10s} │")

        items = [
            ('累计收益率', d['total_return'], '+.2%'),
            ('年化收益率', d['annual_return'], '+.2%'),
            ('年化波动率', d['annual_volatility'], '.2%'),
            ('夏普比率', d['sharpe_ratio'], '.2f'),
            ('索提诺比率', d['sortino_ratio'], '.2f'),
            ('最大回撤', d['max_drawdown'], '.2%'),
            ('卡玛比率', d['calmar_ratio'], '.2f'),
            ('胜率', d['win_rate'], '.2%'),
            ('盈亏比', d['profit_loss_ratio'], '.2f'),
            ('VaR(95%)', d['value_at_risk_95'], '.2%'),
            ('CVaR(95%)', d['conditional_var_95'], '.2%'),
        ]

        for label, val, fmt in items:
            lines.append(f"  │ {label:>25s} │ {val:{fmt}} │")

        lines.append("  └─────────────────────────────┴────────────┘")
        lines.append("")

        if self.benchmark is not None:
            lines.append("  ┌─────────────────────────────┬────────────┐")
            lines.append(f"  │ {'基准对比':>25s} │ {'数值':>10s} │")
            bench_items = [
                ('基准累计收益', d['benchmark_return'], '+.2%'),
                ('基准年化收益', d['benchmark_annual'], '+.2%'),
                ('超额收益', d['excess_return'], '+.2%'),
                ('信息比', d['information_ratio'], '.2f'),
                ('跟踪误差', d['tracking_error'], '.2%'),
                ('Alpha(年化)', d['alpha_annual'], '+.2%'),
                ('Beta', d['beta'], '.2f'),
            ]
            for label, val, fmt in bench_items:
                lines.append(f"  │ {label:>25s} │ {val:{fmt}} │")
            lines.append("  └─────────────────────────────┴────────────┘")

        return '\n'.join(lines)
