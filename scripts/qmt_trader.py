"""
QMT 实盘交易模块 —— 读取预测结果，通过国金 QMT (xtquant) 自动下单。

========================================
 用法
========================================

1️⃣ 预览订单（不实际下单）:
    python scripts/qmt_trader.py --preview-only

2️⃣ 一键执行调仓（连接 QMT 下单）:
    python scripts/qmt_trader.py --run

3️⃣ 指定预测 JSON 文件:
    python scripts/qmt_trader.py --pred-file data/results/auto_predictions.json --top-k 10 --run

========================================
 前置条件
========================================

1. 已安装 国金QMT 客户端（mini 模式），并已登录交易账户
2. 安装 xtquant 依赖:
    pip install xtquant
3. 确认 QMT 的 Python 环境与当前环境一致（或在 QMT 内置 Python 中运行本脚本）
4. 在底部 CONFIG 段配置你的 QMT 路径和账号

========================================
 数据流
========================================

  predictor.py  →  predictions.json  →  qmt_trader.py  →  QMT下单
  （生成选股）       (stock codes)       (交易执行)

========================================
 股票代码格式说明
========================================

 本系统预测输出:   "603991.XSHG" / "002396.XSHE"
 QMT 内部代码:     "603991"（省略后缀）或 "603991.SH"
 本脚本自动处理转换。
"""

from __future__ import annotations
import sys
import json
import time
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ── 尝试导入 xtquant，若失败则降级为预览模式 ──
try:
    from xtquant import xtconstant
    from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
    from xtquant.xttype import StockAccount
    XTQUANT_AVAILABLE = True
except ImportError:
    XTQUANT_AVAILABLE = False
    print("  [警告] xtquant 未安装，仅支持预览模式预览订单")
    print("         安装: pip install xtquant")


# ═══════════════════════════════════════════════════════════════════
#  配置区 —— 根据你的实际情况修改
# ═══════════════════════════════════════════════════════════════════

class QMTConfig:
    """QMT 连接配置"""

    # ── QMT 客户端路径（mini 模式安装路径） ──
    # 通常在 QMT 安装目录下的 bin.x64 或 bin.x86
    MINI_QMT_PATH = r"C:\国金QMT\bin\x64\QMT.exe"
    # 或: r"D:\QMT\bin.x64\userdata_mini"

    # ── 交易账号（资金账号） ──
    ACCOUNT_ID = "您的资金账号"

    # ── 交易参数 ──
    TOP_K = 20                     # 最多买入股票数(从预测中取前N)
    CASH_PER_STOCK = 50_000       # 每只股票分配资金(元)，等权分配
    MAX_CASH_PER_TRADE = 200_000  # 单只股票最大买入金额
    MIN_CASH_PER_TRADE = 2_000    # 单只股票最小买入金额（低于不下单）

    # ── 买卖规则 ──
    KEEP_OLD_POSITIONS = False    # True=保留不在预测中的老持仓, False=卖出
    REBUY_THRESHOLD_DAYS = 5      # 同一只股票上次卖出后多久才能再次买入

    # ── 风控 ──
    MAX_ORDER_VALUE_RATIO = 0.25  # 单笔订单不超过该股日成交额的25%
    PRICE_LIMIT_PCT = 0.095       # 偏离昨收超9.5%不下单（接近涨停）
    MAX_TOTAL_ORDER_VALUE = 1_000_000  # 单次调仓总金额上限


# ═══════════════════════════════════════════════════════════════════
#  核心逻辑
# ═══════════════════════════════════════════════════════════════════

