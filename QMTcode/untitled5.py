#coding:gbk
'''
回测模型示例（非实盘交易策略）

本策略根据计算滚动的.过去的30个bar的均值正负0.5个标准差得到布林线
并在最新价差上穿上轨来做空价差,下穿下轨来做多价差
并在回归至上下轨水平内的时候平仓
'''

import numpy as np

def init(ContextInfo):
	ContextInfo.trade_pair=['rb00.SF','hc00.SF']
	ContextInfo.position_tag = {'long':False,'short':False}         #初始化持仓状态
	ContextInfo.set_universe(ContextInfo.trade_pair) # 设置标的期货合约对应股票池
	ContextInfo.accid = '103427'

def handlebar(ContextInfo):
	index = ContextInfo.barpos
	bartimetag = ContextInfo.get_bar_timetag(index)
	print(timetag_to_datetime(bartimetag,'%Y-%m-%d %H:%M%S'))
	# 获取两个品种的收盘价时间序列
	closes=ContextInfo.get_market_data(['close'], stock_code=ContextInfo.trade_pair, period = ContextInfo.period, count=31)
	if closes.empty:
		return

	up_closes = closes[ContextInfo.trade_pair[0]]['close']
	down_closes = closes[ContextInfo.trade_pair[1]]['close']
	# 计算价差
	spread = up_closes[:-1] - down_closes[:-1]
	#spread=0
	# 计算布林带上下轨
	up = np.mean(spread) + 0.5 * np.std(spread)
	down = np.mean(spread) - 0.5 * np.std(spread)
	# 计算价差
	if (up_closes[-1] is None) or (down_closes[-1] is None):
		spread_now=0
	else:
		spread_now = up_closes[-1] - down_closes[-1]
		
	#无交易时若价差上(下)穿布林带上(下)轨则做空(多)价差
	position_up_long = ContextInfo.position_tag['long']
	position_up_short = ContextInfo.position_tag['short']
	if not position_up_long and not position_up_short:
		if spread_now > up:
			#开空code1，开多code2
			sell_open(ContextInfo.trade_pair[0],1,ContextInfo,ContextInfo.accid)
			buy_open(ContextInfo.trade_pair[1],1,ContextInfo,ContextInfo.accid)
			ContextInfo.position_tag['short'] = True
		if spread_now < down:
			#开多code1，开空code2
			buy_open(ContextInfo.trade_pair[0],1,ContextInfo,ContextInfo.accid)
			sell_open(ContextInfo.trade_pair[1],1,ContextInfo,ContextInfo.accid)
			ContextInfo.position_tag['long'] = True
	# 价差回归时平仓
	elif position_up_short:
		if spread_now <= up:
			#平空code1，平多code2
			buy_close_tdayfirst(ContextInfo.trade_pair[0],1,ContextInfo,ContextInfo.accid)
			sell_close_tdayfirst(ContextInfo.trade_pair[1],1,ContextInfo,ContextInfo.accid)
			ContextInfo.position_tag['short'] = False
		# 跌破下轨反向开仓
		if spread_now < down:
			#开多code1，开空code2
			buy_open(ContextInfo.trade_pair[0],1,ContextInfo,ContextInfo.accid)
			sell_open(ContextInfo.trade_pair[1],1,ContextInfo,ContextInfo.accid)
			ContextInfo.position_tag['long'] = True
	elif position_up_long:
		if spread_now >= down:
			#平多code1，平空code2
			sell_close_tdayfirst(ContextInfo.trade_pair[0],1,ContextInfo,ContextInfo.accid)
			buy_close_tdayfirst(ContextInfo.trade_pair[1],1,ContextInfo,ContextInfo.accid)
			ContextInfo.position_tag['long'] = False
		if spread_now > up:
			#开空code1，开多code2
			sell_open(ContextInfo.trade_pair[0],1,ContextInfo,ContextInfo.accid)
			buy_open(ContextInfo.trade_pair[1],1,ContextInfo,ContextInfo.accid)
			ContextInfo.position_tag['short'] = True

	ContextInfo.paint('short_spread',int(spread_now > up),-1,0,'noaxis')
	ContextInfo.paint('long_spread',int(spread_now < down),-1,0,'noaxis')

























