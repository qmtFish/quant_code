"""
策略基类 —— 模仿聚宽 API 风格。

用户通过继承 Strategy 并实现以下方法使用:
  - initialize(context)              # 策略初始化
  - before_trading_start(context)    # 每天开盘前
  - handle_data(context, data)       # 每天/每周交易时
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Callable, Any
from datetime import date, datetime
import pandas as pd
import json

from .core.context import Context
from .core.broker import Broker, CommissionModel, SlippageModel


class Strategy(ABC):
    """
    策略基类。

    用法:
        class MyStrategy(Strategy):
            def initialize(self, context):
                context.set_param('top_k', 10)

            def handle_data(self, context, data):
                ...
    """

    def __init__(self):
        self.name = self.__class__.__name__

    @abstractmethod
    def initialize(self, context: Context):
        """策略初始化（只执行一次）"""
        raise NotImplementedError

    def before_trading_start(self, context: Context):
        """每日开盘前执行"""
        pass

    def handle_data(self, context: Context, data: Any):
        """交易时执行"""
        pass


# ── 辅助函数（类似聚宽全局函数） ──

def set_benchmark(context: Context, benchmark_code: str):
    """设置基准"""
    context.benchmark_code = benchmark_code
    print(f"  [设置基准] {benchmark_code}")


def order_target_value(context: Context, code: str, target_value: float):
    """下单到目标市值（引擎内部通过 Broker 执行）"""
    # 引擎会在 broker 中处理
    pass


def get_security_info(code: str) -> object:
    """简化版股票信息查询"""
    return type('SecurityInfo', (), {
        'code': code,
        'display_name': code,
        'start_date': date(2000, 1, 1),
    })()


def read_file(path: str) -> str:
    """读取文件内容"""
    import os
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def log_info(msg: str, context: Context = None):
    """日志输出"""
    if context:
        dt = context.current_dt
        print(f"{dt.date() if dt else ''}  {msg}")
    else:
        print(f"  {msg}")
