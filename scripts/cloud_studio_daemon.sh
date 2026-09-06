#!/bin/bash
cd /root/autodl-tmp/shiping_shengce
export PYTHONPATH=/root/autodl-tmp/shiping_shengce
export BASE_MODEL_DIR=/root/autodl-tmp/shiping_shengce/models/Qwen2.5-1.5B-Instruct
export VL_MODEL_DIR=/root/autodl-tmp/shiping_shengce/models/Qwen2.5-VL-3B-Instruct
export ADAPTER_DIR=/root/autodl-tmp/shiping_shengce/models/script_lora/adapter
if [ -f scripts/.env ]; then
  # 去掉 Windows CRLF，避免 URL 里残留 \r
  sed -i 's/\r$//' scripts/.env 2>/dev/null || true
  set -a
  # shellcheck disable=SC1091
  source scripts/.env
  set +a
fi
export PORT=6006
export GRADIO_ANALYTICS_ENABLED=False
export GRADIO_HEARTBEAT_INTERVAL=45
export GRADIO_WATCHDOG_TIMEOUT=3600
exec /root/miniconda3/bin/python -u studio/app.py > /tmp/studio_app.log 2>&1