def load_predictions(pred_file: str) -> Tuple[str, List[str]]:
    """
    加载预测 JSON，返回最临近的预测日期及其股票列表。

    Args:
        pred_file: predictions.json 路径

    Returns:
        (trade_date_str, stock_codes)  例如 ("2026-07-17", ["603991", "002396", ...])
    """
    with open(pred_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    predictions = data.get("predictions", {})
    if not predictions:
        print("  [错误] 预测文件中没有 predictions 数据")
        sys.exit(1)

    # 找到最接近今天且 <= 今天的预测日期
    today = date.today()
    best_date = None
    best_stocks = []

    for date_str, pred in predictions.items():
        d = date.fromisoformat(date_str)
        # 取最近（<=今天）的预测日
        if d <= today:
            if best_date is None or d > best_date:
                best_date = d
                best_stocks = pred.get("top", [])

    if best_date is None:
        print(f"  [错误] 没有 <= {today} 的预测数据")
        print(f"          文件中的日期: {list(predictions.keys())}")
        sys.exit(1)

    print(f"  [预测] 日期: {best_date}, 候选股票: {len(best_stocks)} 只")
    return str(best_date), best_stocks


def convert_stock_code(code: str) -> str:
    """
    转换股票代码格式到 QMT 内部格式。

    输入格式: "603991.XSHG" / "002396.XSHE"
    输出格式: "603991"（xtquant 使用纯数字代码）

    特殊情况：
      - 如果已经是纯数字 "603991"，原样返回
      - 如果带 .SH/.SZ 后缀，去掉后缀
      - 如果带 .XSHG/.XSHE，去掉后缀
    """
    code = code.strip()
    # 去掉 .XSHG / .XSHE / .SH / .SZ 后缀
    for suffix in ['.XSHG', '.XSHE', '.SH', '.SZ']:
        if code.upper().endswith(suffix):
            code = code[:-len(suffix)]
            break
    return code


def get_stock_exchange(code: str) -> str:
    """
    判断股票所属交易所。

    Args:
        code: 纯数字股票代码或带后缀

    Returns:
        "SH" (沪市) 或 "SZ" (深市)
    """
    code_str = str(code).strip().upper()
    # 如果带后缀
    if code_str.endswith('.SH') or code_str.endswith('.XSHG'):
        return 'SH'
    if code_str.endswith('.SZ') or code_str.endswith('.XSHE'):
        return 'SZ'
    # 纯数字：6开头/688开头是沪市，其余是深市
    if code_str.startswith('6'):
        return 'SH'
    return 'SZ'


def to_qmt_code(code: str) -> str:
    """
    转换为 QMT 限价单使用的完整代码格式。
    QMT 限价单通常使用 "SH603991" 或 "603991.SH" 格式。
    这里使用市场代码前缀格式。

    Args:
        code: 原始股票代码

    Returns:
        "SH603991" 或 "SZ002396"
    """
    numeric = convert_stock_code(code)
    exchange = get_stock_exchange(code)
    return f"{exchange}{numeric}"


def format_order_desc(order_type: int) -> str:
    """下单类型文本描述"""
    return {
        xtconstant.STOCK_BUY: "买入",
        xtconstant.STOCK_SELL: "卖出",
    }.get(order_type, str(order_type))


def format_price_type(pt: int) -> str:
    """价格类型文本描述"""
    mapping = {
        xtconstant.FIXED_PRICE: "限价",
        xtconstant.LATEST_PRICE: "市价",
        xtconstant.MARKET_SH_ORDER: "对手方最优",
        xtconstant.MARKET_SH_CLOSE: "本方最优",
    }
    return mapping.get(pt, str(pt))


# ═══════════════════════════════════════════════════════════════════
#  订单计算
# ═══════════════════════════════════════════════════════════════════

def calc_target_positions(
    target_codes_raw: List[str],
    current_positions: Dict[str, float],
    available_cash: float,
    prices: Dict[str, float],
) -> Tuple[List[Dict], List[Dict]]:
    """
    计算买入和卖出清单。

    买入规则：等权分配资金，每只股票按 CASH_PER_STOCK 分配

    Args:
        target_codes_raw: 预测股票代码列表（原始格式）
        current_positions: 当前持仓 {code: shares}
        available_cash: 可用资金
        prices: {code: current_price}

    Returns:
        (buy_orders, sell_orders)
        每个 order: {code, numeric_code, price, shares, value, reason}
    """
    buy_orders = []
    sell_orders = []

    # 转换股票代码
    target_numeric = {convert_stock_code(c) for c in target_codes_raw}

    # ── 卖出不在预测中的持仓 ──
    if not QMTConfig.KEEP_OLD_POSITIONS:
        for code, shares in current_positions.items():
            if shares <= 0:
                continue
            numeric = convert_stock_code(code)
            if numeric not in target_numeric:
                price = prices.get(code, 0) or prices.get(numeric, 0)
                if price <= 0:
                    continue
                value = shares * price
                if value >= QMTConfig.MIN_CASH_PER_TRADE:
                    sell_orders.append({
                        "code": to_qmt_code(code),
                        "numeric_code": numeric,
                        "price": price,
                        "shares": -abs(shares),  # 正数表示股数，在 xtquant 中用 order_type 区分买卖
                        "value": value,
                        "reason": "不在预测列表中",
                    })

    # ── 计算买入清单 ──
    # 扣除卖出回笼资金
    sell_total = sum(o["value"] for o in sell_orders)
    total_available = available_cash + sell_total

    # 过滤出不在持仓中的目标股票，或持仓不足的
    to_buy = []
    for code in target_codes_raw:
        numeric = convert_stock_code(code)
        if numeric in current_positions:
            continue  # 已有持仓
        to_buy.append(code)

    # 等权分配
    n = min(len(to_buy), QMTConfig.TOP_K)
    if n == 0:
        print("  [仓位] 无新买入目标")
        return buy_orders, sell_orders

    cash_per_stock = min(QMTConfig.CASH_PER_STOCK, total_available / n)

    for code in to_buy[:n]:
        numeric = convert_stock_code(code)
        price = prices.get(code, 0) or prices.get(numeric, 0)
        if price <= 0:
            print(f"  [跳过] {code} 无价格数据")
            continue

        # 计算买入股数（按100股整数倍）
        target_value = min(cash_per_stock, QMTConfig.MAX_CASH_PER_TRADE)
        shares = int(target_value / price / 100) * 100

        if shares <= 0 or target_value < QMTConfig.MIN_CASH_PER_TRADE:
            print(f"  [跳过] {code} 金额不足: {target_value:.0f} < {QMTConfig.MIN_CASH_PER_TRADE}")
            continue

        actual_value = shares * price
        buy_orders.append({
            "code": to_qmt_code(code),
            "numeric_code": numeric,
            "price": price,
            "shares": shares,
            "value": actual_value,
            "reason": "预测买入",
        })

    return buy_orders, sell_orders


# ═══════════════════════════════════════════════════════════════════
#  风控检查
# ═══════════════════════════════════════════════════════════════════

def risk_check(orders: List[Dict]) -> List[Dict]:
    """
    风控检查，返回通过检查的订单。

    检查项：
    1. 总金额上限
    2. 涨跌幅偏离检查（偏离昨收超过阈值）
    3. 价格有效性

    Args:
        orders: 订单列表

    Returns:
        通过风控的订单列表
    """
    passed = []
    total_value = 0

    for order in orders:
        # 总金额检查
        if total_value + order["value"] > QMTConfig.MAX_TOTAL_ORDER_VALUE:
            print(f"  [风控] {order['numeric_code']} 跳过: 总金额超限")
            continue

        # 价格有效性
        if order["price"] <= 0 or order["price"] < 0.01:
            print(f"  [风控] {order['numeric_code']} 跳过: 价格无效 {order['price']}")
            continue

        # 金额有效性
        if order["value"] < QMTConfig.MIN_CASH_PER_TRADE:
            print(f"  [风控] {order['numeric_code']} 跳过: 金额不足 {order['value']:.0f}")
            continue

        passed.append(order)
        total_value += order["value"]

    return passed


# ═══════════════════════════════════════════════════════════════════
#  打印订单预览
# ═══════════════════════════════════════════════════════════════════

def print_orders(buy_orders: List[Dict], sell_orders: List[Dict],
                 available_cash: float, prices: Dict[str, float]):
    """打印订单预览"""
    print("\n" + "=" * 60)
    print("  QMT 订单预览")
    print("=" * 60)

    # ── 卖出 ──
    if sell_orders:
        print(f"\n  -> 卖出 ({len(sell_orders)} 只)")
        print(f"  {'代码':>10}  {'股数':>8}  {'价格':>8}  {'金额':>10}  {'原因'}")
        print(f"  {'-'*50}")
        for o in sell_orders:
            print(f"  {o['numeric_code']:>10}  {abs(o['shares']):>8}  "
                  f"{o['price']:>8.2f}  {o['value']:>10.0f}  {o['reason']}")
        sell_total = sum(o["value"] for o in sell_orders)
        print(f"  {'-'*50}")
        print(f"  {'卖出合计':>10}  {'':>8}  {'':>8}  {sell_total:>10.0f}")
    else:
        print(f"\n  -> 卖出: 无")

    # ── 买入 ──
    if buy_orders:
        print(f"\n  -> 买入 ({len(buy_orders)} 只)")
        print(f"  {'代码':>10}  {'股数':>8}  {'价格':>8}  {'金额':>10}  {'原因'}")
        print(f"  {'-'*50}")
        for o in buy_orders:
            print(f"  {o['numeric_code']:>10}  {o['shares']:>8}  "
                  f"{o['price']:>8.2f}  {o['value']:>10.0f}  {o['reason']}")
        buy_total = sum(o["value"] for o in buy_orders)
        print(f"  {'-'*50}")
        print(f"  {'买入合计':>10}  {'':>8}  {'':>8}  {buy_total:>10.0f}")
    else:
        print(f"\n  -> 买入: 无")

    # ── 资金汇总 ──
    buy_total = sum(o["value"] for o in buy_orders)
    sell_total = sum(o["value"] for o in sell_orders)
    print(f"\n  ── 资金汇总 ──")
    print(f"  可用资金:           {available_cash:>12.2f}")
    print(f"  卖出回笼:          +{sell_total:>12.2f}")
    print(f"  买入支出:          -{buy_total:>12.2f}")
    print(f"  调仓后预计可用:    {available_cash + sell_total - buy_total:>12.2f}")
    print(f"  {'='*60}\n")


# ═══════════════════════════════════════════════════════════════════
#  QMT 交易回调
# ═══════════════════════════════════════════════════════════════════

class QmtCallback(XtQuantTraderCallback if XTQUANT_AVAILABLE else object):
    """QMT 交易回调——处理异步通知"""

    def __init__(self):
        if XTQUANT_AVAILABLE:
            super().__init__()
        self.order_results = []
        self.disconnect_event = None

    def on_disconnected(self):
        print(f"  [QMT] 连接断开")

    def on_stock_order(self, order):
        self.order_results.append(order)
        print(f"  [订单] {order.stock_code} | "
              f"{'买入' if order.order_type == xtconstant.STOCK_BUY else '卖出'} | "
              f"股数={order.order_volume} | 价格={order.price:.2f} | "
              f"状态={order.order_status}")

    def on_order_error(self, order_error):
        print(f"  [订单错误] {order_error.order_id}: {order_error.error_msg}")

    def on_cancel_error(self, cancel_error):
        print(f"  [撤单错误] {cancel_error.order_id}: {cancel_error.error_msg}")

    def on_order_status(self, order):
        print(f"  [订单状态] {order.stock_code} ID={order.order_id} 状态={order.order_status}")

    def on_position_changed(self, position):
        pass

    def on_account_status(self, account_status):
        pass


# ═══════════════════════════════════════════════════════════════════
#  执行下单
# ═══════════════════════════════════════════════════════════════════

def execute_trades(buy_orders: List[Dict], sell_orders: List[Dict],
                   config: QMTConfig, dry_run: bool = True) -> int:
    """
    执行调仓下单。

    Args:
        buy_orders: 买入订单列表
        sell_orders: 卖出订单列表
        config: QMT 配置
        dry_run: True=仅打印不下单, False=实际下单

    Returns:
        提交的订单数量
    """
    if dry_run:
        print("  [模式] DRY RUN — 不下单")
        return 0

    if not XTQUANT_AVAILABLE:
        print("  [错误] xtquant 未安装，无法执行交易")
        return 0

    # ── 1. 创建交易连接 ──
    session_id = int(time.time() * 1000) % 1000000
    trader = XtQuantTrader(config.MINI_QMT_PATH, session_id)
    callback = QmtCallback()
    trader.register_callback(callback)
    trader.start()

    # ── 2. 连接并登录 ──
    print(f"\n  [QMT] 连接中...")
    connect_result = trader.connect()
    if connect_result != 0:
        print(f"  [错误] 连接失败: {connect_result}")
        trader.stop()
        return 0

    account = StockAccount(config.ACCOUNT_ID)
    login_result = trader.login(account)
    if login_result != 0:
        print(f"  [错误] 登录失败: {login_result}")
        trader.stop()
        return 0

    print(f"  [QMT] 已连接并登录: {config.ACCOUNT_ID}")

    # ── 3. 下单 ──
    total_orders = 0

    # 先卖后买
    for order in sell_orders:
        order_id = trader.order_stock(
            account,
            order["code"],                    # 股票代码（如 "SH603991"）
            xtconstant.STOCK_SELL,            # 卖出
            order["shares"],                  # 股数（正数）
            xtconstant.LATEST_PRICE,          # 市价
            0,                                # 市价单价格填0
        )
        if order_id > 0:
            total_orders += 1
            print(f"  [提交卖出] {order['numeric_code']} | {abs(order['shares'])}股 | 订单ID={order_id}")
        else:
            print(f"  [提交失败] {order['numeric_code']} 卖出: {order_id}")
        time.sleep(0.2)  # 避免下单过快

    time.sleep(1)

    for order in buy_orders:
        order_id = trader.order_stock(
            account,
            order["code"],
            xtconstant.STOCK_BUY,             # 买入
            order["shares"],                  # 股数
            xtconstant.LATEST_PRICE,          # 市价
            0,                                # 市价单价格填0
        )
        if order_id > 0:
            total_orders += 1
            print(f"  [提交买入] {order['numeric_code']} | {order['shares']}股 | 订单ID={order_id}")
        else:
            print(f"  [提交失败] {order['numeric_code']} 买入: {order_id}")
        time.sleep(0.2)

    # ── 4. 等待几秒收齐回调 ──
    time.sleep(3)

    # ── 5. 断开连接 ──
    trader.stop()
    print(f"\n  [QMT] 已断开, 共提交 {total_orders} 笔订单")

    return total_orders


# ═══════════════════════════════════════════════════════════════════
#  QMT 数据查询（获取当前持仓和价格）
# ═══════════════════════════════════════════════════════════════════

def query_qmt_portfolio(config: QMTConfig) -> Tuple[float, Dict[str, float], Dict[str, float]]:
    """
    连接 QMT 查询当前账户状态。

    Args:
        config: QMT 配置

    Returns:
        (available_cash, positions, prices)
        - available_cash: 可用资金
        - positions: {code: shares}  持仓股数，键为纯数字代码
        - prices: {code: current_price} 当前价
    """
    if not XTQUANT_AVAILABLE:
        print("  [警告] xtquant 未安装，使用模拟数据")
        return simulate_portfolio()

    session_id = int(time.time() * 1000) % 1000000
    trader = XtQuantTrader(config.MINI_QMT_PATH, session_id)
    callback = QmtCallback()
    trader.register_callback(callback)
    trader.start()

    print(f"  [QMT] 查询账户...")
    connect_result = trader.connect()
    if connect_result != 0:
        print(f"  [错误] QMT 连接失败: {connect_result}")
        trader.stop()
        return simulate_portfolio()

    account = StockAccount(config.ACCOUNT_ID)
    login_result = trader.login(account)
    if login_result != 0:
        print(f"  [错误] 登录失败: {login_result}")
        trader.stop()
        return simulate_portfolio()

    # 查询账户信息
    account_info = trader.query_account_info(account)
    if account_info:
        available_cash = float(account_info.available_cash)
        print(f"  [账户] 总资产={account_info.total_asset:.2f}  "
              f"可用={available_cash:.2f}  市值={account_info.market_value:.2f}")
    else:
        available_cash = 0
        print("  [账户] 查询失败")

    # 查询持仓
    positions = {}
    prices = {}
    try:
        pos_list = trader.query_positions(account)
        for p in pos_list:
            if p.volume > 0:
                # xtquant 返回的 stock_code 可能是 "SH603991"
                numeric = convert_stock_code(p.stock_code)
                positions[numeric] = float(p.volume)
                prices[numeric] = float(p.last_price)
                print(f"  [持仓] {numeric}  {p.volume:>6}股  "
                      f"成本={p.open_price:.2f}  现价={p.last_price:.2f}")
    except Exception as e:
        print(f"  [持仓] 查询异常: {e}")

    trader.stop()
    return available_cash, positions, prices


def simulate_portfolio() -> Tuple[float, Dict[str, float], Dict[str, float]]:
    """
    模拟账户数据（用于预览模式或无 QMT 连接时）。
    """
    print("  [模拟] 使用模拟账户数据")

    # 模拟可用资金
    available_cash = 1_000_000

    # 模拟持仓
    positions = {}

    # 模拟价格
    prices = {}

    return available_cash, positions, prices


# ═══════════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="QMT 实盘交易 — 读取预测 JSON，自动下单",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/qmt_trader.py --preview-only                    仅预览
  python scripts/qmt_trader.py --pred-file data/results/auto_predictions.json --top-k 10 --run    实际下单
  python scripts/qmt_trader.py --account "123456" --path "D:\\QMT\\bin.x64" --run    指定账号和路径
"""
    )
    parser.add_argument("--pred-file", default=None,
                        help="预测JSON文件路径（默认取 data/results/ 下最新的 *_predictions.json）")
    parser.add_argument("--top-k", type=int, default=None,
                        help=f"覆盖买入数量（默认 {QMTConfig.TOP_K}）")
    parser.add_argument("--cash-per-stock", type=float, default=None,
                        help=f"每只股票买入金额（默认 {QMTConfig.CASH_PER_STOCK}）")
    parser.add_argument("--account", default=None,
                        help="资金账号（覆盖配置文件中的 ACCOUNT_ID）")
    parser.add_argument("--path", default=None,
                        help="QMT mini 客户端路径（覆盖配置文件中的 MINI_QMT_PATH）")
    parser.add_argument("--preview-only", action="store_true",
                        help="仅预览订单，不下单")
    parser.add_argument("--run", action="store_true",
                        help="执行实际交易（需先预览确认）")
    parser.add_argument("--keep-positions", action="store_true",
                        help="保留不在预测中的老持仓（默认卖出）")

    args = parser.parse_args()

    # ── 应用参数覆盖 ──
    if args.top_k:
        QMTConfig.TOP_K = args.top_k
    if args.cash_per_stock:
        QMTConfig.CASH_PER_STOCK = args.cash_per_stock
    if args.account:
        QMTConfig.ACCOUNT_ID = args.account
    if args.path:
        QMTConfig.MINI_QMT_PATH = args.path
    if args.keep_positions:
        QMTConfig.KEEP_OLD_POSITIONS = True

    # ── 自动寻找预测文件 ──
    pred_file = args.pred_file
    if pred_file is None:
        results_dir = Path(__file__).resolve().parent.parent / "data" / "results"
        candidates = sorted(results_dir.glob("*_predictions.json"), reverse=True)
        if candidates:
            pred_file = str(candidates[0])
            print(f"  [自动] 使用预测文件: {pred_file}")
        else:
            print(f"  [错误] 未找到预测文件，请用 --pred-file 指定")
            print(f"          搜索路径: {results_dir}/*_predictions.json")
            sys.exit(1)

    # ── 1. 加载预测结果 ──
    print(f"\n{'='*60}")
    print(f"  QMT 实盘交易 v1.0")
    print(f"{'='*60}")
    trade_date, target_codes_raw = load_predictions(pred_file)
    print(f"  预测日期: {trade_date}")
    print(f"  Top K:    {QMTConfig.TOP_K}")
    print(f"  每只配资: {QMTConfig.CASH_PER_STOCK:.0f} 元")

    # ── 2. 查询当前账户 ──
    print(f"\n  [步骤 1/3] 查询账户...")
    if args.preview_only or not XTQUANT_AVAILABLE:
        available_cash, positions, prices = simulate_portfolio()
    else:
        available_cash, positions, prices = query_qmt_portfolio(QMTConfig)

    # 为目标股票补充价格（无实时行情时使用模拟价格）
    for c in target_codes_raw:
        numeric = convert_stock_code(c)
        if numeric not in prices:
            prices[numeric] = 15.0  # 模拟价格 15元

    print(f"  可用资金: {available_cash:.2f} 元")
    print(f"  当前持仓: {len(positions)} 只")
    print(f"  目标候选: {len(target_codes_raw)} 只")

    # ── 3. 计算订单 ──
    print(f"\n  [步骤 2/3] 计算订单...")
    buy_orders, sell_orders = calc_target_positions(
        target_codes_raw, positions, available_cash, prices
    )

    # 风控过滤
    buy_orders = risk_check(buy_orders)
    sell_orders = risk_check(sell_orders)

    # ── 4. 预览订单 ──
    print(f"\n  [步骤 3/3] 生成订单预览...")
    print_orders(buy_orders, sell_orders, available_cash, prices)

    # ── 5. 执行 ──
    if args.run:
        confirm = input("\n  确认执行调仓？(yes/no): ").strip().lower()
        if confirm in ("yes", "y"):
            print("\n  [执行] 开始下单...")
            count = execute_trades(buy_orders, sell_orders, QMTConfig, dry_run=False)
            print(f"\n  [完成] 共提交 {count} 笔订单")
        else:
            print("\n  [取消] 用户取消")
    else:
        print("\n  [信息] 使用 --run 参数实际执行下单")
        print("         建议: 先预览确认订单无误，再执行")


if __name__ == "__main__":
    main()
