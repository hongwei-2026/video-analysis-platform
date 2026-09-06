#!/usr/bin/env bash
# 云端一键环境：国内 pip 源 + 依赖 + 目录
set -euo pipefail

ROOT="${REMOTE_DIR:-/root/autodl-tmp/video-platform}"
MODEL_ROOT="/root/autodl-tmp/models"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PIP_TRUSTED="${PIP_TRUSTED:-pypi.tuna.tsinghua.edu.cn}"

source /root/miniconda3/bin/activate

mkdir -p "$ROOT" "$MODEL_ROOT" \
  "$ROOT/data/raw_videos" "$ROOT/data/scripts" \
  "$ROOT/logs"

cd "$ROOT"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
export MODELSCOPE_CACHE="$MODEL_ROOT"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"

echo "[1/3] pip install (清华源)"
pip install -U pip -i "$PIP_INDEX" --trusted-host "$PIP_TRUSTED"
pip install -r requirements.txt -i "$PIP_INDEX" --trusted-host "$PIP_TRUSTED"

# 确保 transformers 足够新以支持 Qwen2.5-VL
if ! python - <<'PY'
import transformers
print("transformers", transformers.__version__)
parts = [int(x) for x in transformers.__version__.split(".")[:2]]
raise SystemExit(0 if tuple(parts) >= (4, 57) else 1)
PY
then
  echo "[fix] transformers 偏旧，改从镜像装最新"
  pip install -U "transformers>=4.57.0" -i "$PIP_INDEX" --trusted-host "$PIP_TRUSTED" || \
    pip install -U transformers -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
fi

# flash-attn 可选；失败不阻断
echo "[2/3] optional flash-attn"
pip install flash-attn --no-build-isolation -i "$PIP_INDEX" --trusted-host "$PIP_TRUSTED" || \
  echo "[warn] flash-attn 安装失败，将使用 sdpa"

# ffmpeg
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[3/3] install ffmpeg"
  apt-get update -y && apt-get install -y ffmpeg || true
else
  echo "[3/3] ffmpeg ok: $(ffmpeg -version | head -1)"
fi

python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.cuda.is_available(), "vram_gb", round(torch.cuda.get_device_properties(0).total_memory/1024**3,2))
import modelscope, transformers
print("modelscope", modelscope.__version__, "transformers", transformers.__version__)
PY

echo "[ok] setup finished at $ROOT"
