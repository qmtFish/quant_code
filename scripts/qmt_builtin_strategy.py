# -*- coding: utf-8 -*-
"""
国金 QMT 内置策略 —— 加载预测结果自动调仓

========================================
  使用说明
========================================

方式一（推荐）：通过 QMT 策略管理导入
  1. 打开 QMT —> 策略交易 —> 新建策略 —> Python策略
  2. 将本文件的内容完整复制到代码编辑器
  3. 在「策略参数」Tab 中配置参数（见下方参数说明）
  4. 保存后启动策略

方式二：直接部署到策略目录
  1. 将本文件复制到 QMT mini 版策略目录：
       {QMT安装目录}\\userdata_mini\\strategies\\auto_trade.py
  2. 打开 QMT 策略管理，找到 auto_trade 策略并启动

========================================
  策略参数（在 QMT 策略参数界面配置）
========================================

  pred_file        = 预测JSON的完整路径
                    默认: C:\\Users\\Cat\\Desktop\\code\\data\\results\\auto_predictions.json
  top_k            = 最多开仓股票数 (默认 20)
  cash_pct         = 单只股票占总资产比例 (默认 0.05 = 5%)
  keep_old         = 是否保留不在预测中的老持仓 (1=保留, 0=卖出, 默认0)
  trade_time       = 每天触发交易的时间 HHMMSS (默认 093500)
  min_cash         = 最小交易金额 (默认 2000)
  max_cash_pct     = 单只最大资金占比 (默认 0.15)
  rebuy_days       = 卖出后N天内不重复买入 (默认 5)

========================================
  数据流
========================================

  predictor.py -> predictions.json -> 本策略 (.py 文件) -> QMT 下单
  （生成预测）      (results目录)      (QMT内置执行)     (实盘)

========================================
  股票代码格式
========================================

  预测输出: "603991.XSHG" / "002396.XSHE"
  QMT 格式: "603991.SH"  / "002396.SZ"
  本策略自动转换。
========================================
"""

import json
import os
import time
from datetime import datetime

# ═══════════════════════════════════════════
#  默认配置（QMT 策略参数未设置时使用）
# ═══════════════════════════════════════════

_DEFAULT_PRED_FILE = r'C:\Users\Cat\Desktop\code\data\results\auto_predictions.json'
_DEFAULT_TOP_K = 20
_DEFAULT_CASH_PCT = 0.05
_DEFAULT_KEEP_OLD = False         # False=卖出不在预测中的持仓
_DEFAULT_TRADE_TIME = '093500'    # 9:35 开始交易（避开开盘波动）
_DEFAULT_MIN_CASH = 2000          # 最小交易金额
_DEFAULT_MAX_CASH_PCT = 0.15      # 单只最大资金占比
_DEFAULT_REBUY_DAYS = 5           # 卖出后N天不再买入


# ═══════════════════════════════════════════
#  工具函数
# ═══════════════════════════════════════════

def _to_qmt_code(code: str) -> str:
    """
    转换股票代码为 QMT 内部格式。

    "603991.XSHG" -> "603991.SH"
    "002396.XSHE" -> "002396.SZ"
    "688498.XSHG" -> "688498.SH"
    纯数字 -> 自动加后缀
    """
    c = code.strip().upper()
    c = c.replace('.XSHG', '.SH').replace('.XSHE', '.SZ')
    return c


def _to_numeric(code: str) -> str:
    """提取纯数字代码，如 '603991.XSHG' -> '603991'"""
    c = code.strip()
    for suffix in ('.XSHG', '.XSHE', '.SH', '.SZ'):
        if c.upper().endswith(suffix):
            c = c[:-len(suffix)]
            break
    return c


def _get_exchange(code: str) -> str:
    """判断交易所：上海 SH / 深圳 SZ"""
    c = code.strip().upper()
    if c.endswith('.SH') or c.endswith('.XSHG'):
        return 'SH'
    if c.endswith('.SZ') or c.endswith('.XSHE'):
        return 'SZ'
    n = _to_numeric(code)
    if n.startswith('6'):
        return 'SH'
    return 'SZ'


