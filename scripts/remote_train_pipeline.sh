#!/usr/bin/env bash
# 云端：批量拆解 → 构建 SFT → LoRA 训练
set -euo pipefail
source /root/miniconda3/bin/activate
ROOT="${REMOTE_DIR:-/root/autodl-tmp/video-platform}"
export PYTHONPATH="$ROOT"
cd "$ROOT"

PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
pip install -q datasets peft trl accelerate sentencepiece -i "$PIP_INDEX" || \
  pip install -q datasets peft accelerate sentencepiece -i "$PIP_INDEX"

mkdir -p data/scripts data/train models/script_lora logs

echo "[1/3] batch dissect"
# 跳过已存在；用 64 帧加速语料生产
python -m src.pipeline.batch_dissect --frames 64 2>&1 | tee logs/dissect.log

echo "[2/3] build sft"
python -m src.train.build_sft_dataset \
  --scripts data/scripts \
  --out data/train/sft.jsonl 2>&1 | tee logs/build_sft.log

N=$(wc -l < data/train/sft.jsonl || echo 0)
echo "sft lines=$N"
if [[ "$N" -lt 4 ]]; then
  echo "[fatal] 训练样本不足，拆解可能失败，见 logs/dissect.log"
  exit 2
fi

echo "[3/3] train lora"
python -m src.train.train_lora \
  --data data/train/sft.jsonl \
  --modelscope_id Qwen/Qwen2.5-1.5B-Instruct \
  --base_model /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct \
  --out /root/autodl-tmp/video-platform/models/script_lora \
  --epochs 4 \
  --batch_size 1 \
  --grad_accum 8 2>&1 | tee logs/train_lora.log

echo "[ok] adapter at models/script_lora/adapter"
ls -lah models/script_lora/adapter | head
