"""
聚宽风格的数据结构：Context / Portfolio / Position / Order / DataAPI。
"""
from __future__ import annotations
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, date
import numpy as np
import pandas as pd


# ═══════════════════════════════════════════════════════════════
# Order 定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class Order:
    """订单对象"""
    code: str
    shares: float             # 正数买入，负数卖出
    price: float              # 成交价（模拟）
    value: float              # 成交金额
    commission: float         # 佣金
    tax: float                # 印花税
    side: str                 # 'buy' | 'sell'
    status: str = 'filled'    # 'filled' | 'partial' | 'failed'
    filled_shares: float = 0.0
    date: date = None
    order_id: int = 0


# ═══════════════════════════════════════════════════════════════
# Position 定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class Position:
    """持仓对象"""
    code: str
    shares: float = 0.0
    avg_cost: float = 0.0    # 持仓均价（含费用）
    current_price: float = 0.0
    market_value: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0

    def update_price(self, price: float):
        self.current_price = price
        self.market_value = self.shares * price
        self.pnl = self.market_value - self.shares * self.avg_cost
        self.pnl_pct = self.pnl / (self.shares * self.avg_cost + 1e-8) if self.shares > 0 else 0.0


# ═══════════════════════════════════════════════════════════════
# Portfolio 定义
# ═══════════════════════════════════════════════════════════════

class Portfolio:
    """投资组合（盯市后更新）"""

    def __init__(self, initial_cash: float = 1_000_000):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.total_value = initial_cash
        self.positions: Dict[str, Position] = {}
        self.returns: List[float] = []           # 每日收益率序列
        self.daily_values: List[float] = []       # 每日总资产序列
        self.daily_cash: List[float] = []
        self.dates: List[date] = []
        self.orders: List[Order] = []             # 所有历史订单

    def position_count(self) -> int:
        return sum(1 for p in self.positions.values() if p.shares > 1e-8)

    def position_values(self) -> Dict[str, float]:
        return {c: p.market_value for c, p in self.positions.items() if p.shares > 1e-8}

    def position_weights(self) -> pd.Series:
        """返回各持仓占净值的比例"""
        vals = self.position_values()
        if self.total_value > 0 and vals:
            return pd.Series({c: v / self.total_value for c, v in vals.items()})
        return pd.Series(dtype=float)

    def mark_to_market(self, prices: Dict[str, float]):
        """逐日盯市：用当日收盘价更新持仓市值"""
        for code, pos in self.positions.items():
            if code in prices:
                pos.update_price(prices[code])
        # 重新计算总资产
        pos_value = sum(p.market_value for p in self.positions.values())
        self.total_value = self.cash + pos_value

    def snapshot(self, date: date):
        """记录每日快照"""
        self.dates.append(date)
        self.daily_values.append(self.total_value)
        self.daily_cash.append(self.cash)
        if len(self.daily_values) >= 2:
            r = self.daily_values[-1] / self.daily_values[-2] - 1
            self.returns.append(r)
        else:
            self.returns.append(0.0)

    def summary(self) -> dict:
        """返回基础摘要"""
        return {
            'initial_cash': self.initial_cash,
            'final_value': self.total_value,
            'final_cash': self.cash,
            'total_return': self.total_value / self.initial_cash - 1,
            'position_count': self.position_count(),
            'trade_count': len(self.orders),
        }


# ═══════════════════════════════════════════════════════════════
# Context 定义
# ═══════════════════════════════════════════════════════════════

class Context:
    """
    类似聚宽的 context 对象。
    用户可通过 g.xxx 存储全局变量。
    """

    def __init__(self, initial_cash: float = 1_000_000,
                 benchmark_code: str = 'hs300'):
        self.portfolio = Portfolio(initial_cash)
        self.current_dt: pd.Timestamp = None
        self.previous_date: date = None
        self.benchmark_code = benchmark_code
        self.run_frequency = 'day'
        self.subportfolios = [self.portfolio]

        # 外部挂载的数据引用（由引擎注入）
        self._daily: pd.DataFrame = None
        self._financial: pd.DataFrame = None
        self._index: Dict[str, pd.DataFrame] = {}
        self._industry: pd.DataFrame = None
        self._all_stocks: List[str] = []

        # 用户自定义变量（类似聚宽 g.xxx）
        self._g: dict = {}

        # 调度任务
        self._scheduled_tasks: List[dict] = []

        # 板块/行业映射缓存
        self._industry_stocks: Dict[str, List[str]] = {}
        self._all_industries: List[str] = []

    @property
    def g(self) -> dict:
        return self._g

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return self._g.get(name)

    def __setattr__(self, name, value):
        if name.startswith('_') or name in ('portfolio', 'current_dt', 'previous_date',
                                              'benchmark_code', 'run_frequency',
                                              'subportfolios', '_g', '_scheduled_tasks',
                                              '_daily', '_financial', '_index', '_industry',
                                              '_all_stocks', '_industry_stocks',
                                              '_all_industries'):
            super().__setattr__(name, value)
        else:
            self._g[name] = value

    def set_param(self, key: str, value):
        self._g[key] = value

    def get_param(self, key: str, default=None):
        return self._g.get(key, default)

    # ── 调度接口 ──

    def run_daily(self, func: Callable, time: str = '09:30',
                  reference_security: str = None):
        """每日开盘前/后执行"""
        self._scheduled_tasks.append({
            'func': func,
            'mode': 'daily',
            'time': time,
            'ref': reference_security,
        })

    def run_weekly(self, func: Callable, weekday: int = 4, time: str = '09:30'):
        """每周指定日执行"""
        self._scheduled_tasks.append({
            'func': func,
            'mode': 'weekly',
            'weekday': weekday,
            'time': time,
        })

    def run_monthly(self, func: Callable, monthday: int = 1, time: str = '09:30'):
        self._scheduled_tasks.append({
            'func': func,
            'mode': 'monthly',
            'monthday': monthday,
            'time': time,
        })