def _load_predictions(filepath: str):
    """
    加载预测 JSON，返回 (预测日期, Top股票列表)。

    支持的JSON结构（两种格式均兼容）：

    格式A（dict格式，当前项目使用）:
        {"predictions": {"2026-07-17": {"top": ["603991.XSHG", ...]}}}

    格式B（list格式）:
        {"predictions": [{"date": "2026-07-17", "top": [{"code": "...", ...}]}]}
    """
    if not os.path.exists(filepath):
        print(f'[错误] 预测文件不存在: {filepath}')
        return None, []

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    predictions = data.get('predictions', {})
    if not predictions:
        print('[错误] 预测文件无 predictions 字段')
        return None, []

    if isinstance(predictions, dict):
        # 格式A: {"2026-07-17": {"top": [...]}}
        dates = sorted(predictions.keys(), reverse=True)
        if not dates:
            return None, []
        latest_date = dates[0]
        top_raw = predictions[latest_date].get('top', [])

    elif isinstance(predictions, list):
        # 格式B: [{"date": "...", "top": [...]}]
        sorted_list = sorted(predictions, key=lambda x: x.get('date', ''), reverse=True)
        if not sorted_list:
            return None, []
        latest_date = sorted_list[0].get('date', '')
        top_raw = sorted_list[0].get('top', [])

    else:
        return None, []

    # 提取code列表 —— top可以是字符串列表或对象列表
    codes = []
    for item in top_raw:
        if isinstance(item, str):
            codes.append(item)
        elif isinstance(item, dict):
            codes.append(item.get('code', ''))
    codes = [c for c in codes if c]

    return latest_date, codes


# ═══════════════════════════════════════════
#  策略入口 — init
# ═══════════════════════════════════════════

def init(ContextInfo):
    """
    策略初始化（QMT 策略引擎启动时调用一次）。
    """
    # 设置K线周期为日线
    ContextInfo.set_field_name('1d')
    ContextInfo.set_field_count(5)

    # ── 从策略参数读取（可在QMT界面上配置） ──
    ContextInfo._pred_file   = ContextInfo.get_para('pred_file')   or _DEFAULT_PRED_FILE
    ContextInfo._top_k       = int(ContextInfo.get_para('top_k')   or _DEFAULT_TOP_K)
    ContextInfo._cash_pct    = float(ContextInfo.get_para('cash_pct') or _DEFAULT_CASH_PCT)
    ContextInfo._keep_old    = (ContextInfo.get_para('keep_old') == '1') or _DEFAULT_KEEP_OLD
    ContextInfo._trade_time  = ContextInfo.get_para('trade_time')  or _DEFAULT_TRADE_TIME
    ContextInfo._min_cash    = float(ContextInfo.get_para('min_cash') or _DEFAULT_MIN_CASH)
    ContextInfo._max_cash_pct = float(ContextInfo.get_para('max_cash_pct') or _DEFAULT_MAX_CASH_PCT)
    ContextInfo._rebuy_days  = int(ContextInfo.get_para('rebuy_days') or _DEFAULT_REBUY_DAYS)
    ContextInfo._last_trade_day = ''   # 上次调仓日期，防止同一天重复触发

    # ── 打印启动信息 ──
    print('')
    print('=' * 50)
    print('  预测调仓策略 v1.0')
    print('=' * 50)
    print(f'  预测文件:     {ContextInfo._pred_file}')
    print(f'  Top K:        {ContextInfo._top_k}')
    print(f'  单只资金比例: {ContextInfo._cash_pct:.1%}')
    print(f'  单只最大比例: {ContextInfo._max_cash_pct:.1%}')
    print(f'  交易时间:     {ContextInfo._trade_time}')
    print(f'  保留旧仓:     {ContextInfo._keep_old}')
    print(f'  卖出冷却天数: {ContextInfo._rebuy_days}')
    print('=' * 50)
    print('')


# ═══════════════════════════════════════════
#  策略入口 — handlebar (核心逻辑)
# ═══════════════════════════════════════════

def handlebar(ContextInfo):
    """
    每日 K 线回调 —— 执行调仓。
    QMT 日线周期下，每个交易日开盘后触发一次。
    """
    try:
        _rebalance(ContextInfo)
    except Exception as e:
        print(f'[异常] handlebar 出错: {e}')
        import traceback
        traceback.print_exc()


