"""Lasso 回归"""
from sklearn.linear_model import Lasso


def create(config: dict = None):
    return Lasso(alpha=0.001, random_state=42, max_iter=2000)


def train(model, X, y):
    model.fit(X, y)
    return model


def predict(model, X):
    return model.predict(X)


def extract_coefs(model, cols):
    return {col: round(float(model.coef_[j]), 8) for j, col in enumerate(cols)}


def is_linear():
    return True
