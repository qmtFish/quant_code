# -*- coding: utf-8 -*-
"""
国金 QMT 内置策略 —— 加载预测结果自动调仓（增强调仓信息版）
基于官方标准 ContextInfo 及内置下单函数编写
"""

import json
import os
from datetime import datetime

# ═══════════════════════════════════════════
#  默认配置
# ═══════════════════════════════════════════
_DEFAULT_PRED_FILE = r'C:\Users\Cat\Desktop\code\data\results\auto_predictions.json'
_DEFAULT_TOP_K = 20
_DEFAULT_CASH_PCT = 0.05
_DEFAULT_TRADE_TIME = '093500'
_DEFAULT_MIN_CASH = 2000

def init(ContextInfo):
    """
    策略初始化
    """
    # 如果你在 QMT 界面策略参数中配置了对应参数，会自动挂载到 ContextInfo 上
    # 这里使用 getattr 做安全兼容，未配时使用上方默认值
    ContextInfo.pred_file = getattr(ContextInfo, 'pred_file', _DEFAULT_PRED_FILE)
    ContextInfo.top_k = int(getattr(ContextInfo, 'top_k', _DEFAULT_TOP_K))
    ContextInfo.cash_pct = float(getattr(ContextInfo, 'cash_pct', _DEFAULT_CASH_PCT))
    ContextInfo.trade_time = str(getattr(ContextInfo, 'trade_time', _DEFAULT_TRADE_TIME))
    ContextInfo.min_cash = float(getattr(ContextInfo, 'min_cash', _DEFAULT_MIN_CASH))

    ContextInfo.last_trade_day = ''   # 防止同一天重复调仓

    # 预加载预测目标并设置股票池：QMT 内置策略的 get_history_data 只能取到
    # set_universe 股票池内的数据，这一步确保目标股能取到行情
    try:
        _, init_targets = _load_predictions(ContextInfo.pred_file)
        if init_targets:
            ContextInfo.set_universe([_to_qmt_code(c) for c in init_targets])
            print('  股票池已更新: ' + str(len(init_targets)) + ' 只 (来自预测文件)')
    except Exception as e:
        print('[警告] init 设置股票池失败: ' + str(e))

    print('=' * 60)
    print('  预测调仓策略初始化成功 (国金QMT标准版)')
    print('  ' + '-' * 56)
    print('  预测文件路径: ' + ContextInfo.pred_file)
    print('  Top-K 数量:   ' + str(ContextInfo.top_k))
    print('  单股资金比例: ' + str(ContextInfo.cash_pct * 100) + '%')
    print('  触发时间:     ' + str(ContextInfo.trade_time))
    print('  最小单股资金: ¥' + str(ContextInfo.min_cash))
    print('=' * 60)

def handlebar(ContextInfo):
    """
    主循环函数，每个K线周期触发
    """
    try:
        _rebalance(ContextInfo)
    except Exception as e:
        print('[异常] handlebar 执行出错: ' + str(e))
        import traceback
        traceback.print_exc()

def _to_qmt_code(code: str) -> str:
    """股票代码格式转换: 603991.XSHG -> 603991.SH；北交所 .BJ 保持原样"""
    c = code.strip().upper()
    return c.replace('.XSHG', '.SH').replace('.XSHE', '.SZ')

def _to_numeric(code: str) -> str:
    """提取纯数字代码: 603991.XSHG -> 603991"""
    c = code.strip()
    for suffix in ('.XSHG', '.XSHE', '.SH', '.SZ', '.BJ'):
        if c.upper().endswith(suffix):
            c = c[:-len(suffix)]
            break
    return c

def _calc_shares(qmt_code: str, budget: float, price: float) -> int:
    """按 A 股交易规则计算可买股数。
    科创板(688开头)最低 200 股、超出部分按 1 股递增；其余按 100 股整手。
    价格或预算无效时返回 0。"""
    if price <= 0 or budget <= 0:
        return 0
    if qmt_code.startswith('688'):
        shares = int(budget / price)
        return shares if shares >= 200 else 0
    return int(budget / price / 100) * 100

