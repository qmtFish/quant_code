"""
归因分析模块：Brinson 归因 + 因子归因。

提供:
  - Brinson归因：将超额收益分解为配置效应 + 选股效应 + 交叉效应
  - 因子归因：将组合收益分解为各因子暴露的贡献
  - 行业归因：按行业分解收益来源
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────
# Brinson 归因
# ─────────────────────────────────────────────────────────────

@dataclass
class BrinsonResult:
    """Brinson归因结果"""
    total_excess: float = 0.0
    allocation_effect: float = 0.0   # 配置效应
    selection_effect: float = 0.0    # 选股效应
    interaction_effect: float = 0.0  # 交叉效应
    industry_detail: pd.DataFrame = field(default_factory=pd.DataFrame)

    def summary(self) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("  Brinson 归因分析")
        lines.append("=" * 60)
        lines.append(f"  超额收益:          {self.total_excess:>+8.4f}")
        lines.append(f"  配置效应(行业):    {self.allocation_effect:>+8.4f}")
        lines.append(f"  选股效应(行业内):  {self.selection_effect:>+8.4f}")
        lines.append(f"  交叉效应:          {self.interaction_effect:>+8.4f}")
        lines.append(f"  合计:              {self.allocation_effect + self.selection_effect + self.interaction_effect:>+8.4f}")
        lines.append("")
        lines.append("  行业明细:")
        lines.append(f"  {'行业':>12s} {'配置效应':>10s} {'选股效应':>10s} {'交叉效应':>10s} {'合计':>10s}")
        if not self.industry_detail.empty:
            for _, row in self.industry_detail.iterrows():
                lines.append(f"  {row['industry']:>12s} "
                             f"{row['allocation']:>+10.4f} "
                             f"{row['selection']:>+10.4f} "
                             f"{row['interaction']:>+10.4f} "
                             f"{row['total']:>+10.4f}")
        lines.append("=" * 60)
        return '\n'.join(lines)


def brinson_attribution(
    portfolio_weights: Dict[str, Dict[str, float]],
    portfolio_returns: Dict[str, Dict[str, float]],
    benchmark_weights: Dict[str, Dict[str, float]],
    benchmark_returns: Dict[str, Dict[str, float]],
    industry_map: Dict[str, List[str]],
    periods: List = None,
) -> BrinsonResult:
    """
    Brinson 归因分析。

    将超额收益分解为:
      - 配置效应：行业权重偏离基准的贡献
      - 选股效应：行业内选股偏离基准的贡献
      - 交叉效应：配置与选股的交互

    Args:
        portfolio_weights: {行业: {股票: 权重}} 或 {期: {行业: {股票: 权重}}}
        portfolio_returns: {行业: {股票: 收益率}}
        benchmark_weights: {行业: {股票: 权重}}
        benchmark_returns: {行业: {股票: 收益率}}
        industry_map: {行业: [股票列表]}
        periods: 期数列表（如果有多个时期）

    Returns:
        BrinsonResult 对象
    """
    # 单期 vs 多期处理
    if periods is not None:
        results = []
        for p in periods:
            pw = portfolio_weights.get(p, {})
            pr = portfolio_returns.get(p, {})
            bw = benchmark_weights.get(p, {})
            br = benchmark_returns.get(p, {})
            r = brinson_attribution(pw, pr, bw, br, industry_map)
            results.append(r)
        # 合并（多期累加）
        total = BrinsonResult()
        for r in results:
            total.total_excess += r.total_excess
            total.allocation_effect += r.allocation_effect
            total.selection_effect += r.selection_effect
            total.interaction_effect += r.interaction_effect
        return total

    # 单期归因
    industries = sorted(industry_map.keys())
    detail_rows = []

    for ind in industries:
        stocks = industry_map[ind]

        # 组合在该行业的权重
        pw_ind = sum(portfolio_weights.get(s, 0) for s in stocks)
        # 基准在该行业的权重
        bw_ind = sum(benchmark_weights.get(s, 0) for s in stocks)

        # 组合在该行业的收益率（等权近似）
        pr_ind = 0
        cnt = 0
        for s in stocks:
            if s in portfolio_returns:
                pr_ind += portfolio_returns[s]
                cnt += 1
        pr_ind = pr_ind / cnt if cnt > 0 else 0

        # 基准在该行业的收益率
        br_ind = 0
        cnt = 0
        for s in stocks:
            if s in benchmark_returns:
                br_ind += benchmark_returns[s]
                cnt += 1
        br_ind = br_ind / cnt if cnt > 0 else 0

        # Brinson 三效应
        allocation = (pw_ind - bw_ind) * (br_ind - br_total_ret) if 'br_total_ret' in dir() else 0
        selection = bw_ind * (pr_ind - br_ind)
        interaction = (pw_ind - bw_ind) * (pr_ind - br_ind)

        # 我们需要基准总收益
        detail_rows.append({
            'industry': ind,
            'allocation': allocation,
            'selection': selection,
            'interaction': interaction,
            'total': allocation + selection + interaction,
        })

    # 计算基准总收益
    bench_total_ret = sum(benchmark_weights.get(s, 0) * benchmark_returns.get(s, 0)
                           for s in benchmark_weights)
    port_total_ret = sum(portfolio_weights.get(s, 0) * portfolio_returns.get(s, 0)
                          for s in portfolio_weights)

    # 重新计算配置效应（需要基准总收益）
    for row in detail_rows:
        ind = row['industry']
        pw_ind = sum(portfolio_weights.get(s, 0) for s in industry_map[ind])
        bw_ind = sum(benchmark_weights.get(s, 0) for s in industry_map[ind])

        pr_ind = np.mean([portfolio_returns.get(s, 0) for s in industry_map[ind]])
        br_ind = np.mean([benchmark_returns.get(s, 0) for s in industry_map[ind]])

        row['allocation'] = (pw_ind - bw_ind) * (br_ind - bench_total_ret)
        row['selection'] = bw_ind * (pr_ind - br_ind)
        row['interaction'] = (pw_ind - bw_ind) * (pr_ind - br_ind)
        row['total'] = row['allocation'] + row['selection'] + row['interaction']

    df = pd.DataFrame(detail_rows)

    result = BrinsonResult(
        total_excess=port_total_ret - bench_total_ret,
        allocation_effect=df['allocation'].sum(),
        selection_effect=df['selection'].sum(),
        interaction_effect=df['interaction'].sum(),
        industry_detail=df,
    )

    return result


# ─────────────────────────────────────────────────────────────
# 因子归因
# ─────────────────────────────────────────────────────────────

@dataclass
class FactorAttributionResult:
    """因子归因结果"""
    total_return: float = 0.0
    factor_contributions: Dict[str, float] = field(default_factory=dict)
    specific_return: float = 0.0  # 残差收益（无法被因子解释的部分）
    r_squared: float = 0.0        # 拟合优度

    def summary(self) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("  因子归因分析")
        lines.append("=" * 60)
        lines.append(f"  组合收益:          {self.total_return:>+8.4f}")
        lines.append(f"  因子解释收益:      {sum(self.factor_contributions.values()):>+8.4f}")
        lines.append(f"  残差收益:          {self.specific_return:>+8.4f}")
        lines.append(f"  R²:                {self.r_squared:.4f}")
        lines.append("")
        lines.append(f"  {'因子':>20s} {'贡献':>10s}")
        for factor, contrib in sorted(self.factor_contributions.items(),
                                       key=lambda x: abs(x[1]), reverse=True):
            lines.append(f"  {factor:>20s} {contrib:>+10.4f}")
        lines.append("=" * 60)
        return '\n'.join(lines)


def factor_attribution(
    factor_exposures: Dict[str, Dict[str, float]],
    factor_returns: Dict[str, float],
    stock_returns: Dict[str, float],
    stock_weights: Dict[str, float],
) -> FactorAttributionResult:
    """
    因子归因分析。

    将组合收益分解为各因子的贡献。

    Args:
        factor_exposures: {因子: {股票: 暴露度}}
        factor_returns: {因子: 收益率}
        stock_returns: {股票: 收益率}
        stock_weights: {股票: 权重}

    Returns:
        FactorAttributionResult
    """
    factors = list(factor_exposures.keys())
    stocks = list(stock_weights.keys())

    # 组合因子暴露（加权平均）
    port_exposure = {}
    for f in factors:
        port_exposure[f] = sum(
            stock_weights.get(s, 0) * factor_exposures[f].get(s, 0)
            for s in stocks
        )

    # 组合收益
    port_ret = sum(stock_weights.get(s, 0) * stock_returns.get(s, 0) for s in stocks)

    # 因子贡献
    factor_contrib = {}
    for f in factors:
        factor_contrib[f] = port_exposure[f] * factor_returns.get(f, 0)

    # 残差（总收益 - 因子解释收益）
    explained = sum(factor_contrib.values())
    specific = port_ret - explained

    # 计算 R²
    # 用个股收益与因子预测值做回归
    if len(stocks) > len(factors) + 1:
        X = np.array([[factor_exposures[f].get(s, 0) for f in factors] for s in stocks])
        y = np.array([stock_returns.get(s, 0) for s in stocks])
        w = np.array([stock_weights.get(s, 0) for s in stocks])

        # 加权回归
        Xw = X * w[:, np.newaxis]
        yw = y * w
        try:
            beta = np.linalg.lstsq(Xw, yw, rcond=None)[0]
            y_pred = X @ beta
            ss_res = np.sum(w * (y - y_pred) ** 2)
            ss_tot = np.sum(w * (y - np.average(y, weights=w)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        except Exception:
            r2 = 0
    else:
        r2 = 0

    return FactorAttributionResult(
        total_return=port_ret,
        factor_contributions=factor_contrib,
        specific_return=specific,
        r_squared=r2,
    )


# ─────────────────────────────────────────────────────────────
# 行业归因
# ─────────────────────────────────────────────────────────────

def industry_attribution(
    stock_returns: Dict[str, float],
    stock_weights: Dict[str, float],
    industry_map: Dict[str, List[str]],
) -> pd.DataFrame:
    """
    按行业分解收益来源。

    Returns:
        DataFrame with columns: [行业, 权重, 收益, 贡献, 超额(相对等权)]
    """
    rows = []
    total_weight = sum(stock_weights.values())

    for ind, stocks in industry_map.items():
        ind_weight = sum(stock_weights.get(s, 0) for s in stocks)
        ind_ret = np.mean([stock_returns.get(s, 0) for s in stocks]) if stocks else 0
        contribution = ind_weight * ind_ret
        rows.append({
            '行业': ind,
            '权重': ind_weight / total_weight if total_weight > 0 else 0,
            '收益': ind_ret,
            '贡献': contribution,
        })

    df = pd.DataFrame(rows).sort_values('贡献', ascending=False)
    df['贡献占比'] = df['贡献'] / df['贡献'].sum() if df['贡献'].sum() != 0 else 0
    return df
