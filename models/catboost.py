"""CatBoost 回归"""
import numpy as np


def create(config: dict = None):
    from catboost import CatBoostRegressor
    params = {
        'iterations': 300, 'depth': 2, 'learning_rate': 0.1,
        'loss_function':'RMSE',      # 损失函数，回归任务常用'RMSE'
        'eval_metric':'RMSE',        # 评估指标
        'early_stopping_rounds':50,

        'min_data_in_leaf': 50, 'verbose': 40, 'random_seed': 42,
    }
    if config:
        params.update(config)
    return CatBoostRegressor(**params)


def train(model, X, y):
    model.fit(X, y)
    return model


def predict(model, X):
    return model.predict(X)


def extract_coefs(model, cols):
    try:
        imp = model.get_feature_importance()
        return {col: round(float(imp[j]), 8) for j, col in enumerate(cols)}
    except Exception:
        return {col: 0.0 for col in cols}


def is_linear():
    return False
