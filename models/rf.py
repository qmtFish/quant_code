"""Random Forest 随机森林"""
import numpy as np
from sklearn.ensemble import RandomForestRegressor


def create(config: dict = None):
    return RandomForestRegressor(
        n_estimators=200, max_depth=6,
        min_samples_leaf=50, n_jobs=-1, random_state=42,
    )


def train(model, X, y):
    model.fit(X, y)
    return model


def predict(model, X):
    return model.predict(X)


def extract_coefs(model, cols):
    imp = model.feature_importances_
    return {col: round(float(imp[j]), 8) for j, col in enumerate(cols)}


def is_linear():
    return False
