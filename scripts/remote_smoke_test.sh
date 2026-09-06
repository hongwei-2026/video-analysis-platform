#!/usr/bin/env bash
# 生成一条短测试视频并跑通拆解（不依赖外网下载）
set -euo pipefail
source /root/miniconda3/bin/activate
ROOT="${REMOTE_DIR:-/root/autodl-tmp/video-platform}"
export PYTHONPATH="$ROOT"
cd "$ROOT"

TEST_MP4="$ROOT/data/raw_videos/_smoke_test.mp4"
mkdir -p "$(dirname "$TEST_MP4")"

if [[ ! -f "$TEST_MP4" ]]; then
  ffmpeg -y -f lavfi -i "color=c=blue:s=720x1280:d=6" \
    -f lavfi -i "sine=f=880:d=6" \
    -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$TEST_MP4"
fi

python -m src.pipeline.dissect_one \
  --video "$TEST_MP4" \
  --out "$ROOT/data/scripts/_smoke_test.json" \
  --frames 32

echo "[ok] smoke script:"
head -c 800 "$ROOT/data/scripts/_smoke_test.json" || true
echo
