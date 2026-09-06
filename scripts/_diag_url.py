#!/usr/bin/env python3
import time
from pathlib import Path

import paramiko

ENV = Path(__file__).resolve().parent / ".env"
env: dict[str, str] = {}
for line in ENV.read_text(encoding="utf-8").splitlines():
    if line.strip() and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    env["SSH_HOST"],
    int(env["SSH_PORT"]),
    env["SSH_USER"],
    env["SSH_PASSWORD"],
    timeout=30,
    allow_agent=False,
    look_for_keys=False,
)

cmds = [
    "screen -wipe 2>/dev/null; screen -ls",
    "ps aux | grep studio/app | grep -v grep",
    "ss -tlnp 2>/dev/null | grep 6006 || true",
    "curl -s -I http://127.0.0.1:6006/ | head -5",
    f"grep UI_VERSION {remote}/studio/app.py | head -1",
    "tail -25 /tmp/studio_app.log 2>/dev/null || true",
    "cat /init/others/help 2>/dev/null | head -50",
    "grep -h . /etc/autodl*.json 2>/dev/null | head -30",
]

for cmd in cmds:
    print("====", cmd[:90])
    _, o, _ = c.exec_command(cmd, timeout=30)
    time.sleep(2)
    print(o.read().decode("utf-8", "replace")[:5000])

c.close()