# ═══════════════════════════════════════════════════════════════
# DataAPI —— 简化版数据查询接口（类似聚宽）
# ═══════════════════════════════════════════════════════════════

class DataAPI:
    """
    挂载到 context 上的数据查询接口。
    引擎在初始化时注入 daily / financial / index / industry 引用。
    """

    def __init__(self, context: Context):
        self._ctx = context

    def get_price(self, codes: List[str], count: int = 20,
                  end_date: date = None, fields: List[str] = None,
                  panel: bool = False) -> pd.DataFrame:
        """获取历史价格"""
        if end_date is None:
            end_date = self._ctx.previous_date
        daily = self._ctx._daily
        if daily is None or daily.empty:
            return pd.DataFrame()

        sub = daily[daily.index.get_level_values('code').isin(codes)]
        sub = sub.loc[:pd.Timestamp(end_date)] if not sub.empty else sub
        sub = sub.tail(count * len(codes) + 100) if not sub.empty else sub

        if sub.empty:
            return pd.DataFrame()

        sub = sub.reset_index()
        if fields:
            cols = ['date', 'code'] + [f for f in fields if f in sub.columns]
            sub = sub[cols]
        else:
            cols = [c for c in ['date', 'code', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turnover']
                    if c in sub.columns]
            sub = sub[cols]

        # 取最近 count 个交易日
        dates = sorted(sub['date'].unique())
        if len(dates) > count:
            cutoff = dates[-count]
            sub = sub[sub['date'] >= cutoff]

        return sub

    def get_current_data(self) -> dict:
        """获取当前截面快照（类似聚宽 get_current_data）"""
        date = self._ctx.current_dt
        daily = self._ctx._daily
        if daily is None or daily.empty:
            return {}

        if date in daily.index.get_level_values('date'):
            today_data = daily.loc[date]
        else:
            return {}

        result = {}
        for code in today_data.index:
            row = today_data.loc[code]
            info = {
                'code': code,
                'close': float(row.get('close', 0)),
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'volume': float(row.get('volume', 0)),
                'amount': float(row.get('amount', 0)),
                'turnover': float(row.get('turnover', 0)),
                'paused': False,
                'is_st': False,
            }
            result[code] = type('CurrentData', (), info)()
        return result

    def get_fundamentals(self, query, date: date = None):
        """简化版基本面查询"""
        fin = self._ctx._financial
        if fin is None or fin.empty:
            return pd.DataFrame()

        if date is None:
            date = self._ctx.previous_date

        fin_flat = fin.reset_index()
        fin_flat = fin_flat[fin_flat['report_date'] <= pd.Timestamp(date)]
        fin_flat = fin_flat.loc[fin_flat.groupby('code')['report_date'].idxmax()]

        # 简单映射 valuation / indicator 列
        col_map = {
            'valuation.code': 'code',
            'valuation.pe_ratio': 'pe_ratio',
            'valuation.pb_ratio': 'pb_ratio',
            'valuation.market_cap': 'market_cap',
            'valuation.circulating_market_cap': 'market_cap',
            'indicator.roe': 'roe',
            'indicator.roa': 'roa',
            'indicator.gross_profit_margin': 'gross_profit_margin',
            'indicator.net_profit_margin': 'net_profit_margin',
            'income.inc_revenue_year_on_year': 'inc_revenue_yoy',
            'income.inc_net_profit_year_on_year': 'inc_net_profit_yoy',
        }

        columns = []
        for c in query.columns:
            mapped = col_map.get(c, c)
            if mapped in fin_flat.columns:
                columns.append(mapped)

        result = fin_flat[columns].copy()
        result.columns = query.columns
        return result

    def industry_stocks(self, industry_code: str, date: date = None) -> List[str]:
        """获取某行业所有股票"""
        if industry_code in self._ctx._industry_stocks:
            return self._ctx._industry_stocks[industry_code]
        return []

    def all_industries(self) -> List[str]:
        """获取所有行业代码"""
        return self._ctx._all_industries
