"""
模型插件目录 —— 每个文件是一个独立模型，遵循统一接口。

接口规范:
    create(config: dict) -> model        # 创建新模型实例
    train(model, X, y) -> model          # 训练
    predict(model, X) -> np.ndarray      # 预测
    extract_coefs(model, cols) -> dict   # 提取系数/importance
    is_linear() -> bool                  # 是否线性（可用系数打分）
"""
