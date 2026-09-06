#!/usr/bin/env bash
# 修复语料 → 训练 → 产出 adapter
set -euo pipefail
source /root/miniconda3/bin/activate
ROOT="${REMOTE_DIR:-/root/autodl-tmp/video-platform}"
export PYTHONPATH="$ROOT"
cd "$ROOT"
mkdir -p logs data/scripts data/train models/script_lora data/clean_videos data/frames

PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
pip install -q datasets peft accelerate sentencepiece -i "$PIP_INDEX"

echo "[0] seed scripts from catalog"
python -m src.pipeline.seed_scripts --catalog data/catalog.json --out data/scripts

echo "[1] preprocess videos"
python -m src.pipeline.preprocess_videos --src data/raw_videos --out data/clean_videos --frames_dir data/frames --num_frames 24

echo "[2] frame dissect (best effort, continue on fail)"
set +e
python -m src.pipeline.dissect_frames --frames data/frames --max_images 16 2>&1 | tee logs/dissect_frames.log
set -e

echo "[3] build sft"
python -m src.train.build_sft_dataset --scripts data/scripts --out data/train/sft.jsonl
N=$(wc -l < data/train/sft.jsonl)
echo "sft lines=$N"
if [[ "$N" -lt 8 ]]; then
  echo "[fatal] still too few samples"
  exit 2
fi

echo "[4] train lora"
python -m src.train.train_lora \
  --data data/train/sft.jsonl \
  --modelscope_id Qwen/Qwen2.5-1.5B-Instruct \
  --base_model /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct \
  --out /root/autodl-tmp/video-platform/models/script_lora \
  --epochs 3 \
  --batch_size 1 \
  --grad_accum 8 2>&1 | tee logs/train_lora.log

echo "[ok] done"
ls -lah models/script_lora/adapter | head
