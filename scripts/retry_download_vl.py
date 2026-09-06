#!/usr/bin/env python3
"""检查云端磁盘并重新下载 VL 模型。"""
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


def run(client, cmd: str, timeout: int = 120) -> str:
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    time.sleep(1)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        out += "\nSTDERR:\n" + err
    return out


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

    print("=== disk ===")
    print(run(client, "df -h / /root/autodl-tmp 2>/dev/null; du -sh /root/autodl-tmp/shiping_shengce/models/* 2>/dev/null | head -10"))

    vl_dir = f"{remote}/models/Qwen2.5-VL-3B-Instruct"
    print("=== existing shards ===")
    print(run(client, f"ls -lh {vl_dir}/model-*.safetensors 2>/dev/null || echo '(none)'"))

    print("=== downloading VL model (background) ===")
    cmd = f"""
cd {remote}
export PATH=/root/miniconda3/bin:$PATH
export PYTHONPATH={remote}
export VL_MODEL_DIR={vl_dir}
nohup python -u scripts/download_vl_model.py > /tmp/download_vl.log 2>&1 &
echo pid=$!
"""
    print(run(client, cmd))

    print("waiting 30s...")
    time.sleep(30)
    print("=== download log tail ===")
    print(run(client, "tail -20 /tmp/download_vl.log 2>/dev/null"))

    print("=== shards after 30s ===")
    print(run(client, f"ls -lh {vl_dir}/model-*.safetensors 2>/dev/null || echo '(still downloading)'"))

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
