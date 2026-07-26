"""
聚宽策略 —— 与离线回测系统保持一致的版本。

改造点:
  1. 使用 factor_coefficients_6m_rolling.json（与离线系统相同）
  2. 因子计算逻辑与离线系统一致（全市场Z-Score + 27因子打分）
  3. 权重分配与离线系统的 PositionManager 一致（等权+上限约束）
  4. 调仓逻辑保持不变（先卖后买）

离线系统对应文件:
  - pipeline/model.py      → FactorModel.predict() 打分逻辑
  - pipeline/position_manager.py → generate_weights() 权重分配
  - coefficients/factor_coefficients_6m_rolling.json → 系数
"""
from jqdata import *
import pandas as pd
from pandas import Series, DataFrame
import numpy as np
import json
from datetime import datetime, timedelta
from scipy.stats import zscore

# ═══════════════════════════════════════════════════════════════
# 初始化
# ═══════════════════════════════════════════════════════════════

def initialize(context):
    set_params(context)
    set_variables()
    set_backtest()
    run_daily(before_trading_start, time='08:00', reference_security='000300.XSHG')

def set_params(context):
    g.security1 = '000300.XSHG'
    set_benchmark(g.security1)
    g.all_industries = list(get_industries('sw_l1', date=context.previous_date).index)

    # ── 与离线系统一致的参数 ──
    g.global_top_k = 10
    g.max_stock_weight = 0.10
    g.min_order_value = 1000

    # 使用与离线系统相同的系数文件（6个月滚动窗口）
    g.weight_file_path = "factor_coefficients_6m_rolling.json"
    g.current_coef_dict = {}
    g.current_coef_date = None
    g.optimized_weight = pd.Series(dtype=float)
    g.buy_list = []

def set_variables():
    g.last_selection_week = None

def set_backtest():
    set_option('use_real_price', True)
    set_option('order_volume_ratio', 1)
    log.set_level('order', 'error')

# ═══════════════════════════════════════════════════════════════
# 每天开盘前：加载系数 + 手续费
# ═══════════════════════════════════════════════════════════════

def before_trading_start(context):
    set_slip_fee(context)
    load_latest_factor_coefficients(context)

def load_latest_factor_coefficients(context):
    """与离线系统一致的系数加载逻辑"""
    current_date = context.current_dt.date()
    try:
        file_content = read_file(g.weight_file_path)
        weight_data = json.loads(file_content)
    except Exception as e:
        log.error(f"读取权重文件失败: {g.weight_file_path} | {e}")
        g.current_coef_dict = {}
        g.current_coef_date = None
        return

    records = weight_data if isinstance(weight_data, list) else \
              (weight_data.get('records') or weight_data.get('data') or [weight_data])

    candidates = []
    for record in records:
        if not isinstance(record, dict):
            continue
        # 提取系数（支持多种字段名）
        coef = (record.get('factor_coefficients')
                or record.get('coefficients')
                or record.get('weights')
                or {})
        if not isinstance(coef, dict) or len(coef) < 3:
            continue
        # 提取日期
        rec_date = None
        for k in ['date', 'trade_date', 'calc_date', 'train_end_date', 'end_date']:
            if k in record:
                try:
                    rec_date = pd.to_datetime(record[k]).date()
                    break
                except:
                    continue
        if rec_date is None:
            continue
        if rec_date < current_date:
            candidates.append((rec_date, coef))

    if not candidates:
        log.warn(f"{current_date} 之前没有可用权重")
        g.current_coef_dict = {}
        g.current_coef_date = None
        return

    candidates.sort(key=lambda x: x[0])
    latest_date, latest_coef = candidates[-1]

    # 清洗
    clean = {}
    for k, v in latest_coef.items():
        try:
            clean[str(k)] = float(v)
        except:
            continue

    g.current_coef_dict = clean
    g.current_coef_date = latest_date
    log.info(f"【权重】交易日={current_date} 使用={latest_date} 因子数={len(clean)}")

def set_slip_fee(context):
    """与离线系统一致的费用模型"""
    set_slippage(PriceRelatedSlippage(0.002))
    dt = context.current_dt
    if dt > datetime(2013, 1, 1):
        # 佣金万2.5 + 印花税千1 + 过户费万0.1
        set_commission(PerTrade(buy_cost=0.00025, sell_cost=0.00135, min_cost=5))
    else:
        set_commission(PerTrade(buy_cost=0.003, sell_cost=0.004, min_cost=5))

