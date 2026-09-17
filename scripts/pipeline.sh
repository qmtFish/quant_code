#!/usr/bin/env bash
# =============================================================================
# 量化因子回测 Pipeline
#   数据合并 → 因子数据 → Label(标签) → 训练 → 预测
# 依据飞书文档《交易系统的框架设计》:
#   https://my.feishu.cn/wiki/CNBxwzITgiIEbfkFeYRcmka5nHf
#
# 运行环境: Git Bash / WSL / Linux（需 python 及项目依赖）
#
# 用法:
#   bash scripts/pipeline.sh                          # 全流程，默认参数
#   START=2025-02-01 END=2026-06-12 MODEL=catboost WINDOW=180 \
#       bash scripts/pipeline.sh                      # 自定义日期/模型
#   bash scripts/pipeline.sh --skip-train             # 只跑到预测前（跳过训练）
#   bash scripts/pipeline.sh --step merge             # 只执行单个步骤
#     --step 可选: merge | factors | labels | train | predict
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ── 配置（环境变量可覆盖）──────────────────────────────────────────────
RAW_INPUT_DIR="${RAW_INPUT_DIR:-data/new_raw_data}"   # 新下载的原始数据目录（聚宽导出）
RAW_OUT_DIR="${RAW_OUT_DIR:-data/all_raw_data}"       # 合并后的原始数据目录
START="${START:-2025-02-01}"                          # 训练/预测起始日期
END="${END:-2026-06-12}"                              # 训练/预测结束日期
MODEL="${MODEL:-catboost}"                            # ols|ridge|lasso|rf|catboost
WINDOW="${WINDOW:-180}"                               # 滚动训练窗口（天）
OUTPUT_JSON="${OUTPUT_JSON:-coefficients/factor_coefficients_${WINDOW}d_${MODEL}.json}"
HORIZONS="${HORIZONS:-1,3,5,10}"                      # label 未来 N 日窗口
ZSCORE="${ZSCORE:-1}"                                 # 1=因子做截面 zscore（截断±5）
CATBOOST_ITER="${CATBOOST_ITER:-}"                    # 可选：catboost 迭代数（小范围验证调小）
STEP="${STEP:-all}"                                   # all | merge | factors | labels | train | predict

step() { echo; echo "════════════════════════════════════════════"; echo "  $1"; echo "════════════════════════════════════════════"; }

# 取目录下最新的 raw_stock_data 文件
latest_raw() { ls -t "$RAW_OUT_DIR"/raw_stock_data_*.csv 2>/dev/null | head -1 || true; }

# ── [1/5] 数据合并：new_raw_data(聚宽增量) → all_raw_data(全量) ────────
if [[ "$STEP" == "all" || "$STEP" == "merge" ]]; then
  step "[1/5] 合并原始数据: $RAW_INPUT_DIR -> $RAW_OUT_DIR"
  python scripts/merge_new_data.py -i "$RAW_INPUT_DIR" -o "$RAW_OUT_DIR"
fi
RAW_FILE="${RAW_FILE:-$(latest_raw)}"
if [[ -z "$RAW_FILE" || ! -f "$RAW_FILE" ]]; then
  echo "✗ 找不到原始数据文件（$RAW_OUT_DIR/raw_stock_data_*.csv）"; exit 1
fi
echo "  原始数据: $RAW_FILE"

# ── [2/5] 因子数据：factors/engine.py ─────────────────────────────────
# 注意: 不用 --drop-raw（会丢掉 industry 列，训练需要行业哑变量），
#       保留原始列 + 因子列，并做截面 zscore。
if [[ "$STEP" == "all" || "$STEP" == "factors" ]]; then
  step "[2/5] 生成因子数据: $(basename "$RAW_FILE")"
  ZS=""; [[ "$ZSCORE" == "1" ]] && ZS="--zscore"
  python factors/engine.py --input "$RAW_FILE" $ZS
fi
FACTOR_FILE="${FACTOR_FILE:-$(ls -t data/all_processed_data/factor_data_*.csv 2>/dev/null | head -1 || true)}"
if [[ -z "$FACTOR_FILE" || ! -f "$FACTOR_FILE" ]]; then
  echo "✗ 找不到因子数据文件（data/all_processed_data/factor_data_*.csv）"; exit 1
fi
echo "  因子数据: $FACTOR_FILE"

# ── [3/5] Label：labels/make_labels.py（按 date+code 合并进因子矩阵） ─
if [[ "$STEP" == "all" || "$STEP" == "labels" ]]; then
  step "[3/5] 生成标签并合并为训练集"
  python labels/make_labels.py --input "$RAW_FILE" \
      --merge "$FACTOR_FILE" --horizons "$HORIZONS" --placeholder
fi
TRAIN_FILE="${TRAIN_FILE:-${FACTOR_FILE%.csv}_labeled.csv}"
if [[ ! -f "$TRAIN_FILE" ]]; then
  echo "✗ 找不到训练集文件: $TRAIN_FILE"; exit 1
fi
echo "  训练集: $TRAIN_FILE"

# ── [4/5] 训练：scripts/train_unified.py ──────────────────────────────
if [[ "$STEP" == "all" || "$STEP" == "train" ]]; then
  step "[4/5] 训练: $MODEL | window=$WINDOW | $START ~ $END"
  EXTRA=()
  [[ -n "$CATBOOST_ITER" ]] && EXTRA+=(--catboost-iterations "$CATBOOST_ITER")
  python scripts/train_unified.py --model "$MODEL" --window "$WINDOW" \
      --start "$START" --end "$END" \
      --output "$OUTPUT_JSON" --force \
      --input "$TRAIN_FILE" "${EXTRA[@]}"
fi

# ── [5/5] 预测：python -m predictor ───────────────────────────────────
if [[ "$STEP" == "all" || "$STEP" == "predict" ]]; then
  step "[5/5] 预测: $START ~ $END ($MODEL)"
  python -m predictor --start "$START" --end "$END" \
      --model-type "$MODEL" --input "$TRAIN_FILE"
fi

echo
echo "✅ Pipeline 完成"
echo "   训练输出: $OUTPUT_JSON (+ .pkl)"
echo "   预测输出: data/results/ 下 ${MODEL}_*.json"
