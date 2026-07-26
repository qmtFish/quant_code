"""
统一因子模型 —— 动态加载 pipeline/models/ 下的模型插件。

支持的模型由 models/ 目录下的文件决定（当前: ols, ridge, lasso, rf, catboost）。

用法:
    from pipeline.model import FactorModel

    model = FactorModel({'window': 180, 'model_type': 'catboost'})
    model.train(df)
    scores = model.predict(df, coef_path='...json', date='2026-06-12')
"""
from __future__ import annotations
from typing import Dict, List, Optional
from pathlib import Path
from datetime import date
import json, time, warnings, pickle, importlib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, zscore

from pipeline.config import COEF_DIR
from pipeline.factor_config import FACTOR_COLS as DEFAULT_FACTOR_COLS

# ── 缓存已加载的模型模块 ──
_model_cache = {}


def _load_model_module(model_type: str):
    """动态加载 pipeline.models.{model_type} 模块"""
    if model_type not in _model_cache:
        _model_cache[model_type] = importlib.import_module(
            f'pipeline.models.{model_type}'
        )
    return _model_cache[model_type]


def _list_available_models() -> List[str]:
    """扫描 models/ 目录列出可用模型"""
    models_dir = Path(__file__).resolve().parent / 'models'
    return sorted(
        f.stem for f in models_dir.glob('*.py')
        if not f.stem.startswith('_')
    )


