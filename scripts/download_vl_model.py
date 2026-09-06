#!/usr/bin/env python3
"""补全云端 Qwen2.5-VL-3B-Instruct 模型文件。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VL_DIR = Path(os.environ.get("VL_MODEL_DIR", str(ROOT / "models" / "Qwen2.5-VL-3B-Instruct")))
VL_ID = os.environ.get("VL_MODEL_ID", "Qwen/Qwen2.5-VL-3B-Instruct")


def main() -> int:
    VL_DIR.mkdir(parents=True, exist_ok=True)
    shard = VL_DIR / "model-00001-of-00002.safetensors"
    if shard.exists() and shard.stat().st_size > 1_000_000:
        print(f"ok: {shard}")
        return 0
    print(f"downloading {VL_ID} -> {VL_DIR}")
    try:
        from modelscope import snapshot_download

        snapshot_download(VL_ID, local_dir=str(VL_DIR))
    except Exception as e:
        print("modelscope failed:", e)
        from huggingface_hub import snapshot_download as hf_download

        hf_download(repo_id=VL_ID, local_dir=str(VL_DIR))
    print("done:", list(VL_DIR.glob("model-*.safetensors")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
