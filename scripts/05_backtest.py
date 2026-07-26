"""
05 — 事件驱动回测引擎（聚宽风格）。

替代旧的分组回测，提供:
  - 事件驱动架构（initialize → before_trading_start → handle_data）
  - 真实成交模拟（费用、滑点、停牌过滤）
  - 持仓管理（逐日盯市、仓位权重）
  - 绩效报告（全套指标 + 基准对比）
  - 聚宽风格策略编写接口

用法:
    python 05_backtest.py --strategy my_strategy.py --start 2024-01-01 --end 2026-06-12
"""
from __future__ import annotations
import sys, os, time, json, importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from datetime import date, datetime
import numpy as np
import pandas as pd

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.config import (INITIAL_CASH, BENCHMARK_CODE,
                               COMMISSION_RATE, MIN_COMMISSION,
                               STAMP_TAX_RATE, TRANSFER_FEE_RATE,
                               SLIPPAGE_MODE, BASE_SLIPPAGE,
                               ORDER_VOLUME_RATIO, MIN_ORDER_VALUE,
                               MAX_STOCK_WEIGHT, REBALANCE_FREQ,
                               TOP_K, WEIGHT_FILE,
                               RESULT_DIR, DATA_DIR)
from pipeline.core.context import Context, Portfolio, Position, Order
from pipeline.core.broker import Broker, CommissionModel, SlippageModel
from pipeline.core.scheduler import Scheduler
from pipeline.core.data_loader import load_daily, load_financial, load_all_index, load_industry
from pipeline.metrics.performance import PerformanceMetrics