# ═══════════════════════════════════════════════════════════════
# 交易逻辑
# ═══════════════════════════════════════════════════════════════

def handle_data(context, data):
    current_date = context.current_dt.date()
    current_week_key = current_date.strftime("%Y-W%W")
    if g.last_selection_week == current_week_key:
        return
    if not getattr(g, "current_coef_dict", None):
        return

    # ── 1. 遍历所有行业，获取原始因子数据 ──
    all_stock_dfs = []
    for ind_code in g.all_industries:
        stocks_df = get_ranked_stocks_in_industry(context, ind_code)
        if stocks_df.empty:
            continue
        stocks_df["industry_code"] = ind_code
        all_stock_dfs.append(stocks_df)

    if len(all_stock_dfs) == 0:
        return

    # ── 2. 合并全市场 ──
    all_stocks_df = pd.concat(all_stock_dfs, axis=0, ignore_index=True)
    all_stocks_df = all_stocks_df.drop_duplicates(subset=["code"], keep="first").set_index("code")

    # ── 3. 全市场 Z-Score（与离线系统一致） ──
    base_factors = [
        "pe_ratio", "pb_ratio", "ps_ratio", "pcf_ratio", "market_cap",
        "roe", "roa", "gross_profit_margin", "net_profit_margin",
        "inc_revenue_year_on_year", "inc_net_profit_year_on_year",
        "ret_5d", "ret_20d", "ret_60d", "volatility_20d",
        "hl_range_5d", "vol_ma_ratio", "fair_price_deviation"
    ]
    market_factors = [
        "ind_ret_5d", "ind_ret_20d", "ind_vol_20d", "ind_alpha_20d",
        "hs300_ret_5d", "hs300_ret_20d", "zz500_ret_5d", "zz500_ret_20d"
    ]
    all_factors = base_factors + market_factors
    all_factors = [f for f in all_factors if f in all_stocks_df.columns]

    all_stocks_df[all_factors] = all_stocks_df[all_factors].replace(
        [np.inf, -np.inf], 0).fillna(0)

    # 全市场 Z-Score -> 创建 _z 列
    for f in base_factors:
        if f in all_stocks_df.columns:
            vals = all_stocks_df[f].values
            if np.std(vals) > 0:
                all_stocks_df[f + "_z"] = zscore(vals)
            else:
                all_stocks_df[f + "_z"] = 0.0

    # 市值对数 Z-Score
    if "circulating_market_cap" in all_stocks_df.columns:
        mc = all_stocks_df["circulating_market_cap"].values
        if np.std(mc) > 0:
            all_stocks_df["size_log_z"] = zscore(-np.log(np.abs(mc) + 1e-6))
        else:
            all_stocks_df["size_log_z"] = 0.0

    # ── 4. 匹配系数，打分（与离线系统完全一致） ──
    raw_coef_dict = g.current_coef_dict
    # 系数的 key 是 pe_ratio_z 这种格式，直接匹配
    valid_coef = {k: v for k, v in raw_coef_dict.items() if k in all_stocks_df.columns}

    if not valid_coef:
        log.warn(f"{current_date} 无有效因子匹配")
        return

    # X @ w（与 pipeline/model.py 的 predict() 一致）
    all_stocks_df["score"] = all_stocks_df[list(valid_coef.keys())].dot(
        pd.Series(valid_coef))

    all_stocks_df = all_stocks_df.replace([np.inf, -np.inf], np.nan).dropna(subset=["score"])

    # ── 5. 选股（与离线 PositionManager 一致） ──
    # 过滤 score > -1，取 Top K
    selected_df = all_stocks_df[all_stocks_df["score"] > -1] \
        .sort_values("score", ascending=False).head(g.global_top_k).copy()
    final_buy_list = selected_df.index.tolist()

    if len(final_buy_list) == 0:
        log.warn(f"{current_date} 无符合条件的股票")
        return

    # ── 6. 权重分配（等权 + 上限约束，与离线一致） ──
    n = len(final_buy_list)
    raw_w = min(1.0 / n, g.max_stock_weight)
    stock_weights = pd.Series(raw_w, index=final_buy_list, dtype=float)
    # 归一化
    stock_weights = stock_weights / stock_weights.sum()

    g.buy_list = stock_weights.index.tolist()
    g.last_selection_week = current_week_key
    g.optimized_weight = stock_weights

    log.info(f"【换仓】{current_date} | 全市场{len(all_stocks_df)}只 "
             f"→ 持股{len(g.buy_list)}只 | 系数日期{g.current_coef_date}")

    # 打印 Top 明细
    log.info("【Top 股票】")
    for stock, row in selected_df.iterrows():
        try:
            name = get_security_info(stock).display_name
        except:
            name = stock
        w = stock_weights.get(stock, 0) * 100
        log.info(f"  {stock} ({name}) | w={w:.1f}% | score={row['score']:.4f}")

    # ── 7. 调仓 ──
    old_snapshot = {s: p.value for s, p in context.portfolio.positions.items() if p.value > 0}
    old_total = context.portfolio.total_value
    rebalance(context, g.buy_list, g.optimized_weight)
    print_rebalance_changes(context, old_snapshot, old_total)

