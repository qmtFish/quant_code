"""
优化器模块：权重分配与约束处理。

提供:
  - equal_weight: 等权（带约束）
  - score_weighted: 评分加权
  - mean_variance: 均值方差优化（最大化评分 - 风险惩罚）
  - risk_parity: 风险平价
  - impose_constraints: 约束后处理
"""
from __future__ import annotations
from typing import Dict, List, Optional, Callable
import numpy as np
import pandas as pd
from scipy.optimize import minimize


# ─────────────────────────────────────────────────────────────
# 约束工具箱
# ─────────────────────────────────────────────────────────────

def impose_constraints(weights: np.ndarray,
                        max_weight: float = 0.10,
                        min_weight: float = 0.0,
                        industry_map: Dict[str, List[int]] = None,
                        max_industry_weight: float = 0.25) -> np.ndarray:
    """
    对原始权重施加约束。

    Args:
        weights: 原始权重向量 (n,)
        max_weight: 个股权重上限
        min_weight: 个股权重下限
        industry_map: {行业名: [该行业股票在 weights 中的索引]}
        max_industry_weight: 行业权重上限

    Returns:
        约束后权重向量（满仓，和为1）
    """
    w = np.asarray(weights, dtype=float).copy()
    n = len(w)

    # 负权重归零
    w[w < 0] = 0.0

    # 如果全为0，等权分配
    if w.sum() <= 0:
        w = np.ones(n) / n

    # 归一化
    w = w / w.sum()

    # 迭代处理上限约束
    for _ in range(20):
        capped = False

        # 个股上限
        over_max = w > max_weight
        if over_max.any():
            excess = w[over_max].sum() - max_weight * over_max.sum()
            w[over_max] = max_weight
            # 多余权重分配到其他股票
            under = ~over_max
            if under.any() and excess > 0:
                under_sum = w[under].sum()
                if under_sum > 0:
                    w[under] += excess * w[under] / under_sum
                else:
                    w[under] = excess / under.sum()
            capped = True

        # 行业上限
        if industry_map:
            for ind, idx_list in industry_map.items():
                ind_w = w[idx_list].sum()
                if ind_w > max_industry_weight:
                    scale = max_industry_weight / ind_w
                    w[idx_list] *= scale
                    excess = ind_w - max_industry_weight
                    other = [i for i in range(n) if i not in idx_list]
                    if other and excess > 0:
                        other_sum = w[other].sum()
                        if other_sum > 0:
                            w[other] += excess * w[other] / other_sum
                        else:
                            w[other] = excess / len(other)
                    capped = True

        if not capped:
            break

    # 最小值约束
    w[w < min_weight] = min_weight
    w = w / w.sum()

    return w


# ─────────────────────────────────────────────────────────────
# 等权分配
# ─────────────────────────────────────────────────────────────

def equal_weight(stocks: List[str],
                 scores: Optional[np.ndarray] = None,
                 max_weight: float = 0.10,
                 industry_map: Dict[str, List[int]] = None) -> Dict[str, float]:
    """等权分配"""
    n = len(stocks)
    if n == 0:
        return {}
    w = np.ones(n) / n
    w = impose_constraints(w, max_weight=max_weight, industry_map=industry_map)
    return {stock: float(w[i]) for i, stock in enumerate(stocks)}


# ─────────────────────────────────────────────────────────────
# 评分加权
# ─────────────────────────────────────────────────────────────

def score_weighted(stocks: List[str],
                   scores: np.ndarray,
                   power: float = 1.0,
                   max_weight: float = 0.10,
                   min_score: float = -1.0,
                   industry_map: Dict[str, List[int]] = None) -> Dict[str, float]:
    """
    评分加权分配。

    权重 ∝ score^power (仅保留 score > min_score 的股票)
    """
    scores = np.asarray(scores, dtype=float)
    # 过滤
    valid = scores > min_score
    if not valid.any():
        return {}

    scores = scores[valid]
    stocks = [s for i, s in enumerate(stocks) if valid[i]]

    # 平移使最小值为0（如果所有分数相等则直接用等权）
    min_score_val = scores.min()
    scores = scores - min_score_val
    if scores.sum() <= 1e-12:
        return equal_weight(stocks, max_weight=max_weight, industry_map=industry_map)

    scores = scores ** power
    w = scores / scores.sum()
    w = impose_constraints(w, max_weight=max_weight, industry_map=industry_map)
    return {stock: float(w[i]) for i, stock in enumerate(stocks)}


# ─────────────────────────────────────────────────────────────
# 均值方差优化
# ─────────────────────────────────────────────────────────────

