#!/usr/bin/env python3
"""检查云端 Studio 状态。"""
from pathlib import Path
import paramiko
import time

ENV = Path(__file__).resolve().parent / ".env"
env = {}
for line in ENV.read_text(encoding="utf-8").splitlines():
    if line.strip() and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], int(env["SSH_PORT"]), env["SSH_USER"], env["SSH_PASSWORD"], timeout=30, allow_agent=False, look_for_keys=False)
_, o, _ = c.exec_command(
    f"grep UI_VERSION {remote}/studio/app.py; screen -ls; curl -s -I http://127.0.0.1:6006/ | head -2; tail -5 /tmp/studio_app.log",
    timeout=30,
)
time.sleep(3)
print(o.read().decode("utf-8", "replace"))
c.close()