class FactorModel:
    """
    统一因子模型 —— 由 model_type 指定使用的模型插件。

    Args:
        config: {
            'window': 180,
            'model_type': 'ols',      # 对应 models/{name}.py
            'min_weeks': 4,
            'factor_cols': [...],
            'with_industry': True,
            'output_dir': 'coefficients/',
        }
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.window = self.config.get('window', 180)
        self.model_type = self.config.get('model_type', 'ols').lower()
        self.min_weeks = self.config.get('min_weeks', 4)
        self.factor_cols = self.config.get('factor_cols', DEFAULT_FACTOR_COLS)
        self.with_industry = self.config.get('with_industry', True)
        self.output_dir = Path(self.config.get('output_dir', str(COEF_DIR)))
        self._mod = _load_model_module(self.model_type)
        self._is_linear = self._mod.is_linear()

    @property
    def is_linear(self) -> bool:
        return self._is_linear

    @classmethod
    def available_models(cls) -> List[str]:
        return _list_available_models()

    # ═══════════════════════════════════════════════════════════
    # 训练
    # ═══════════════════════════════════════════════════════════

    def train(self, df: pd.DataFrame, output_path: str = None) -> str:
        if output_path is None:
            output_path = str(self.output_dir /
                              f'factor_coefficients_{self.window}d_{self.model_type}.json')
        self.output_dir.mkdir(parents=True, exist_ok=True)
        pkl_path = output_path.replace('.json', '.pkl')

        print("=" * 60)
        print(f"  [训练] {self.model_type.upper()} | 窗口={self.window}天")
        print("=" * 60)

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        dates = sorted(df['date'].unique())
        available = list(dict.fromkeys(
            c for c in self.factor_cols if c in df.columns
        ))
        print(f"  数据: {len(dates)} 截面, {len(available)} 个可用因子")

        self._fill_missing(df, available)
        X, y = self._build_features(df, available)

        output = []
        saved_models = {}
        n_total = 0
        t0 = time.time()

        for i, d in enumerate(dates):
            ws = d - pd.Timedelta(days=self.window)
            train_dates = [dt for dt in dates if ws <= dt < d]
            if len(train_dates) < self.min_weeks:
                continue

            # 过滤掉 next_ret == -1（无标签的占位值）的样本
            valid = y != -1
            train_mask = df['date'].isin(train_dates) & valid
            model_fn = self._mod.create(self.config.get(f'{self.model_type}_params'))
            self._mod.train(model_fn, X[train_mask], y[train_mask])

            factor_coefs = self._mod.extract_coefs(model_fn, available)

            test_mask = df['date'] == d
            ic, mse = 0.0, 0.0
            test_valid = test_mask & valid
            if test_valid.sum() >= 3:  # spearmanr 需要至少 3 个样本
                y_pred = self._mod.predict(model_fn, X[test_valid])
                y_true = y[test_valid]
                ic, _ = spearmanr(y_pred, y_true)
                mse = float(np.mean((y_true - y_pred) ** 2))

            output.append({
                "date": str(d.date()),
                "factor_coefficients": factor_coefs,
                "metrics": {"rank_ic": round(float(ic), 6), "mse": round(mse, 8)},
                "model_type": self.model_type,
            })

            if not self._is_linear:
                saved_models[str(d.date())] = model_fn

            n_total += 1
            if (i + 1) % 10 == 0 or i == len(dates) - 1:
                print(f"     [{i+1}/{len(dates)}] {d.date()}  IC={ic:.4f}  n_train={len(train_dates)}")

        elapsed = time.time() - t0

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        if not self._is_linear and saved_models:
            with open(pkl_path, 'wb') as f:
                pickle.dump(saved_models, f)
            print(f"  [PKL] {pkl_path} ({len(saved_models)} 期)")

        ics = [o['metrics']['rank_ic'] for o in output]
        print(f"\n  完成: {n_total} 期, {elapsed:.0f}s")
        print(f"  输出: {output_path}")
        print(f"  IC均值: {np.mean(ics):.4f}  IC>0比率: {np.mean([ic > 0 for ic in ics]):.2%}")
        return output_path

    # ═══════════════════════════════════════════════════════════
    # 预测
    # ═══════════════════════════════════════════════════════════

    def predict(self, df: pd.DataFrame,
                coef_path: str = None,
                date: date = None,
                industry_zscore: bool = True,
                model_type: str = None) -> pd.DataFrame:
        """
        Args:
            model_type: 模型类型，用于 PKL 预测时加载正确的模块。
                        默认从 JSON 元数据读取，回退到 self.model_type。
        """
        from pipeline.core.data_loader import load_latest_coefficients

        # ── 确定使用的模型类型 ──
        if model_type is None and coef_path and Path(coef_path).exists():
            try:
                with open(coef_path, 'r') as f:
                    meta = json.load(f)
                if isinstance(meta, list) and len(meta) > 0:
                    model_type = meta[0].get('model_type')
            except Exception:
                pass
        model_type = model_type or self.model_type
        mod = _load_model_module(model_type)

        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        if date is None:
            date = sorted(df['date'].unique())[-1]
        target_date = pd.Timestamp(date)
        td = target_date.date()

        cur = df[df['date'] == target_date].copy()
        if cur.empty:
            raise ValueError(f"日期 {date} 无数据")

        # ── 根据模型类型选择预测方式 ──
        if mod.is_linear():
            # 线性模型：JSON 系数打分
            coef_dict, coef_date = load_latest_coefficients(coef_path, td)
            if not coef_dict:
                raise FileNotFoundError(f"{coef_path} 中找不到 {td} 之前的可用权重")
            available = list(dict.fromkeys(
                c for c in self.factor_cols if c in cur.columns and c in coef_dict
            ))
            if not available:
                raise ValueError("无可用因子列与系数匹配")
            weights = pd.Series({c: coef_dict[c] for c in available})
            cur = cur.copy()
            cur['score'] = cur[available].fillna(0).dot(weights)
        else:
            # 非线性模型（树模型）：必须加载 PKL 全量模型
            pkl_path = coef_path.replace('.json', '.pkl')
            if not Path(pkl_path).exists():
                raise FileNotFoundError(
                    f"{model_type} 不是线性模型，需要 .pkl 文件但未找到: {pkl_path}\n"
                    f"请先用 model.train() 训练，或使用线性模型（ols/ridge/lasso）"
                )
            with open(pkl_path, 'rb') as f:
                saved_models = pickle.load(f)
            valid_dates = sorted([pd.Timestamp(d) for d in saved_models
                                  if pd.Timestamp(d).date() <= td])
            if not valid_dates:
                raise ValueError(f"{pkl_path} 中找不到 {td} 之前或当天的模型")
            best_dt = str(valid_dates[-1].date())
            model_fn = saved_models[best_dt]
            print(f"  [预测] {model_type} PKL: {best_dt}")

            available = list(dict.fromkeys(
                c for c in self.factor_cols if c in cur.columns
            ))
            if not available:
                raise ValueError("无可用的因子列")
            cur_filled = cur.copy()
            self._fill_missing(cur_filled, available)
            ind_dum_cur = pd.get_dummies(cur_filled['industry'], prefix='ind')
            all_ind_cols = [c for c in model_fn.feature_names_ if c.startswith('ind_')] \
                           if hasattr(model_fn, 'feature_names_') else []
            for c in all_ind_cols:
                if c not in ind_dum_cur.columns:
                    ind_dum_cur[c] = 0
            X_cur = np.concatenate([
                cur_filled[available].fillna(0).values,
                ind_dum_cur[all_ind_cols].values if all_ind_cols else ind_dum_cur.iloc[:, 1:].values,
            ], axis=1)
            cur = cur.copy()
            cur['score'] = mod.predict(model_fn, X_cur)

        result = pd.DataFrame({
            'code': cur['code'].values,
            'score': cur['score'].values,
            'industry': cur['industry'].values if 'industry' in cur.columns else None,
        })

        if industry_zscore and 'industry' in result.columns:
            result['score'] = result.groupby('industry', group_keys=False)['score'].transform(
                lambda x: zscore(x) if x.std() > 0 else x
            )

        result['rank_pct'] = result['score'].rank(pct=True)
        result = result.sort_values('score', ascending=False).reset_index(drop=True)
        return result

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _fill_missing(df: pd.DataFrame, cols: List[str]):
        for col in cols:
            na = df[col].isna()
            if isinstance(na, pd.DataFrame):
                # DataFrame 有重复列名时 isna() 返回 DataFrame
                if na.values.sum() == 0:
                    continue
            elif na.sum() == 0:
                continue
            fill_val = df.groupby(['date', 'industry'])[col].transform('mean')
            df[col] = df[col].fillna(fill_val).fillna(df[col].mean())

    @staticmethod
    def _build_features(df: pd.DataFrame, factor_cols: List[str]) -> tuple:
        X_factors = df[factor_cols].values
        y = df['next_ret'].values
        ind_dum = pd.get_dummies(df['industry'], prefix='ind').iloc[:, 1:]
        X = np.concatenate([X_factors, ind_dum.values], axis=1)
        return X, y
