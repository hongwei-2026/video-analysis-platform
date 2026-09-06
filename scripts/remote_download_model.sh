#!/usr/bin/env bash
# 从魔搭下载轻量模型：Qwen2.5-VL-3B + Qwen2.5-1.5B
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-$PWD}"
python - <<'PY'
from pathlib import Path
from modelscope import snapshot_download

root = Path.cwd()
jobs = [
    ("Qwen/Qwen2.5-VL-3B-Instruct", root / "models" / "Qwen2.5-VL-3B-Instruct"),
    ("Qwen/Qwen2.5-1.5B-Instruct", root / "models" / "Qwen2.5-1.5B-Instruct"),
]
for mid, dest in jobs:
    if (dest / "config.json").exists():
        print(f"[skip] {dest}")
        continue
    dest.mkdir(parents=True, exist_ok=True)
    print(f"[download] {mid}")
    snapshot_download(mid, local_dir=str(dest))
    print(f"[ok] {dest}")
PY
