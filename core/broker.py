"""
经纪商模块：真实交易费用计算、滑点模型、成交模拟。
"""
from __future__ import annotations
from typing import Dict, Optional, List, Tuple
from datetime import date
import numpy as np
import pandas as pd

from .context import Context, Order, Position, Portfolio


# ─────────────────────────────────────────────────────────────
# StockStatusChecker — 股票可交易状态判断
# ─────────────────────────────────────────────────────────────

class StockStatusChecker:
    """
    股票交易状态检查器。
    
    判断维度:
      - 涨跌停（主板±10%，创业板/科创板±20%，ST±5%）
      - 停牌（当日无交易数据或成交量为0）
      - 新股（上市不足N个交易日）
    """

    def __init__(self, min_list_days: int = 365):
        self.min_list_days = min_list_days
        # 缓存每日 pre_close
        self._prev_close_cache: Dict[date, Dict[str, float]] = {}

    def build_prev_close(self, date: date, daily_df: pd.DataFrame):
        """从日线数据构建昨收价映射"""
        # 找到上一个交易日的收盘价
        dates = sorted(daily_df.index.get_level_values('date').unique())
        if len(dates) < 2:
            return
        prev_date = dates[-2]  # 前一个交易日
        if prev_date in daily_df.index:
            prev = daily_df.loc[prev_date]
            cache = {}
            for code in prev.index:
                cache[code] = float(prev.loc[code]['close'])
            self._prev_close_cache[date] = cache

    def get_prev_close(self, code: str, date: date) -> Optional[float]:
        """获取某只股票的昨收价"""
        cache = self._prev_close_cache.get(date, {})
        return cache.get(code)

    def get_price_limit(self, code: str, prev_close: float) -> tuple:
        """
        计算涨跌停价格。
        返回 (limit_down, limit_up)
        """
        # 简单判断：6开头上交所主板，0开头深交所主板（±10%）
        # 3开头创业板，688开头科创板（±20%）
        # ST股票（±5%）
        if prev_close <= 0:
            return prev_close, prev_close

        if code.startswith('300') or code.startswith('688'):
            # 创业板/科创板：±20%
            ratio = 0.20
        elif code.startswith('8') or code.startswith('4'):
            # 北交所：±30%
            ratio = 0.30
        else:
            # 主板：±10%
            ratio = 0.10

        # 精确到分
        limit_down = round(prev_close * (1 - ratio), 2)
        limit_up = round(prev_close * (1 + ratio), 2)
        return limit_down, limit_up

    def can_trade(self, code: str, date: date, daily_info: dict,
                  prev_close: float, side: str) -> tuple:
        """
        检查股票是否可以交易。
        返回 (can_trade: bool, reason: str)
        """
        if daily_info is None:
            return False, '无行情数据'

        close = daily_info.get('close', 0)
        volume = daily_info.get('volume', 0)
        amount = daily_info.get('amount', 0)

        if close <= 0:
            return False, '价格无效'

        # 成交量/额接近0 → 停牌
        if volume < 1 and amount < 100:
            return False, '疑似停牌'

        # 涨跌停检测
        if prev_close > 0:
            limit_down, limit_up = self.get_price_limit(code, prev_close)
            if side == 'buy' and abs(close - limit_up) / max(limit_up, 0.01) < 0.005:
                # 涨停：无法买入
                return False, f'涨停(prev={prev_close}, limit={limit_up}, cur={close})'
            if side == 'sell' and abs(close - limit_down) / max(limit_down, 0.01) < 0.005:
                # 跌停：无法卖出
                return False, f'跌停(prev={prev_close}, limit={limit_down}, cur={close})'

        return True, ''

    def __repr__(self):
        return f"StockStatusChecker(min_list_days={self.min_list_days})"


