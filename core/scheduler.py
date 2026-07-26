"""
调度器：管理 run_daily / run_weekly / run_monthly 注册的任务。
"""
from __future__ import annotations
from typing import Callable, List
from datetime import date, datetime
import pandas as pd


class Scheduler:
    """任务调度器，检查并执行已注册的定时任务。"""

    def __init__(self):
        self.tasks: List[dict] = []

    def register_tasks(self, tasks: List[dict]):
        self.tasks = tasks

    def get_due_tasks(self, current_dt: pd.Timestamp,
                      previous_date: date) -> List[Callable]:
        """
        返回当前应该执行的任务函数列表。
        """
        dt = current_dt
        if isinstance(dt, pd.Timestamp):
            dt = dt.to_pydatetime()
        today = dt.date()

        due = []
        for task in self.tasks:
            mode = task.get('mode')

            if mode == 'daily':
                # run_daily：每日执行（由 time 参数控制，这里简化到 just run once per day）
                due.append(task['func'])

            elif mode == 'weekly':
                weekday = task.get('weekday', 4)
                if today.weekday() == weekday:
                    due.append(task['func'])

            elif mode == 'monthly':
                monthday = task.get('monthday', 1)
                if today.day == monthday:
                    # 如果是非交易日，取上一个交易日
                    due.append(task['func'])

        return due
