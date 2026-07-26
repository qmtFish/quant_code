"""
仓位管理模块 —— 独立于模型，负责权重分配和调仓执行。

模型输出: 每个截面的股票评分/排序 (DataFrame[code, score, rank_pct])
仓位管理: 从评分生成目标权重 → 通过 Broker 执行调仓

用法:
    from pipeline.position_manager import PositionManager

    pm = PositionManager(max_weight=0.10, top_k=10)
    weights = pm.generate_weights(scores_df)
    pm.rebalance(context, weights, date)
"""
from __future__ import annotations
from typing import Dict, List, Optional
from datetime import date
import numpy as np
import pandas as pd


class PositionManager:
    """
    仓位管理 —— 从模型评分生成目标权重，并执行调仓。

    Args:
        max_weight: 单只股票最大权重 (默认 0.10 = 10%)
        top_k: 全局最多持仓数 (默认 10)
        min_order_value: 最小调仓金额 (默认 1000)
        min_score: 最低评分阈值 (默认 -1.0)
    """

    def __init__(self,
                 max_weight: float = 0.10,
                 top_k: int = 10,
                 min_order_value: float = 1000.0,
                 min_score: float = -1.0):
        self.max_weight = max_weight
        self.top_k = top_k
        self.min_order_value = min_order_value
        self.min_score = min_score

    # ── 权重生成 ──

    def generate_weights(self, scores_df: pd.DataFrame) -> Dict[str, float]:
        """
        从模型评分生成目标权重。

        Args:
            scores_df: DataFrame[code, score, ...]，按 score 降序排列

        Returns:
            {code: weight} 权重字典，和为 1.0
        """
        if scores_df is None or scores_df.empty:
            return {}

        # 选 Top K（仅保留评分 > min_score 的股票）
        candidates = scores_df[scores_df['score'] > self.min_score].head(self.top_k)
        if candidates.empty:
            return {}

        codes = candidates['code'].tolist()
        n = len(codes)

        # 等权分配 + 单股权重上限约束
        raw_weight = min(1.0 / n, self.max_weight)
        weights = {code: raw_weight for code in codes}

        # 归一化（如果权重总和不足1，多出部分平摊）
        w_sum = sum(weights.values())
        if w_sum > 0:
            weights = {c: v / w_sum for c, v in weights.items()}

        return weights

    # ── 调仓执行 ──

    def rebalance(self,
                  context,
                  target_weights: Dict[str, float],
                  trade_date: date) -> int:
        """
        执行调仓：通过 context._broker 下单。

        Args:
            context: 回测引擎的 Context 对象
            target_weights: {code: weight} 目标权重
            trade_date: 交易日

        Returns:
            成交订单数
        """
        broker = getattr(context, '_broker', None)
        if broker is None:
            print("  [仓位] Broker 不可用，跳过调仓")
            return 0

        prices = self._get_prices(context)
        if not prices:
            print("  [仓位] 无法获取价格，跳过调仓")
            return 0

        trade_count = broker.update_broker(
            context.portfolio,
            target_weights,
            prices,
            trade_date,
            self.min_order_value,
        )
        return trade_count

    # ── 打印仓位报告 ──

    def print_position_report(self, context, selected: List[tuple],
                               weights: Dict[str, float]):
        """
        打印调仓日志。

        Args:
            context: Context 对象
            selected: [(code, score, industry), ...]
            weights: {code: weight}
        """
        total_ret = context.portfolio.total_value / context.portfolio.initial_cash - 1
        pos_count = context.portfolio.position_count()

        print(f"\n  [仓位] {context.current_dt.date()}  | "
              f"持股{pos_count}只 | 收益{total_ret:+.2%}")
        for item in selected[:8]:
            code, score, industry = item
            w = weights.get(code, 0) * 100
            print(f"    {code}  w={w:.1f}%  score={score:+.4f}  industry={industry}")
        if len(selected) > 8:
            print(f"    ... 还有 {len(selected) - 8} 只")

    # ── 内部工具 ──

    @staticmethod
    def _get_prices(context) -> Dict[str, float]:
        """从 Context 的日线数据获取当前收盘价"""
        try:
            current_dt = context.current_dt
            daily = context._daily
            if daily is None or current_dt not in daily.index:
                return {}
            today = daily.loc[current_dt]
            if isinstance(today, pd.Series):
                return {today.name: float(today['close'])}
            return {code: float(row['close']) for code, row in today.iterrows()}
        except Exception:
            return {}