# ═══════════════════════════════════════════════════════════════
# 因子计算（与离线 factor_builder.py 一致）
# ═══════════════════════════════════════════════════════════════

def get_ranked_stocks_in_industry(context, industry_code):
    """
    获取行业内股票的原始因子值（不做 Z-Score）。
    与 scripts/factor_builder.py 的 build_factor_df 一致。
    """
    calc_date = context.previous_date
    stocks = get_industry_stocks(industry_code, date=calc_date)
    current_date = context.current_dt.date()

    # 过滤：上市满1年、非ST、非停牌
    valid_stocks = []
    curr_data = get_current_data()
    for stock in stocks:
        try:
            info = get_security_info(stock)
            if (current_date - info.start_date).days < 365:
                continue
            data = curr_data[stock]
            if data.paused or data.is_st:
                continue
            if 'ST' in data.name or '*' in data.name or '退' in data.name:
                continue
            valid_stocks.append(stock)
        except:
            continue

    if not valid_stocks:
        return pd.DataFrame()

    # 基本面因子
    q = query(
        valuation.code, valuation.pe_ratio, valuation.pb_ratio,
        valuation.ps_ratio, valuation.pcf_ratio,
        valuation.market_cap, valuation.circulating_market_cap,
        indicator.roe, indicator.roa,
        indicator.gross_profit_margin, indicator.net_profit_margin,
        indicator.inc_revenue_year_on_year, indicator.inc_net_profit_year_on_year
    ).filter(valuation.code.in_(valid_stocks))

    df = get_fundamentals(q, date=calc_date).fillna(0)
    if df.empty:
        return pd.DataFrame()
    df = df.set_index("code")

    # 量价因子
    try:
        # 指数行情
        mkt = get_price(['000300.XSHG', '000905.XSHG'], count=60,
                        end_date=calc_date, fields=['close'], panel=False)
        mkt_pivot = mkt.pivot(index='time', columns='code', values='close')

        hs300_r5 = mkt_pivot['000300.XSHG'].iloc[-1] / mkt_pivot['000300.XSHG'].iloc[-5] - 1
        hs300_r20 = mkt_pivot['000300.XSHG'].iloc[-1] / mkt_pivot['000300.XSHG'].iloc[-20] - 1
        zz500_r5 = mkt_pivot['000905.XSHG'].iloc[-1] / mkt_pivot['000905.XSHG'].iloc[-5] - 1
        zz500_r20 = mkt_pivot['000905.XSHG'].iloc[-1] / mkt_pivot['000905.XSHG'].iloc[-20] - 1

        # 个股行情
        hist = get_price(valid_stocks, count=120, end_date=calc_date,
                         fields=["open", "high", "low", "close", "volume"], panel=False)
        if hist.empty:
            return pd.DataFrame()

        close_p = hist.pivot(index="time", columns="code", values="close")
        high_p = hist.pivot(index="time", columns="code", values="high")
        low_p = hist.pivot(index="time", columns="code", values="low")
        vol_p = hist.pivot(index="time", columns="code", values="volume")

        common = list(set(df.index) & set(close_p.columns))
        if len(common) == 0:
            return pd.DataFrame()

        df = df.loc[common]
        close_p = close_p[common]; high_p = high_p[common]
        low_p = low_p[common]; vol_p = vol_p[common]

        if close_p.shape[0] < 60:
            return pd.DataFrame()

        last_close = close_p.iloc[-1]
        ret = close_p.pct_change().fillna(0)

        df["ret_5d"] = close_p.iloc[-1] / close_p.iloc[-5] - 1
        df["ret_20d"] = close_p.iloc[-1] / close_p.iloc[-20] - 1
        df["ret_60d"] = close_p.iloc[-1] / close_p.iloc[-60] - 1
        df["volatility_20d"] = ret.iloc[-20:].std()
        df["hl_range_5d"] = (high_p.iloc[-5:].max() - low_p.iloc[-5:].min()) / (last_close + 1e-6)
        df["vol_ma_ratio"] = vol_p.iloc[-5:].mean() / (vol_p.iloc[-20:].mean() + 1e-6)
        df["fair_price_deviation"] = (close_p.median() - last_close) / (close_p.std() + 1e-6)

        ind_ret_ts = ret.iloc[-20:].mean(axis=1)
        df["ind_ret_5d"] = (ind_ret_ts.iloc[-5:] + 1).prod() - 1
        df["ind_ret_20d"] = (ind_ret_ts.iloc[-20:] + 1).prod() - 1
        df["ind_vol_20d"] = ind_ret_ts.iloc[-20:].std()
        df["ind_alpha_20d"] = df["ind_ret_20d"] - hs300_r20

        df["hs300_ret_5d"] = hs300_r5
        df["hs300_ret_20d"] = hs300_r20
        df["zz500_ret_5d"] = zz500_r5
        df["zz500_ret_20d"] = zz500_r20

    except Exception as e:
        log.error(f"行业 [{industry_code}] 因子计算失败: {e}")
        return pd.DataFrame()

    df = df.reset_index()
    return df

