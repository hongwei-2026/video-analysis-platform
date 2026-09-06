#!/usr/bin/env python3
from __future__ import annotations

import time
from pathlib import Path

import paramiko

ENV = Path(__file__).resolve().parent / ".env"


def main() -> int:
    env = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    vl = f"{env['REMOTE_DIR']}/models/Qwen2.5-VL-3B-Instruct"
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        env["SSH_HOST"],
        port=int(env["SSH_PORT"]),
        username=env["SSH_USER"],
        password=env["SSH_PASSWORD"],
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    for i in range(15):
        _, o, _ = c.exec_command(
            f"ls -lh {vl}/model-*.safetensors 2>/dev/null; "
            f"tail -2 /tmp/download_vl.log 2>/dev/null; "
            f"pgrep -f download_vl_model.py >/dev/null && echo RUNNING || echo DONE"
        )
        time.sleep(2)
        out = o.read().decode("utf-8", "replace")
        print(f"--- poll {i + 1} ---\n{out}")
        if "DONE" in out and "model-00001-of-00002.safetensors" in out:
            break
        time.sleep(30)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
