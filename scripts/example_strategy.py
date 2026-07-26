"""
示例策略 —— 基于统一数据格式的完整回测策略。

架构:
  FactorModel (model.py)       — 训练/预测，只输出排序
  PositionManager (position_manager.py) — 仓位管理
  Strategy (strategy.py)       — 回测引擎接口

数据流:
  CSV 因子数据 → FactorModel.predict() → 评分排序 →
  PositionManager.generate_weights() → 目标权重 →
  PositionManager.rebalance() → Broker 执行调仓

用法:
    python pipeline/scripts/05_backtest.py --strategy example_strategy.py
"""
from __future__ import annotations
from typing import Dict, List
from datetime import date
import pandas as pd

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline.strategy import Strategy, Context, set_benchmark
from pipeline.model import FactorModel, DEFAULT_FACTOR_COLS
from pipeline.position_manager import PositionManager
from pipeline.core.data_loader import load_factor_csv, get_industry_map
from pipeline.config import DATA_PATH, COEF_DIR, MAX_STOCK_WEIGHT, MIN_ORDER_VALUE, TOP_K


class DemoStrategy(Strategy):
    """
    演示策略 —— 周频调仓 + 行业内Z-Score + 全局TopK。

    流程:
      1. initialize: 加载 CSV 数据，初始化 Model 和 PositionManager
      2. handle_data (每周五):
         a. FactorModel.predict(date) → 评分排序
         b. PositionManager.generate_weights() → 目标权重
         c. PositionManager.rebalance() → 调仓
    """

    def initialize(self, context: Context):
        # ── 1. 加载因子数据 ──
        df = load_factor_csv(DATA_PATH)

        # 行业映射（注入到 context 供引擎使用）
        context._industry_stocks = get_industry_map(df)
        context._all_industries = sorted(context._industry_stocks.keys())
        context._all_stocks = df['code'].unique().tolist()
        context.set_param('factor_df', df)

        # ── 2. 初始化模型（只用于预测，不训练） ──
        coef_path = str(COEF_DIR / 'factor_coefficients_6m_rolling.json')
        if not Path(coef_path).exists():
            coef_path = str(sorted(Path(COEF_DIR).glob('*_*m_*.json'))[-1])
        context.set_param('coef_path', coef_path)
        print(f"  [模型] 系数文件: {coef_path}")

        # ── 3. 初始化仓位管理器 ──
        pm = PositionManager(
            max_weight=MAX_STOCK_WEIGHT,
            top_k=TOP_K,
            min_order_value=MIN_ORDER_VALUE,
        )
        context.set_param('pm', pm)

        set_benchmark(context, 'hs300')
        print(f"  [策略] DemoStrategy: top_k={TOP_K}, max_w={MAX_STOCK_WEIGHT}")

    def handle_data(self, context: Context, data):
        current_date = context.current_dt.date()

        # 周频调仓 (每周五)
        if current_date.weekday() != 4:
            return
        week_key = current_date.strftime('%Y-W%W')
        if context.get_param('last_week') == week_key:
            return

        df = context.get_param('factor_df')
        coef_path = context.get_param('coef_path')

        # ── a. 模型预测评分 ──
        model = FactorModel({'factor_cols': DEFAULT_FACTOR_COLS})
        try:
            scores_df = model.predict(
                df=df,
                coef_path=coef_path,
                date=current_date,
                industry_zscore=True,
            )
        except (ValueError, FileNotFoundError) as e:
            print(f"  [{current_date}] 预测失败: {e}")
            return

        # ── b. 仓位管理：评分 → 权重 ──
        pm = context.get_param('pm')
        target_weights = pm.generate_weights(scores_df)
        if not target_weights:
            print(f"  [{current_date}] 无满足条件的股票")
            return

        # ── c. 执行调仓 ──
        trade_count = pm.rebalance(context, target_weights, current_date)

        # ── d. 打印日志 ──
        context.set_param('last_week', week_key)

        selected = []
        for _, row in scores_df.head(TOP_K).iterrows():
            ind = row.get('industry', '')
            selected.append((row['code'], row['score'], ind))
        pm.print_position_report(context, selected, target_weights)
