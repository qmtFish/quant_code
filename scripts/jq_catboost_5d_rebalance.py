# =============================================================================
# 多因子选股策略（CatBoost 预测文件版）- 5 交易日调仓版
# =============================================================================
# 基于聚宽文章：https://www.joinquant.com/post/42603
# 改造（方案A：调仓周期对齐预测周期）：
#   原版：每个交易日 09:30 调仓（实际持有仅 1 天）
#   新版：每 5 个交易日调仓一次，持有 5 个交易日 -> 持有收益 ≈ 预测的 next_ret（未来5日收益）
# 所有改动处均以「[方案A改动]」标记，其余为原版逻辑原样保留。
# =============================================================================

from jqdata import *
import pandas as pd
import json
from datetime import datetime


def initialize(context):
    set_benchmark('000905.XSHG')
    g.topk = 5
    g.min_order_value = 100
    g.predictions_file_path = "catboost_ic0.0904_wr76_predictions.json"

    # ══ [方案A改动-1] 新增：调仓周期参数 ══
    # 原版无此段。g.hold_days=5 表示每 5 个交易日调仓一次（对齐 next_ret 的 5 日预测周期）；
    # g.trading_day_count 为交易日计数器，从 1 开始。
    g.hold_days = 5
    g.trading_day_count = 0

    set_option('use_real_price', True)
    set_option('order_volume_ratio', 1)
    log.set_level('order', 'error')

    run_daily(before_trading_start, time='08:00', reference_security='000905.XSHG')
    run_daily(daily_rebalance, time='09:30', reference_security='000905.XSHG')


def before_trading_start(context):
    set_slippage(PriceRelatedSlippage(0.002))
    is_after_2013 = context.current_dt > datetime(2013, 1, 1)
    set_commission(PerTrade(
        buy_cost=0.0003 if is_after_2013 else 0.003,
        sell_cost=0.0013 if is_after_2013 else 0.004,
        min_cost=5
    ))

    # ══ [方案A改动-2] 新增：每个交易日计数器 +1 ══
    # 原版无此段。每天开盘前累加，供 daily_rebalance 判断是否为调仓日。
    g.trading_day_count += 1

    try:
        g.predictions_data = json.loads(read_file(g.predictions_file_path)).get("predictions", {})
    except Exception as e:
        log.error(f"读取预测文件失败: {e}")
        g.predictions_data = {}


def daily_rebalance(context):
    # ══ [方案A改动-3] 新增：调仓节奏闸门 ══
    # 原版每日直接执行调仓。现改为：仅当计数器 % 5 == 1 时才是调仓日（第 1、6、11...个交易日），
    # 非调仓日直接 return，持仓完全不动（原版每天清仓换股的逻辑被此闸门挡住）。
    if g.trading_day_count % g.hold_days != 1:
        return

    current_date_str = str(context.current_dt.date())

    # ══ [方案A改动-4] 无预测数据时：跳过本次调仓、继续持有 ══
    # 原版：无预测数据时只是 return，但"清仓不在池持仓"的代码在下方仍会执行（造成误清仓）。
    # 新版：直接 return 跳过整个调仓，持仓保持不变，等待下一个调仓日。
    if current_date_str not in g.predictions_data:
        log.info(f"{current_date_str} 无预测数据，本次调仓跳过（继续持有）")
        return

    raw_list = g.predictions_data[current_date_str].get("top", [])
    current_data = get_current_data()
    zz500_stocks = set(get_index_stocks('000905.XSHG', date=context.current_dt))
    hs300_stocks = set(get_index_stocks('000300.XSHG', date=context.current_dt))
    buy_list = []
    zz_buy_list = []
    hs_buy_list = []
    kc_buy_lits = []
    others = []
    hs_cnt = 0
    zz_cnt = 0
    for idx, stock in enumerate(raw_list):
        if stock.startswith('688'):
            kc_buy_lits.append(stock)
            continue

        if stock in zz500_stocks:
            zz_cnt += 1 / (idx + 1)
            zz_buy_list.append(stock)
        elif stock in hs300_stocks:
            hs_cnt += 1 / (idx + 1)
            hs_buy_list.append(stock)
        else:
            others.append(stock)
            continue
        if current_data[stock].paused:
            continue
        try:
            if (context.current_dt.date() - get_security_info(stock).start_date).days < 90:
                continue
        except:
            continue
        buy_list.append(stock)
    print(f"others:{len(others)}, kc:{len(kc_buy_lits)}, zz:{len(zz_buy_list)}, hs: {len(hs_buy_list)}")

    # 注意：沿用原版选股逻辑（沪深300 成分中分数最高 topk 只）
    buy_list = hs_buy_list[:g.topk]

    if not buy_list:
        return

    print(f"购买的股票数量,zz：{zz_cnt}, hs：{hs_cnt}")

    # ── 换仓逻辑（原版代码，未改动）──────────────────────────────
    # 说明：这段"清仓+买入"在原版每天执行；在新版中因 [方案A改动-3] 的闸门，
    #       只会在调仓日（每 5 个交易日）执行，即换仓频率从每日降为 5 日一次。
    # ──────────────────────────────────────────────────────────────
    holding_set = set(buy_list)
    for stock in list(context.portfolio.positions.keys()):
        if stock not in holding_set and context.portfolio.positions[stock].value > 0:
            order_target_value(stock, 0)

    # 均等权重调仓
    target_value = context.portfolio.total_value / len(buy_list)
    for stock in buy_list:
        curr_val = context.portfolio.positions[stock].value if stock in context.portfolio.positions else 0.0
        if abs(curr_val - target_value) >= g.min_order_value:
            order_target_value(stock, target_value)