def _rebalance(ContextInfo):
    """调仓核心：加载预测 -> 获取持仓 -> 对比 -> 下单"""

    # ── 时间检查 ──
    now = datetime.now()
    cur_time = now.strftime('%H%M%S')
    today_str = now.strftime('%Y-%m-%d')

    # 不到指定时间不交易
    if cur_time < ContextInfo._trade_time:
        return

    # 同一天不重复调仓
    if ContextInfo._last_trade_day == today_str:
        return

    print(f'\n{"=" * 50}')
    print(f'  [{today_str}] 开始调仓')
    print(f'{"=" * 50}')

    # ────────────────────────────────────────
    # 1. 加载预测结果
    # ────────────────────────────────────────
    pred_file = ContextInfo._pred_file
    if not os.path.exists(pred_file):
        print(f'  [错误] 预测文件不存在: {pred_file}')
        print(f'  [提示] 可在策略参数中设置 pred_file 路径')
        return

    pred_date, all_targets = _load_predictions(pred_file)
    if not all_targets:
        return

    # 截取 Top-K
    target_codes = all_targets[:ContextInfo._top_k]
    # 建立快速查找 set（用纯数字代码）
    target_numeric_set = set()
    target_qmt_map = {}  # numeric -> qmt_code
    target_order = []    # 保持原始顺序
    for c in target_codes:
        n = _to_numeric(c)
        if n not in target_numeric_set:
            target_numeric_set.add(n)
            target_qmt_map[n] = _to_qmt_code(c)
            target_order.append(n)

    print(f'  预测日期: {pred_date}')
    print(f'  候选股票: {len(target_codes)} 只')
    if target_order:
        print(f'  Top 列表: {", ".join(target_order[:5])} ...')

    # ────────────────────────────────────────
    # 2. 获取账户信息
    # ────────────────────────────────────────
    try:
        account_info = ContextInfo.get_account_info()
        if account_info is None:
            print('  [错误] 无法获取账户信息')
            return
        # 兼容不同 QMT 版本的属性名
        available_cash = getattr(account_info, 'm_dAvailable', 0)
        total_asset    = getattr(account_info, 'm_dTotalAsset', 0)
        market_value   = getattr(account_info, 'm_dMarketValue', 0)
        if available_cash == 0:
            available_cash = getattr(account_info, 'available_cash', 0)
        if total_asset == 0:
            total_asset = getattr(account_info, 'total_asset', 0)
    except Exception as e:
        print(f'  [错误] 获取账户信息异常: {e}')
        return

    print(f'  总资产: {total_asset:>12.2f}')
    print(f'  可用资金: {available_cash:>10.2f}')
    print(f'  持仓市值: {market_value:>10.2f}')

    # ────────────────────────────────────────
    # 3. 获取当前持仓
    # ────────────────────────────────────────
    positions = {}        # numeric_code -> volume
    position_prices = {}  # numeric_code -> last_price (for valuation)
    try:
        pos_list = ContextInfo.get_position()
        if pos_list:
            for p in pos_list:
                raw_code = getattr(p, 'm_strStockCode', '') or getattr(p, 'stock_code', '')
                volume = float(getattr(p, 'm_nVolume', 0) or getattr(p, 'volume', 0))
                if volume > 0 and raw_code:
                    numeric = _to_numeric(raw_code)
                    positions[numeric] = volume
                    # 当前价
                    last_p = float(getattr(p, 'm_dLastPrice', 0) or getattr(p, 'last_price', 0))
                    position_prices[numeric] = last_p
    except Exception as e:
        print(f'  [警告] 获取持仓异常: {e}')

    print(f'  当前持仓: {len(positions)} 只')
    for code, vol in sorted(positions.items()):
        print(f'    {code:>8}  {int(vol):>6}股')

    # ────────────────────────────────────────
    # 4. 计算买卖清单
    # ────────────────────────────────────────

    # —— 卖出清单：持仓中不在预测列表的 ——
    sell_list = []
    for code, vol in positions.items():
        if code not in target_numeric_set:
            sell_list.append(code)

    # —— 买入清单：预测列表中未持仓的 ——
    buy_list = []
    for n in target_order:
        if n not in positions:
            buy_list.append(n)

    print(f'  计划卖出: {len(sell_list)} 只')
    print(f'  计划买入: {len(buy_list)} 只')

    if not sell_list and not buy_list:
        print('  [完成] 无变动需要执行')
        ContextInfo._last_trade_day = today_str
        return

    # ────────────────────────────────────────
    # 5. 执行卖出（先卖后买）
    # ────────────────────────────────────────
    if sell_list:
        print(f'\n  —— 执行卖出 ——')
        for code in sell_list:
            qmt_code = _to_qmt_code(code)  # code is numeric
            vol = int(positions.get(code, 0))
            if vol <= 0:
                continue
            try:
                # 市价卖出：volume 负数 = 卖出
                # price_type=5 对手方最优价格
                order_id = order(qmt_code, -vol, 5, 0)
                print(f'  [卖出] {qmt_code}  {vol}股  订单={order_id}')
            except Exception as e:
                print(f'  [卖出失败] {qmt_code}: {e}')

        # 等卖出信号提交
        time.sleep(1)

    # ────────────────────────────────────────
    # 6. 执行买入
    # ────────────────────────────────────────
    if buy_list:
        # 等权分配：每只买入资金 = 总资产 * cash_pct，上限 max_cash_pct
        cash_per_stock = total_asset * ContextInfo._cash_pct
        max_per_stock  = total_asset * ContextInfo._max_cash_pct
        cash_per_stock = min(cash_per_stock, max_per_stock)

        # 防止资金不足：以可用资金为上限按比例分配
        if cash_per_stock * len(buy_list) > available_cash * 0.95:
            cash_per_stock = available_cash * 0.95 / max(len(buy_list), 1)

        # 最后兜底：不低于最小金额
        cash_per_stock = max(cash_per_stock, ContextInfo._min_cash)

        print(f'\n  —— 执行买入 ——')
        print(f'  单只分配: {cash_per_stock:.0f} 元')

        for numeric in buy_list:
            qmt_code = target_qmt_map.get(numeric, _to_qmt_code(numeric))

            # 6a. 获取当前价格
            price = _get_stock_price(ContextInfo, qmt_code, numeric)
            if price is None or price <= 0:
                print(f'  [跳过] {qmt_code} 获取价格失败')
                continue

            # 6b. 涨停检查（偏离昨收 > 9.5% 跳过）
            try:
                df = ContextInfo.get_market_data(
                    ['close', 'preClose'],
                    [qmt_code],
                    '1d',
                    2
                )
                if df is not None and not df.empty and 'preClose' in df.columns:
                    pre_close = float(df['preClose'].iloc[-1])
                    if pre_close > 0 and abs(price - pre_close) / pre_close > 0.095:
                        print(f'  [跳过] {qmt_code} 偏离昨收超9.5% (现价{price:.2f}/昨收{pre_close:.2f})')
                        continue
            except Exception:
                pass  # 忽略检查失败

            # 6c. 计算买入股数（100股整数倍）
            target_value = min(cash_per_stock, max_per_stock)
            shares = int(target_value / price / 100) * 100

            if shares <= 0 or target_value < ContextInfo._min_cash:
                print(f'  [跳过] {qmt_code} 金额不足: {target_value:.0f} < {ContextInfo._min_cash:.0f}')
                continue

            # 6d. 下单
            try:
                order_id = order(qmt_code, shares, 5, 0)
                actual_value = shares * price
                print(f'  [买入] {qmt_code}  {shares}股  '
                      f'@{price:.2f} 约{actual_value:.0f}元  订单={order_id}')
            except Exception as e:
                print(f'  [买入失败] {qmt_code}: {e}')

    # ────────────────────────────────────────
    # 7. 完成
    # ────────────────────────────────────────
    ContextInfo._last_trade_day = today_str
    print(f'\n  [完成] {today_str} 调仓结束\n')