def mean_variance(stocks: List[str],
                  expected_returns: np.ndarray,
                  cov_matrix: np.ndarray,
                  risk_aversion: float = 1.0,
                  max_weight: float = 0.10,
                  min_weight: float = 0.0,
                  industry_map: Dict[str, List[int]] = None,
                  max_industry_weight: float = 0.25) -> Dict[str, float]:
    """
    均值方差优化：最大化 expected_ret - 0.5 * risk_aversion * variance。

    适用于有协方差矩阵估计的场景。
    """
    n = len(stocks)
    if n == 0:
        return {}
    if cov_matrix.shape != (n, n):
        # 如果没有协方差矩阵，回退到评分加权
        return score_weighted(stocks, expected_returns, max_weight=max_weight)

    expected = np.asarray(expected_returns, dtype=float)
    cov = np.asarray(cov_matrix, dtype=float)

    def objective(w):
        ret = w @ expected
        risk = w @ cov @ w
        return -(ret - 0.5 * risk_aversion * risk)

    # 约束：满仓
    constraints = [{'type': 'eq', 'fun': lambda w: w.sum() - 1.0}]
    bounds = [(min_weight, max_weight)] * n

    # 行业约束
    if industry_map:
        for ind, idx_list in industry_map.items():
            constraints.append({
                'type': 'ineq',
                'fun': lambda w, idx=idx_list: max_industry_weight - w[idx].sum(),
            })

    # 初始值：评分加权
    x0 = np.maximum(expected, 0)
    if x0.sum() <= 0:
        x0 = np.ones(n) / n
    else:
        x0 = x0 / x0.sum()

    try:
        result = minimize(objective, x0, method='SLSQP', bounds=bounds,
                           constraints=constraints, options={'ftol': 1e-8, 'maxiter': 200})
        w = result.x if result.success else x0
        w = np.maximum(w, 0)
        w = w / w.sum()
    except Exception:
        w = x0

    return {stock: float(w[i]) for i, stock in enumerate(stocks)}


# ─────────────────────────────────────────────────────────────
# 风险平价（Risk Parity）
# ─────────────────────────────────────────────────────────────

def risk_parity(stocks: List[str],
                cov_matrix: np.ndarray,
                max_weight: float = 0.10,
                industry_map: Dict[str, List[int]] = None,
                max_industry_weight: float = 0.25) -> Dict[str, float]:
    """
    风险平价：使每个成分对组合的风险贡献相等。

    Args:
        stocks: 股票列表
        cov_matrix: 协方差矩阵 (n x n)
        max_weight: 个股权重上限
    """
    n = len(stocks)
    if n == 0:
        return {}
    if cov_matrix.shape != (n, n):
        return equal_weight(stocks, max_weight=max_weight, industry_map=industry_map)

    cov = np.asarray(cov_matrix, dtype=float)

    def risk_contribution(w):
        """计算每个成分的风险贡献"""
        port_var = w @ cov @ w
        if port_var <= 0:
            return np.ones(n) / n
        marginal = cov @ w
        rc = w * marginal / np.sqrt(port_var)
        return rc

    def objective(w):
        rc = risk_contribution(w)
        target = rc.mean()
        return np.sum((rc - target) ** 2)

    constraints = [{'type': 'eq', 'fun': lambda w: w.sum() - 1.0}]
    bounds = [(0.0, max_weight)] * n

    if industry_map:
        for ind, idx_list in industry_map.items():
            constraints.append({
                'type': 'ineq',
                'fun': lambda w, idx=idx_list: max_industry_weight - w[idx].sum(),
            })

    x0 = np.ones(n) / n
    try:
        result = minimize(objective, x0, method='SLSQP', bounds=bounds,
                           constraints=constraints,
                           options={'ftol': 1e-8, 'maxiter': 500})
        w = result.x if result.success else x0
        w = np.maximum(w, 0)
        w = w / w.sum()
    except Exception:
        w = x0

    return {stock: float(w[i]) for i, stock in enumerate(stocks)}


# ─────────────────────────────────────────────────────────────
# 组合优化器（统一接口）
# ─────────────────────────────────────────────────────────────

def optimize(method: str = 'equal',
             stocks: List[str] = None,
             scores: np.ndarray = None,
             cov_matrix: np.ndarray = None,
             max_weight: float = 0.10,
             industry_map: Dict[str, List[int]] = None,
             **kwargs) -> Dict[str, float]:
    """
    统一优化接口。

    Args:
        method: 'equal' | 'score' | 'mean_variance' | 'risk_parity'
        stocks: 股票代码列表
        scores: 评分/预期收益 (n,)
        cov_matrix: 协方差矩阵 (n x n)
        max_weight: 个股权重上限
        industry_map: {行业名: [索引列表]}

    Returns:
        {股票代码: 权重}
    """
    if method == 'equal':
        return equal_weight(stocks, max_weight=max_weight, industry_map=industry_map)
    elif method == 'score':
        return score_weighted(stocks, scores, max_weight=max_weight,
                               industry_map=industry_map, **kwargs)
    elif method == 'mean_variance':
        return mean_variance(stocks, scores, cov_matrix,
                              max_weight=max_weight, industry_map=industry_map, **kwargs)
    elif method == 'risk_parity':
        return risk_parity(stocks, cov_matrix,
                            max_weight=max_weight, industry_map=industry_map, **kwargs)
    else:
        raise ValueError(f"Unknown optimizer method: {method}")
