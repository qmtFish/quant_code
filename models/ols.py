"""OLS 线性回归"""
import numpy as np
from sklearn.linear_model import LinearRegression


def create(config: dict = None):
    return LinearRegression(n_jobs=-1)


def train(model, X, y):
    model.fit(X, y)
    return model


def predict(model, X):
    return model.predict(X)


def extract_coefs(model, cols):
    return {col: round(float(model.coef_[j]), 8) for j, col in enumerate(cols)}


def is_linear():
    return True