def _safe_get_stock_name(ContextInfo, code: str) -> str:
    """安全获取股票名称，失败时返回代码本身"""
    try:
        if hasattr(ContextInfo, 'get_stock_name'):
            name = ContextInfo.get_stock_name(code)
            return name if name else code
    except Exception:
        pass
    return code

def _load_predictions(filepath: str):
    """加载预测 JSON 文件"""
    if not os.path.exists(filepath):
        print('[错误] 预测文件不存在: ' + filepath)
        return None, []

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    predictions = data.get('predictions', {})
    if not predictions:
        return None, []

    if isinstance(predictions, dict):
        dates = sorted(predictions.keys(), reverse=True)
        if not dates:
            return None, []
        latest_date = dates[0]
        top_raw = predictions[latest_date].get('top', [])
    elif isinstance(predictions, list):
        sorted_list = sorted(predictions, key=lambda x: x.get('date', ''), reverse=True)
        if not sorted_list:
            return None, []
        latest_date = sorted_list[0].get('date', '')
        top_raw = sorted_list[0].get('top', [])
    else:
        return None, []

    codes = []
    for item in top_raw:
        if isinstance(item, str):
            codes.append(item)
        elif isinstance(item, dict):
            codes.append(item.get('code', ''))
    codes = [c for c in codes if c]
    return latest_date, codes