# ═══════════════════════════════════════════════════════════════
# 调仓执行 + 日志（与离线 PositionManager 一致）
# ═══════════════════════════════════════════════════════════════

def rebalance(context, holding_list, optimized_weight):
    """先卖后买，满仓多头"""
    if not holding_list:
        return
    holding_list = list(dict.fromkeys(holding_list))
    holding_set = set(holding_list)

    portfolio_value = context.portfolio.total_value
    positions = context.portfolio.positions

    raw_weights = {}
    for stock in holding_list:
        try:
            w = float(optimized_weight.get(stock, 0.0))
        except:
            w = 0.0
        if w > 0:
            raw_weights[stock] = w
    if not raw_weights:
        return
    w_sum = float(np.sum(list(raw_weights.values())))
    if w_sum <= 0:
        return

    target_values = {s: portfolio_value * (w / w_sum) for s, w in raw_weights.items()}
    current_values = {s: p.value for s, p in positions.items() if p.value > 0}

    # 先清仓不在目标池的
    for stock in list(current_values.keys()):
        if stock not in holding_set:
            order_target_value(stock, 0)
    # 减仓
    for stock, tv in target_values.items():
        cv = current_values.get(stock, 0.0)
        if cv > tv and abs(cv - tv) >= g.min_order_value:
            order_target_value(stock, tv)
    # 加仓/新买入
    for stock, tv in target_values.items():
        if tv < g.min_order_value:
            continue
        cv = current_values.get(stock, 0.0)
        if tv > cv and abs(tv - cv) >= g.min_order_value:
            order_target_value(stock, tv)

def print_rebalance_changes(context, old_snapshot, old_total):
    """与离线 position_manager.print_position_report 一致"""
    new_total = context.portfolio.total_value
    new_snapshot = {s: p.value for s, p in context.portfolio.positions.items() if p.value > 0}

    old_set = set(old_snapshot.keys())
    new_set = set(new_snapshot.keys())

    ret = new_total / context.portfolio.initial_cash - 1
    log.info(f"============ 调仓完成 资产:{new_total:.0f} 收益:{ret:.2%} ============")

    sell_out = old_set - new_set
    if sell_out:
        log.info("【清仓】" + "  ".join(s[:6] for s in list(sell_out)[:8]))

    buy_in = new_set - old_set
    if buy_in:
        log.info("【新买入】" + "  ".join(s[:6] for s in list(buy_in)[:8]))

    common = old_set & new_set
    for s in common:
        old_r = old_snapshot[s] / old_total * 100
        new_r = new_snapshot[s] / new_total * 100
        diff = new_r - old_r
        if abs(diff) > 0.1:
            try:
                name = get_security_info(s).display_name[:4]
            except:
                name = s[:6]
            action = "加仓" if diff > 0 else "减仓"
            log.info(f"  [{action}] {s} ({name}) {old_r:.1f}%→{new_r:.1f}% ({diff:+.1f}%)")
