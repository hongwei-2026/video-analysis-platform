#!/usr/bin/env python3
"""在云端后台下载 VL 模型。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

ENV = Path(__file__).resolve().parent / ".env"
ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main() -> int:
    env = load_env()
    remote = env["REMOTE_DIR"]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        env["SSH_HOST"],
        port=int(env["SSH_PORT"]),
        username=env["SSH_USER"],
        password=env["SSH_PASSWORD"],
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    cmd = f"""
cd {remote}
export PATH=/root/miniconda3/bin:$PATH
export PYTHONPATH={remote}
export VL_MODEL_DIR={remote}/models/Qwen2.5-VL-3B-Instruct
nohup python -u scripts/download_vl_model.py > /tmp/download_vl.log 2>&1 &
echo started
sleep 2
tail -5 /tmp/download_vl.log 2>/dev/null || true
"""
    _, stdout, _ = client.exec_command(cmd, timeout=30)
    time.sleep(3)
    print(stdout.read().decode("utf-8", "replace"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