def _rebalance(ContextInfo):
    """调仓核心逻辑（含详细调仓报告）"""
    # 获取当前时间与日期字符串
    bar_pos = ContextInfo.barpos
    timetag = ContextInfo.get_bar_timetag(bar_pos)
    today_str = datetime.fromtimestamp(timetag / 1000).strftime('%Y-%m-%d') if timetag > 0 else datetime.now().strftime('%Y-%m-%d')

    # 同一天不重复调仓
    if ContextInfo.last_trade_day == today_str:
        return

    # 触发时间控制：日线 bar 时间戳通常为 00:00（视为全天有效不拦截）；
    # 分钟级 K 线则在达到 trade_time 之前不调仓
    try:
        if timetag > 0:
            bar_time_str = datetime.fromtimestamp(timetag / 1000).strftime('%H%M%S')
        else:
            bar_time_str = datetime.now().strftime('%H%M%S')
        if bar_time_str != '000000' and bar_time_str < ContextInfo.trade_time:
            return
    except Exception:
        pass

    # ═══════════════════════════════════════════
    #  1. 加载预测数据
    # ═══════════════════════════════════════════
    pred_date, all_targets = _load_predictions(ContextInfo.pred_file)
    if not all_targets:
        return

    # 预测数据时效检查（仅提示，不阻断交易）
    if pred_date:
        try:
            pred_dt = datetime.strptime(str(pred_date), '%Y-%m-%d')
            age_days = (datetime.strptime(today_str, '%Y-%m-%d') - pred_dt).days
            if age_days > 7:
                print('  [警告] 预测数据日期 ' + str(pred_date) + ' 距今 ' + str(age_days) + ' 天，请确认预测文件已更新')
        except Exception:
            pass

    target_codes = all_targets[:ContextInfo.top_k]
    target_numeric_set = {_to_numeric(c) for c in target_codes}
    target_qmt_map = {_to_numeric(c): _to_qmt_code(c) for c in target_codes}
    target_order = [_to_numeric(c) for c in target_codes]

    # ═══════════════════════════════════════════
    #  2. 获取账户资金
    # ═══════════════════════════════════════════
    total_asset = getattr(ContextInfo, 'capital', 1000000)
    available_cash = None
    try:
        account_info = ContextInfo.get_account_info() if hasattr(ContextInfo, 'get_account_info') else None
        if account_info:
            total_asset = getattr(account_info, 'm_dTotalAsset', 0) or getattr(account_info, 'total_asset', total_asset)
            available_cash = getattr(account_info, 'm_dAvailable', 0) or getattr(account_info, 'available', None)
    except Exception:
        pass

    # ═══════════════════════════════════════════
    #  3. 获取当前持仓
    # ═══════════════════════════════════════════
    # positions: {numeric_code -> {'vol': int, 'cost': float, 'mkt_val': float}}
    positions = {}
    try:
        pos_list = ContextInfo.get_position() if hasattr(ContextInfo, 'get_position') else []
        if pos_list:
            for p in pos_list:
                raw_code = getattr(p, 'm_strStockCode', '') or getattr(p, 'stock_code', '')
                volume = float(getattr(p, 'm_nVolume', 0) or getattr(p, 'volume', 0))
                if volume > 0 and raw_code:
                    ncode = _to_numeric(raw_code)
                    cost_price = getattr(p, 'm_dCostPrice', 0) or getattr(p, 'cost_price', 0)
                    market_value = getattr(p, 'm_dMarketValue', 0) or getattr(p, 'market_value', 0)
                    profit_loss = getattr(p, 'm_dProfitLoss', 0) or getattr(p, 'profit_loss', 0)
                    # 可卖数量：优先取可用数量(T+1 当日买入部分不可卖)，字段缺失时退回总持仓
                    can_use_volume = getattr(p, 'm_nCanUseVolume', None)
                    if can_use_volume is None:
                        can_use_volume = getattr(p, 'can_use_volume', None)
                    if can_use_volume is None:
                        can_use_volume = volume
                    positions[ncode] = {
                        'vol': int(volume),
                        'sellable': int(float(can_use_volume)),
                        'cost': float(cost_price),
                        'mkt_val': float(market_value),
                        'pnl': float(profit_loss),
                        'qmt_code': _to_qmt_code(raw_code)
                    }
    except Exception as e:
        print('  [警告] 获取持仓异常: ' + str(e))

    # ═══════════════════════════════════════════
    #  4. 获取最新价格
    # ═══════════════════════════════════════════
    all_qmt_codes = list(set(
        [target_qmt_map[n] for n in target_order] +
        [positions[c]['qmt_code'] for c in positions]
    ))
    price_dict = {}
    if all_qmt_codes:
        history_prices = None
        try:
            # get_history_data 只返回股票池内数据，取数前先更新股票池；
            # div_method 官方文档为字符串 'forward'(前复权)/'backward'/'none'
            if hasattr(ContextInfo, 'set_universe'):
                ContextInfo.set_universe(all_qmt_codes)
            history_prices = ContextInfo.get_history_data(1, '1d', 'close', 'forward')
        except Exception as e:
            print('  [警告] 获取行情异常: ' + str(e))
        if history_prices:
            for qcode in all_qmt_codes:
                vals = history_prices.get(qcode) if isinstance(history_prices, dict) else None
                if vals and len(vals) > 0:
                    price_dict[_to_numeric(qcode)] = vals[-1]

    # ═══════════════════════════════════════════
    #  5. 计算买卖清单
    # ═══════════════════════════════════════════
    sell_list = [code for code in positions if code not in target_numeric_set]
    buy_list = [n for n in target_order if n not in positions]

    cash_per_stock = total_asset * ContextInfo.cash_pct
    cash_per_stock = max(cash_per_stock, ContextInfo.min_cash)

    # 按可用资金收紧单股预算，避免买入总额超出可用资金
    if buy_list and available_cash is not None and available_cash > 0:
        cap_per_stock = available_cash / len(buy_list)
        if cash_per_stock > cap_per_stock:
            print('  [提示] 可用资金有限，单股资金由 ¥{:,.2f} 下调至 ¥{:,.2f}'.format(cash_per_stock, cap_per_stock))
            cash_per_stock = cap_per_stock
    if cash_per_stock <= 0:
        print('  [警告] 可用资金不足，本次不买入')

    # ═══════════════════════════════════════════
    #  6. ★ 调仓前全景报告 ★
    # ═══════════════════════════════════════════
    print('\n' + '=' * 60)
    print('  ★ 调仓全景报告 ★  ' + today_str)
    print('=' * 60)
    print('  [基础信息]')
    print('    预测数据日期:   ' + str(pred_date))
    print('    账户总资产:     ¥{:>12,.2f}'.format(total_asset))
    if available_cash is not None:
        print('    可用资金:       ¥{:>12,.2f}'.format(available_cash))
    print('    当前持仓只数:   ' + str(len(positions)) + ' 只')
    print('    目标组合只数:   ' + str(len(target_codes)) + ' 只 (Top-' + str(ContextInfo.top_k) + ')')
    print('    需卖出:         ' + str(len(sell_list)) + ' 只  需买入: ' + str(len(buy_list)) + ' 只')
    print('    单股分配资金:   ¥{:>10,.2f}'.format(cash_per_stock))
    print('    分配总金额:     ¥{:>10,.2f}'.format(cash_per_stock * len(buy_list)))

    # ── 当前持仓明细表 ──
    if positions:
        print('  ' + '-' * 56)
        print('  [当前持仓明细（共 ' + str(len(positions)) + ' 只）]')
        header = '  {:<14} {:<10} {:>8} {:>9} {:>10} {:>10}'.format(
            '代码', '名称', '数量(股)', '现价', '市值', '盈亏')
        print(header)
        print('  ' + '-' * 56)
        pos_total_value = 0
        pos_total_pnl = 0
        for code in sorted(positions.keys()):
            info = positions[code]
            qmt_code = info['qmt_code']
            vol = info['vol']
            price = price_dict.get(code, 0)
            mkt_val = info['mkt_val'] if info['mkt_val'] > 0 else vol * price
            pnl = info['pnl']
            name = _safe_get_stock_name(ContextInfo, qmt_code)
            pos_total_value += mkt_val
            pos_total_pnl += pnl
            pnl_flag = '+' if pnl >= 0 else ''
            print('  {:<14} {:<10} {:>8d} {:>9.2f} {:>10,.2f} {:>+10,.2f}'.format(
                qmt_code, name, vol, price, mkt_val, pnl))
        print('  ' + '-' * 56)
        print('  {:>14} {:>10} {:>9} {:>10,.2f} {:>+10,.2f}'.format(
            '持仓合计:', str(sum(positions[c]['vol'] for c in positions)) + '股',
            '', pos_total_value, pos_total_pnl))
    else:
        print('  [当前持仓明细] 空仓')

    # ── 目标持仓列表 ──
    print('  ' + '-' * 56)
    print('  [目标持仓列表 Top-' + str(len(target_codes)) + ']')
    header2 = '{:>4} {:>4} {:<14} {:<10} {:>8} {:>10}'.format(
        '排名', '状态', '代码', '名称', '现价', '目标资金')
    print(header2)
    print('  ' + '-' * 56)
    for i, ncode in enumerate(target_order, 1):
        qmt_code = target_qmt_map.get(ncode, _to_qmt_code(ncode))
        price = price_dict.get(ncode, 0)
        name = _safe_get_stock_name(ContextInfo, qmt_code)
        if ncode in positions:
            status = '已有'
            target_money = 0  # 已有持仓，不额外分配买入资金
        else:
            status = '新买'
            target_money = cash_per_stock
        print('  {:>4d} {:>4s} {:<14} {:<10} {:>8.2f} {:>10,.2f}'.format(
            i, status, qmt_code, name, price, target_money))
    print('  ' + '-' * 56)
    new_buy_count = len(buy_list)
    keep_count = len(target_codes) - new_buy_count
    print('  保留: ' + str(keep_count) + ' 只 | 新增: ' + str(new_buy_count) + ' 只 | 预计新增资金: ¥{:>,.2f}'.format(
        cash_per_stock * new_buy_count))

    # ── 买卖清单 ──
    print('  ' + '-' * 56)
    print('  [买卖清单]')
    if sell_list:
        sell_total_value = 0
        print('    ↓ 卖出 ' + str(len(sell_list)) + ' 只（不在目标组合）:')
        for code in sell_list:
            info = positions[code]
            qmt_code = info['qmt_code']
            vol = info['vol']
            price = price_dict.get(code, 0)
            value = vol * price if price > 0 else info['mkt_val']
            sell_total_value += value
            name = _safe_get_stock_name(ContextInfo, qmt_code)
            cost_total = info['cost'] * vol if info['cost'] > 0 else 0
            pnl_text = ''
            if info['cost'] > 0 and price > 0:
                pnl_pct = (price - info['cost']) / info['cost'] * 100
                pnl_text = ' (成本¥{:.2f}, 盈亏{:+.2f}%)'.format(info['cost'], pnl_pct)
            print('    {:<14} {:<10} {:>8d}股 × ¥{:>7.2f} = ¥{:>10,.2f}{}'.format(
                qmt_code, name, vol, price, value, pnl_text))
        print('    ── 预计卖出回收: ¥{:>10,.2f}'.format(sell_total_value))
    else:
        print('    ↓ 无需卖出')

    if buy_list:
        buy_total_value = 0
        print('    ↑ 买入 ' + str(len(buy_list)) + ' 只:')
        for code in buy_list:
            qmt_code = target_qmt_map.get(code, _to_qmt_code(code))
            price = price_dict.get(code, 0)
            if price <= 0:
                name = _safe_get_stock_name(ContextInfo, qmt_code)
                print('    {:<14} {:<10} 价格缺失，跳过'.format(qmt_code, name))
                continue
            shares = _calc_shares(qmt_code, cash_per_stock, price)
            value = shares * price if shares > 0 else 0
            buy_total_value += value
            name = _safe_get_stock_name(ContextInfo, qmt_code)
            pct = ContextInfo.cash_pct * 100
            print('    {:<14} {:<10} {:>8d}股 × ¥{:>7.2f} = ¥{:>10,.2f}  (≈{:.0f}%仓位)'.format(
                qmt_code, name, shares, price, value, pct))
        print('    ── 预计买入投入: ¥{:>10,.2f}'.format(buy_total_value))

    # 资金净变动预估
    if sell_list or buy_list:
        sell_total = sum(
            positions[c]['vol'] * price_dict.get(c, 0) if price_dict.get(c, 0) > 0 else positions[c]['mkt_val']
            for c in sell_list
        )
        buy_total = buy_total_value if buy_list else 0
        net_change = sell_total - buy_total
        print('    ── 资金净变动:   ¥{:>+10,.2f}'.format(net_change))
        if net_change < 0:
            print('    ⚠ 提示: 买入资金超出卖出回收，需确保可用资金充足')

    print('=' * 60)
    # ★ 报告结束 ★

    # ═══════════════════════════════════════════
    #  7. 执行卖出
    # ═══════════════════════════════════════════
    sell_order_count = 0
    sell_order_value = 0
    if sell_list:
        print('  ' + '-' * 56)
        print('  [执行卖出] 共 ' + str(len(sell_list)) + ' 只')
        for code in sell_list:
            info = positions[code]
            qmt_code = info['qmt_code']
            vol = info.get('sellable', info['vol'])   # 用可用数量卖出，规避 T+1 冻结
            price = price_dict.get(code, 0)
            name = _safe_get_stock_name(ContextInfo, qmt_code)
            if vol <= 0:
                print('  [跳过卖出] {:<14} {:<10} 无可卖数量(T+1 冻结)，保留'.format(qmt_code, name))
                continue
            if price <= 0:
                print('  [跳过卖出] {:<14} {:<10} 价格缺失，暂不卖出'.format(qmt_code, name))
                continue
            if hasattr(ContextInfo, 'accountID'):
                order_shares(qmt_code, -vol, 'fix', price, ContextInfo, ContextInfo.accountID)
            else:
                order_shares(qmt_code, -vol, 'fix', price, ContextInfo)
            mkt_val = vol * price
            # 盈亏统计
            pnl_str = ''
            if info['cost'] > 0:
                pnl = (price - info['cost']) * vol
                pnl_pct = (price - info['cost']) / info['cost'] * 100
                pnl_str = '  成本¥{:.2f}, 盈亏{:+.0f} ({:+.2f}%)'.format(info['cost'], pnl, pnl_pct)
            print('  [委托卖出] {:<14} {:<10} {:>8d}股 × ¥{:>7.2f} = ¥{:>10,.2f}{}'.format(
                qmt_code, name, vol, price, mkt_val, pnl_str))
            sell_order_count += 1
            sell_order_value += mkt_val
        print('  ── 已委托卖出: ' + str(sell_order_count) + ' 只, 预计回收 ¥{:>10,.2f}'.format(sell_order_value))
    else:
        print('  [执行卖出] 无卖出操作')

    # ═══════════════════════════════════════════
    #  8. 执行买入
    # ═══════════════════════════════════════════
    buy_order_count = 0
    buy_order_value = 0
    if buy_list:
        print('  ' + '-' * 56)
        print('  [执行买入] 共 ' + str(len(buy_list)) + ' 只')
        for numeric in buy_list:
            qmt_code = target_qmt_map.get(numeric, _to_qmt_code(numeric))
            price = price_dict.get(numeric, 0)
            name = _safe_get_stock_name(ContextInfo, qmt_code)
            if price <= 0:
                print('  [跳过] {:<14} {:<10} 价格缺失，无法计算买入数量'.format(qmt_code, name))
                continue

            shares = _calc_shares(qmt_code, cash_per_stock, price)
            if shares > 0:
                if hasattr(ContextInfo, 'accountID'):
                    order_shares(qmt_code, shares, 'fix', price, ContextInfo, ContextInfo.accountID)
                else:
                    order_shares(qmt_code, shares, 'fix', price, ContextInfo)
                value = shares * price
                weight_pct = value / total_asset * 100
                print('  [委托买入] {:<14} {:<10} {:>8d}股 × ¥{:>7.2f} = ¥{:>10,.2f}  占比{:.2f}%'.format(
                    qmt_code, name, shares, price, value, weight_pct))
                buy_order_count += 1
                buy_order_value += value
            else:
                min_hint = '200股(科创板)' if qmt_code.startswith('688') else '100股'
                print('  [跳过] {:<14} {:<10} 资金不足最小单位(预算¥{:.0f}/价¥{:.2f}={:.0f}股, 不足{})'.format(
                    qmt_code, name, cash_per_stock, price, cash_per_stock / price, min_hint))
        print('  ── 已委托买入: ' + str(buy_order_count) + ' 只, 预计投入 ¥{:>10,.2f}'.format(buy_order_value))
    else:
        print('  [执行买入] 无买入操作')

    # ═══════════════════════════════════════════
    #  9. ★ 调仓执行汇总 ★
    # ═══════════════════════════════════════════
    print('  ' + '=' * 56)
    print('  ★ 调仓执行汇总 ★')
    print('  ' + '-' * 56)
    print('  调仓日期:      ' + today_str)
    print('  预测数据:      ' + str(pred_date))
    print('  ' + '-' * 56)
    print('  目标持有:      ' + str(len(target_codes)) + ' 只')
    sell_count = len(sell_list)
    buy_count = buy_order_count
    print('  实际委托卖出:  ' + str(sell_order_count) + ' / ' + str(sell_count) + ' 只')
    print('  实际委托买入:  ' + str(buy_order_count) + ' / ' + str(len(buy_list)) + ' 只')
    print('  ' + '-' * 56)
    print('  预计卖出回收:  ¥{:>12,.2f}'.format(sell_order_value))
    print('  预计买入投入:  ¥{:>12,.2f}'.format(buy_order_value))
    net = sell_order_value - buy_order_value
    print('  资金净变动:    ¥{:>+12,.2f}'.format(net))
    after_asset = total_asset + net
    print('  预估调仓后资产:¥{:>12,.2f}'.format(after_asset))
    print('  ' + '-' * 56)
    keep_in_target = sum(1 for c in positions if c in target_numeric_set)
    print('  保留在目标池:  ' + str(keep_in_target) + ' 只')
    print('  调仓后预计:    ' + str(keep_in_target + buy_order_count) + ' 只持仓')
    print('  ' + '=' * 56)
    print('  [完成] ' + today_str + ' 调仓结束\n')

    # 仅在“实际有委托”或“本就无需调仓”时标记当天已调仓；
    # 若因价格缺失等导致零委托，允许当天后续 K 线重试补上
    if sell_order_count + buy_order_count > 0 or (not sell_list and not buy_list):
        ContextInfo.last_trade_day = today_str
    else:
        print('  [提示] 当日未产生有效委托，下根K线将重试')