# ═══════════════════════════════════════════════════════════════
# BacktestEngine
# ═══════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    事件驱动回测引擎。

    使用示例:
        engine = BacktestEngine(
            strategy_class=MyStrategy,
            initial_cash=10_000_000,
            start_date='2024-01-01',
            end_date='2026-06-12',
        )
        engine.run()
    """

    def __init__(self,
                 strategy_class: type,
                 initial_cash: float = None,
                 start_date: str = None,
                 end_date: str = None,
                 benchmark_code: str = None,
                 commission_rate: float = None,
                 base_slippage: float = None,
                 max_stock_weight: float = None,
                 min_order_value: float = None,
                 result_dir: str = None):
        self.strategy_class = strategy_class
        self.initial_cash = initial_cash or INITIAL_CASH
        self.start_date = start_date or '2024-01-01'
        self.end_date = end_date or '2026-06-12'
        self.benchmark_code = benchmark_code or BENCHMARK_CODE
        self.commission_rate = commission_rate or COMMISSION_RATE
        self.base_slippage = base_slippage or BASE_SLIPPAGE
        self.max_stock_weight = max_stock_weight or MAX_STOCK_WEIGHT
        self.min_order_value = min_order_value or MIN_ORDER_VALUE
        self.result_dir = result_dir or str(RESULT_DIR / 'portfolios')
        Path(self.result_dir).mkdir(parents=True, exist_ok=True)

        # 运行时状态
        self.context: Context = None
        self.broker: Broker = None
        self.scheduler: Scheduler = None
        self.data_api = None
        self.strategy = None

        # 数据缓存
        self._daily: pd.DataFrame = None
        self._financial: pd.DataFrame = None
        self._index: Dict[str, pd.DataFrame] = {}
        self._industry: pd.DataFrame = None
        self._all_trading_dates: List[pd.Timestamp] = []

        # 基准收益率
        self._benchmark_returns: np.ndarray = None

    def _load_data(self):
        """加载回测所需的所有数据"""
        print("=" * 55)
        print("  加载数据...")
        print("=" * 55)

        try:
            self._daily = load_daily(self.start_date, self.end_date)
            print(f"  [日线] {len(self._daily)} 行, "
                  f"{self._daily.index.get_level_values('date').nunique()} 交易日")
        except FileNotFoundError:
            print("  [日线] 未找到，请先运行数据下载")
            raise

        try:
            self._financial = load_financial()
            print(f"  [财务] {len(self._financial)} 行")
        except FileNotFoundError:
            print("  [财务] 未找到")
            self._financial = pd.DataFrame()

        try:
            self._index = load_all_index()
            for k, v in self._index.items():
                print(f"  [指数] {k}: {len(v)} 行")
        except FileNotFoundError:
            print("  [指数] 未找到")

        try:
            self._industry = load_industry()
            print(f"  [行业] {len(self._industry)} 只股票")
        except FileNotFoundError:
            self._industry = pd.DataFrame()
            print("  [行业] 未找到")

        # 交易日列表
        all_dates = sorted(self._daily.index.get_level_values('date').unique())
        self._all_trading_dates = [
            d for d in all_dates
            if self.start_date <= str(d.date()) <= self.end_date
        ]
        print(f"  [回测期] {self._all_trading_dates[0].date()} ~ "
              f"{self._all_trading_dates[-1].date()} "
              f"({len(self._all_trading_dates)} 个交易日)")

    def _init_context(self):
        """初始化 Context 和 Broker"""
        commission_model = CommissionModel(
            commission_rate=self.commission_rate,
            min_commission=MIN_COMMISSION,
            stamp_tax_rate=STAMP_TAX_RATE,
            transfer_fee_rate=TRANSFER_FEE_RATE,
        )
        slippage_model = SlippageModel(
            mode=SLIPPAGE_MODE,
            base_slippage=self.base_slippage,
        )
        self.broker = Broker(
            initial_cash=self.initial_cash,
            commission_model=commission_model,
            slippage_model=slippage_model,
            order_volume_ratio=ORDER_VOLUME_RATIO,
        )
        self.context = Context(
            initial_cash=self.initial_cash,
            benchmark_code=self.benchmark_code,
        )

        # 挂载数据引用
        self.context._daily = self._daily
        self.context._financial = self._financial
        self.context._index = self._index
        self.context._industry = self._industry

        # 注入行业映射
        if not self._industry.empty and 'industry_code' in self._industry.columns:
            industry_stocks = {}
            for code, row in self._industry.iterrows():
                ind = row['industry_code']
                if ind not in industry_stocks:
                    industry_stocks[ind] = []
                industry_stocks[ind].append(code)
            self.context._industry_stocks = industry_stocks
            self.context._all_industries = sorted(industry_stocks.keys())

        # 可用股票列表
        first_date = self._all_trading_dates[0]
        if first_date in self._daily.index:
            self.context._all_stocks = self._daily.loc[first_date].index.tolist()

        # 注入完整日线数据用于涨跌停检测
        self.broker.set_full_daily(self._daily)

        # 挂载 Broker 和引擎引用（供策略访问）
        self.context._broker = self.broker
        self.context._engine = self

        # 调度器
        self.scheduler = Scheduler()

    def _get_prices_on_date(self, date: pd.Timestamp) -> Dict[str, float]:
        """获取当日所有股票收盘价"""
        if date not in self._daily.index:
            return {}
        today_data = self._daily.loc[date]
        if isinstance(today_data, pd.Series):
            return {today_data.name: float(today_data.get('close', 0))}
        return {code: float(row['close']) for code, row in today_data.iterrows()}

    def _calc_benchmark_returns(self) -> np.ndarray:
        """计算基准指数的每日收益率"""
        idx = self._index.get(self.benchmark_code)
        if idx is None or idx.empty:
            return np.zeros(len(self.context.portfolio.returns))

        idx = idx.sort_index()
        close = idx['close'].values
        ret = close[1:] / close[:-1] - 1
        ret = np.concatenate([np.array([0.0]), ret])

        # 对齐回测期
        bt_dates = self.context.portfolio.dates
        if len(bt_dates) <= 1:
            return np.zeros(len(self.context.portfolio.returns))

        # 简单对齐：取对应的指数日收益
        aligned = []
        idx_dates = idx.index.tolist()
        price_map = {d.date(): close[i] for i, d in enumerate(idx_dates)}
        for i, d in enumerate(bt_dates):
            if i == 0:
                aligned.append(0.0)
            else:
                prev_price = price_map.get(bt_dates[i-1])
                cur_price = price_map.get(d)
                if prev_price and cur_price and prev_price > 0:
                    aligned.append(cur_price / prev_price - 1)
                else:
                    aligned.append(0.0)
        return np.array(aligned, dtype=float)

    def run(self) -> dict:
        """执行回测"""
        t0 = time.time()

        # 1. 加载数据
        self._load_data()

        # 2. 初始化上下文
        self._init_context()

        # 3. 初始化策略
        self.strategy = self.strategy_class()
        print(f"\n  [策略] {self.strategy.name}")

        # 4. 调用策略 initialize
        self.strategy.initialize(self.context)
        self.scheduler.register_tasks(self.context._scheduled_tasks)

        print(f"\n  回测期: {self._all_trading_dates[0].date()} ~ "
              f"{self._all_trading_dates[-1].date()}")
        print(f"  初始资金: {self.initial_cash:,.0f}")
        print(f"  佣金: {self.commission_rate*10000:.1f}‰ + 印{STAMP_TAX_RATE*1000:.1f}‰")
        print(f"  滑点: {self.base_slippage*100:.1f}%")
        print(f"  单股上限: {self.max_stock_weight*100:.0f}%")
        print("=" * 55)

        # 5. 事件循环
        n_dates = len(self._all_trading_dates)
        report_interval = max(1, n_dates // 20)  # 约每5%进度报告一次

        for i, dt in enumerate(self._all_trading_dates):
            self.context.current_dt = dt
            self.context.previous_date = dt.date()

            # ── 5a. 注入行情快照到 Broker ──
            if dt in self._daily.index:
                today_data = self._daily.loc[dt]
                if isinstance(today_data, pd.DataFrame):
                    self.broker.set_daily_snapshot(dt.date(), today_data)

            # ── 5b. 执行开盘前调度任务 ──
            due_tasks = self.scheduler.get_due_tasks(dt, self.context.previous_date)
            for task_func in due_tasks:
                if task_func.__name__ == 'before_trading_start':
                    self.broker.commission = CommissionModel(
                        commission_rate=self.commission_rate,
                        min_commission=MIN_COMMISSION,
                        stamp_tax_rate=STAMP_TAX_RATE,
                        transfer_fee_rate=TRANSFER_FEE_RATE,
                    )
                    self.strategy.before_trading_start(self.context)

            # ── 5c. 执行 handle_data（交易逻辑） ──
            self.strategy.handle_data(self.context, None)

            # ── 5d. 逐日盯市 ──
            prices = self._get_prices_on_date(dt)
            self.context.portfolio.mark_to_market(prices)

            # ── 5e. 记录每日快照 ──
            self.context.portfolio.snapshot(dt.date())

            # ── 进度报告 ──
            if (i + 1) % report_interval == 0 or i == n_dates - 1:
                pos_count = self.context.portfolio.position_count()
                val = self.context.portfolio.total_value
                ret = (val / self.initial_cash - 1) * 100
                print(f"  [{i+1}/{n_dates}] {dt.date()}  "
                      f"资产={val:>12,.0f} 收益={ret:>+6.2f}% 持仓={pos_count}只")

        elapsed = time.time() - t0

        # ════════════════════════════════════════════
        # 6. 生成绩效报告
        # ════════════════════════════════════════════
        portfolio_returns = np.array(self.context.portfolio.returns, dtype=float)
        self._benchmark_returns = self._calc_benchmark_returns()

        metrics = PerformanceMetrics(
            daily_returns=portfolio_returns,
            benchmark_returns=self._benchmark_returns,
            rf_annual=0.02,
            trading_days_per_year=252,
        )

        report = metrics.full_report()
        print(f"\n{report}")

        # 7. 保存结果
        summary = self.context.portfolio.summary()
        summary.update(metrics.to_dict())
        summary.update({
            'start_date': str(self._all_trading_dates[0].date()),
            'end_date': str(self._all_trading_dates[-1].date()),
            'elapsed_sec': round(elapsed, 1),
            'strategy': self.strategy.name,
        })

        # 保存 JSON 摘要
        out_json = Path(self.result_dir) / 'backtest_summary.json'
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n  摘要: {out_json}")

        # 保存持仓快照
        out_port = Path(self.result_dir) / 'daily_portfolio.csv'
        port_records = []
        for i, d in enumerate(self.context.portfolio.dates):
            port_records.append({
                'date': d,
                'total_value': self.context.portfolio.daily_values[i],
                'cash': self.context.portfolio.daily_cash[i],
                'return': portfolio_returns[i] if i < len(portfolio_returns) else 0.0,
            })
        pd.DataFrame(port_records).to_csv(out_port, index=False)
        print(f"  每日资产: {out_port}")

        # 保存交易记录
        out_orders = Path(self.result_dir) / 'orders.csv'
        order_records = []
        for o in self.context.portfolio.orders:
            order_records.append({
                'date': o.date,
                'code': o.code,
                'side': o.side,
                'shares': o.shares,
                'price': o.price,
                'value': o.value,
                'commission': o.commission,
                'tax': o.tax,
            })
        if order_records:
            pd.DataFrame(order_records).to_csv(out_orders, index=False)
            print(f"  交易记录: {out_orders} ({len(order_records)} 笔)")

        # 8. 生成可视化报告
        try:
            from pipeline.metrics.visualization import generate_visual_report
            generate_visual_report(
                returns=portfolio_returns,
                benchmark_returns=self._benchmark_returns,
                dates=self.context.portfolio.dates,
                output_dir=str(RESULT_DIR / 'reports'),
                prefix='backtest',
            )
        except Exception as e:
            print(f"  [可视化] 生成失败: {e}")

        print(f"\n  回测完成, 耗时 {elapsed:.1f}s\n")
        return summary


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

def run(strategy_path: str = None, start: str = None, end: str = None,
        initial_cash: float = None, top_k: int = None,
        max_weight: float = None):
    """从命令行运行回测"""
    if strategy_path is None:
        # 默认尝试加载 example_strategy.py
        strategy_path = str(PROJECT_ROOT / 'example_strategy.py')

    # 动态加载策略模块
    path = Path(strategy_path)
    if not path.exists():
        print(f"  策略文件不存在: {path}")
        return

    spec = importlib.util.spec_from_file_location('strategy_mod', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # 查找策略类（继承 Strategy 的子类）
    strategy_class = None
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, type) and issubclass(obj, mod.Strategy) and obj is not mod.Strategy:
            strategy_class = obj
            break

    if strategy_class is None:
        print("  策略文件中未找到 Strategy 子类")
        return

    engine = BacktestEngine(
        strategy_class=strategy_class,
        initial_cash=initial_cash or INITIAL_CASH,
        start_date=start or '2024-01-01',
        end_date=end or '2026-06-12',
    )

    # 覆盖策略参数
    engine.max_stock_weight = max_weight or MAX_STOCK_WEIGHT

    engine.run()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', type=str, default=None,
                        help='策略文件路径')
    parser.add_argument('--start', type=str, default=None)
    parser.add_argument('--end', type=str, default=None)
    parser.add_argument('--cash', type=float, default=None)
    parser.add_argument('--top-k', type=int, default=None)
    parser.add_argument('--max-weight', type=float, default=None)
    args = parser.parse_args()

    run(
        strategy_path=args.strategy,
        start=args.start,
        end=args.end,
        initial_cash=args.cash,
        top_k=args.top_k,
        max_weight=args.max_weight,
    )