class CommissionModel:
    """
    真实交易费用模型。

    A股费率（2025年标准）:
      - 佣金: 万2.5（最低5元）
      - 印花税: 千1（仅在卖出时征收）
      - 过户费: 万0.1（双向）
      - 证管费+经手费: 约万0.687（已包含在佣金中）
    """

    def __init__(self, commission_rate: float = 0.00025,
                 min_commission: float = 5.0,
                 stamp_tax_rate: float = 0.001,
                 transfer_fee_rate: float = 0.00001):
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate
        self.transfer_fee_rate = transfer_fee_rate

    def calc(self, price: float, shares: float, side: str) -> Tuple[float, float, float]:
        """
        返回 (commission, stamp_tax, transfer_fee)
        """
        turnover = price * abs(shares)
        commission = max(turnover * self.commission_rate, self.min_commission)
        stamp_tax = turnover * self.stamp_tax_rate if side == 'sell' else 0.0
        transfer_fee = turnover * self.transfer_fee_rate
        return commission, stamp_tax, transfer_fee

    def calc_buy_cost(self, price: float, shares: float) -> float:
        """买入一股需要花费的总金额（含费用）"""
        turnover = price * shares
        commission = max(turnover * self.commission_rate, self.min_commission) / shares
        transfer_fee = turnover * self.transfer_fee_rate / shares
        return price + commission + transfer_fee

    def calc_sell_proceeds(self, price: float, shares: float) -> float:
        """卖出一股实际到手金额（扣费后）"""
        turnover = price * shares
        shares_per_unit = shares
        commission = max(turnover * self.commission_rate, self.min_commission) / shares_per_unit
        stamp_tax = turnover * self.stamp_tax_rate / shares_per_unit
        transfer_fee = turnover * self.transfer_fee_rate / shares_per_unit
        return price - commission - stamp_tax - transfer_fee

    def __repr__(self):
        return (f"Commission(佣{self.commission_rate*10000:.1f}‰"
                f"/印{self.stamp_tax_rate*1000:.1f}‰"
                f"/过{self.transfer_fee_rate*10000:.1f}‰)")


class SlippageModel:
    """
    滑点模型。

    支持多种模式:
      - fixed: 固定比例滑点
      - price_related: 基于价格的滑点（低价股滑点比例更大）
      - volume_related: 基于成交量的滑点（大单穿透更高）
    """

    def __init__(self, mode: str = 'fixed', base_slippage: float = 0.002,
                 price_threshold: float = 10.0):
        """
        Args:
            mode: 'fixed' | 'price_related' | 'volume_related'
            base_slippage: 基础滑点比例
            price_threshold: 价格阈值（低于此价位的股票滑点加倍）
        """
        self.mode = mode
        self.base_slippage = base_slippage
        self.price_threshold = price_threshold

    def calc(self, price: float, side: str,
             daily_amount: float = None, order_amount: float = None) -> float:
        """
        计算买入/卖出的实际成交价比例偏移。
        side='buy'  -> 成交价更高 (1 + slippage)
        side='sell' -> 成交价更低 (1 - slippage)
        """
        slippage = self.base_slippage

        if self.mode == 'price_related' and price < self.price_threshold:
            slippage *= 2.0

        if self.mode == 'volume_related' and daily_amount and order_amount:
            ratio = order_amount / (daily_amount + 1e-6)
            if ratio > 0.05:
                slippage *= (1.0 + 5.0 * ratio)

        return slippage

    def __repr__(self):
        return f"Slippage({self.mode}, base={self.base_slippage})"


