#!/usr/bin/env python3
"""验证 MiniMax API Key 是否可用（仅创建任务，不等待成片）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

env_path = ROOT / "scripts" / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from src.studio_pipeline.minimax_client import MiniMaxVideoClient


def main() -> int:
    key = os.environ.get("MINIMAX_API_KEY", "")
    if not key:
        print("FAIL: MINIMAX_API_KEY 未配置")
        return 1
    print(f"OK: 已读取 API Key（{key[:12]}...）")
    client = MiniMaxVideoClient()
    try:
        info = client.ping()
        print(f"OK: base={info['base_url']} task_id={info['task_id']} status={info['status']}")
        return 0
    except Exception as e:
        print(f"FAIL: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