def _get_stock_price(ContextInfo, qmt_code: str, numeric: str):
    """
    获取股票当前价格。
    优先用 get_full_tick 的实时价，降级用日线最新价。
    """
    # 方法1: 实时行情
    try:
        ticks = ContextInfo.get_full_tick([qmt_code])
        if ticks and qmt_code in ticks:
            tick = ticks[qmt_code]
            price = float(getattr(tick, 'lastPrice', 0) or tick.get('lastPrice', 0)
                          if isinstance(tick, dict) else getattr(tick, 'lastPrice', 0))
            if price and price > 0:
                return price
    except Exception:
        pass

    # 方法2: 日线最新价
    try:
        df = ContextInfo.get_market_data(['close'], [qmt_code], '1d', 1)
        if df is not None and not df.empty:
            return float(df.iloc[-1, 0])
    except Exception:
        pass

    return None


"""
========================================
  附录：QMT 内置策略 API 速查
========================================

  入口函数：
    init(ContextInfo)         — 策略初始化
    handlebar(ContextInfo)    — 每个新K线触发

  ContextInfo 常用方法：
    get_account_info()        — 账户: m_dAvailable / available_cash
    get_position()            — 持仓: m_strStockCode / m_nVolume
    get_full_tick(codes)      — 实时Tick
    get_market_data(...)      — K线数据
    get_para(name)            — 读取策略参数

  下单函数（全局内置）：
    order(code, volume, price_type, price)
      price_type: 5=对手方最优(市价), 4=限价
      volume: 正数买入, 负数卖出

  股票代码格式：
    '603991.SH'    上海
    '002396.SZ'    深圳
"""