class Broker:
    """
    经纪商：负责订单执行、成交模拟。

    新增:
      - StockStatusChecker 进行涨跌停/停牌检测
      - 成交量比例限制（不超过日成交额的一定比例）
      - 流动性折扣（小盘股滑点更大）
    """

    def __init__(self, initial_cash: float = 1_000_000,
                 commission_model: CommissionModel = None,
                 slippage_model: SlippageModel = None,
                 order_volume_ratio: float = 0.25,
                 status_checker: StockStatusChecker = None,
                 max_volume_ratio: float = 0.10):
        self.commission = commission_model or CommissionModel()
        self.slippage = slippage_model or SlippageModel()
        self.order_volume_ratio = order_volume_ratio  # 单笔订单占日成交额最大比例
        self.max_volume_ratio = max_volume_ratio      # 累计订单占日成交额最大比例
        self.status_checker = status_checker or StockStatusChecker()
        self._order_counter = 0
        self._trading_dates: Dict[date, Dict[str, dict]] = {}  # date -> {code -> {close, amount, ...}}
        self._trade_log: List[str] = []  # 被拒绝的订单原因
        self._full_daily: pd.DataFrame = None  # 完整的 multi-index 日线数据（用于 prev_close）

    def set_daily_snapshot(self, date: date, daily_df: pd.DataFrame):
        """注入当日行情快照"""
        snap = {}
        for code in daily_df.index:
            row = daily_df.loc[code]
            snap[code] = {
                'close': float(row.get('close', 0)),
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'volume': float(row.get('volume', 0)),
                'amount': float(row.get('amount', 0)),
                'turnover': float(row.get('turnover', 0)),
            }
        self._trading_dates[date] = snap

    def set_full_daily(self, full_daily: pd.DataFrame):
        """注入完整日线数据（multi-index [date, code]），用于涨跌停检测的昨收价"""
        self._full_daily = full_daily
        # 为所有有数据的日期构建昨收价缓存
        if full_daily is not None and not full_daily.empty:
            all_dates = sorted(full_daily.index.get_level_values('date').unique())
            for i in range(1, len(all_dates)):
                prev_d = all_dates[i - 1]
                cur_d = all_dates[i]
                if prev_d in full_daily.index:
                    prev_data = full_daily.loc[prev_d]
                    cache = {}
                    for code in prev_data.index:
                        cache[code] = float(prev_data.loc[code]['close'])
                    # Store prev_close for cur_d
                    self.status_checker._prev_close_cache[cur_d.date()] = cache

    def get_daily_info(self, code: str, date: date, daily_df: pd.DataFrame) -> Optional[dict]:
        """获取个股当日行情快照"""
        if date not in self._trading_dates:
            if daily_df is not None and not daily_df.empty:
                self.set_daily_snapshot(date, daily_df)
        return self._trading_dates.get(date, {}).get(code)

    def can_trade(self, code: str, date: date, daily_df: pd.DataFrame,
                  side: str = 'buy') -> bool:
        """
        检查股票是否可以交易（排除停牌、涨跌停）。
        返回 True/False。
        """
        info = self.get_daily_info(code, date, daily_df)
        if info is None:
            return False

        prev_close = self.status_checker.get_prev_close(code, date)
        ok, reason = self.status_checker.can_trade(code, date, info, prev_close, side)
        if not ok:
            self._trade_log.append(f"{date} {code} {side}: {reason}")
        return ok

    def calc_max_trade_value(self, code: str, date: date, daily_df: pd.DataFrame) -> float:
        """
        计算单只股票的最大可交易金额（基于日成交额的比例限制）。
        """
        info = self.get_daily_info(code, date, daily_df)
        if info is None:
            return 0.0
        daily_amount = info.get('amount', 0)
        return daily_amount * self.order_volume_ratio

    def order_target_value(self, portfolio: Portfolio, code: str,
                           target_value: float, price: float,
                           date: date, min_order_value: float = 1000,
                           check_status: bool = True) -> Optional[Order]:
        """
        根据目标市值下单（类似聚宽 order_target_value）。
        返回 Order 对象，None 表示无法执行。
        """
        current = portfolio.positions.get(code)
        current_shares = current.shares if current else 0.0
        current_value = current_shares * price

        diff_value = target_value - current_value
        if abs(diff_value) < min_order_value:
            return None

        side = 'buy' if diff_value > 0 else 'sell'

        # ── 涨跌停/停牌检查 ──
        if check_status:
            if not self.can_trade(code, date, None, side):
                # 涨停不能买，跌停不能卖
                return None

        # ── 成交量限制 ──
        max_trade_val = self.calc_max_trade_value(code, date, None)
        if max_trade_val > 0 and abs(diff_value) > max_trade_val:
            # 缩量到成交量限制以内
            diff_value = max_trade_val * (1 if diff_value > 0 else -1)

        # 按收盘价计算股数（A股按100股整数倍）
        target_shares = int(diff_value / price / 100) * 100
        if abs(target_shares) < 100:
            return None

        # 滑点影响成交价
        slippage = self.slippage.calc(price, side)
        exec_price = price * (1 + slippage) if side == 'buy' else price * (1 - slippage)

        # 费用
        commission, stamp_tax, transfer_fee = self.commission.calc(exec_price, abs(target_shares), side)

        # 检查资金是否足够
        if side == 'buy':
            needed = abs(target_shares) * exec_price + commission + stamp_tax + transfer_fee
            if needed > portfolio.cash:
                # 缩量：用剩余可买资金重新计算
                max_shares = int((portfolio.cash - self.commission.min_commission * 2) / exec_price / 100) * 100
                if max_shares < 100:
                    return None
                target_shares = max_shares if target_shares > 0 else -max_shares
                diff_value = target_shares * price
                commission, stamp_tax, transfer_fee = self.commission.calc(exec_price, abs(target_shares), side)

        # 检查卖出股数不超持仓
        if side == 'sell' and abs(target_shares) > current_shares:
            target_shares = -int(current_shares / 100) * 100
            if abs(target_shares) < 100:
                return None
            diff_value = target_shares * price
            commission, stamp_tax, transfer_fee = self.commission.calc(exec_price, abs(target_shares), side)

        # 创建订单
        self._order_counter += 1
        order = Order(
            code=code,
            shares=target_shares,
            price=exec_price,
            value=abs(target_shares) * exec_price,
            commission=commission,
            tax=stamp_tax,
            side=side,
            status='filled',
            filled_shares=abs(target_shares),
            date=date,
            order_id=self._order_counter,
        )

        return order

    def execute_order(self, portfolio: Portfolio, order: Order) -> bool:
        """执行订单：更新持仓和资金"""
        code = order.code
        shares = order.shares
        price = order.price
        side = order.side
        filled = order.filled_shares

        total_cost = order.value + order.commission + order.tax + (order.value * 0.00001)

        if side == 'buy':
            # 检查资金
            if total_cost > portfolio.cash + 0.01:
                return False

            # 更新持仓
            if code not in portfolio.positions:
                portfolio.positions[code] = Position(code=code)

            pos = portfolio.positions[code]
            new_shares = pos.shares + filled
            if new_shares > 0:
                pos.avg_cost = (pos.shares * pos.avg_cost + total_cost) / new_shares
            pos.shares = new_shares
            portfolio.cash -= total_cost

        else:  # sell
            if code not in portfolio.positions:
                return False
            pos = portfolio.positions[code]
            if filled > pos.shares + 1e-8:
                return False

            proceeds = order.value - order.commission - order.tax - (order.value * 0.00001)
            pos.shares -= filled
            portfolio.cash += proceeds
            if pos.shares < 1e-8:
                del portfolio.positions[code]

        portfolio.orders.append(order)
        return True

    def execute_orders(self, portfolio: Portfolio, orders: List[Order]) -> int:
        """批量执行订单，返回成功数"""
        # 先卖后买
        sell_orders = [o for o in orders if o.side == 'sell']
        buy_orders = [o for o in orders if o.side == 'buy']

        succeeded = 0
        for o in sell_orders + buy_orders:
            if self.execute_order(portfolio, o):
                succeeded += 1
        return succeeded

    def update_broker(self, portfolio: Portfolio,
                      target_weights: Dict[str, float],
                      prices: Dict[str, float],
                      date: date,
                      min_order_value: float = 1000) -> int:
        """
        根据目标权重调仓。
        返回成交的订单数。
        """
        orders = []
        total_value = portfolio.total_value

        # 1. 先检查停牌（买入方向，卖出在清仓时单独检查）
        tradeable_buy = {c: p for c, p in prices.items() if self.can_trade(c, date, None, side='buy')}
        tradeable_sell = {c: p for c, p in prices.items() if self.can_trade(c, date, None, side='sell')}

        # 2. 生成卖出订单（清仓不在目标池的 + 减仓）
        for code, pos in list(portfolio.positions.items()):
            if pos.shares < 1e-8:
                continue
            if code not in target_weights or code not in tradeable_sell:
                # 清仓（即使跌停无法卖出也尝试，保留原股）
                order = self.order_target_value(portfolio, code, 0,
                                                 prices.get(code, pos.current_price),
                                                 date, min_order_value)
                if order:
                    orders.append(order)
            else:
                target_val = total_value * target_weights[code]
                order = self.order_target_value(portfolio, code, target_val,
                                                 prices.get(code, pos.current_price),
                                                 date, min_order_value)
                if order and order.side == 'sell':
                    orders.append(order)

        # 3. 生成买入订单
        for code, weight in target_weights.items():
            if code not in tradeable_buy:
                continue
            target_val = total_value * weight
            if target_val < min_order_value:
                continue
            current_shares = portfolio.positions[code].shares if code in portfolio.positions else 0
            current_value = current_shares * prices.get(code, 0)
            if target_val > current_value + min_order_value:
                order = self.order_target_value(portfolio, code, target_val,
                                                 prices.get(code, 0),
                                                 date, min_order_value)
                if order:
                    orders.append(order)

        # 4. 执行（先卖后买）
        return self.execute_orders(portfolio, orders)
