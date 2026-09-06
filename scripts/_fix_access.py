#!/usr/bin/env python3
"""诊断并修复云端 Studio 访问。"""
from __future__ import annotations

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

print(f"SSH -> {env['SSH_HOST']}:{env['SSH_PORT']}")
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    c.connect(
        env["SSH_HOST"],
        int(env["SSH_PORT"]),
        env["SSH_USER"],
        env["SSH_PASSWORD"],
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
except Exception as e:
    print(f"SSH 失败: {e}")
    print("实例可能已关机或 SSH 端口已变，请到 AutoDL 控制台查看新 SSH 连接信息。")
    raise SystemExit(1)

def run(cmd: str, wait: float = 2.0) -> str:
    print(f"\n>> {cmd}")
    _, o, e = c.exec_command(cmd, timeout=60)
    time.sleep(wait)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    if out.strip():
        print(out[:8000])
    if err.strip():
        print("stderr:", err[:2000])
    return out

# 重启 Studio
run("screen -wipe 2>/dev/null; screen -S studio -X quit 2>/dev/null; sleep 1; true")
run(
    f"cd {remote} && export PATH=/root/miniconda3/bin:$PATH && "
    "chmod +x scripts/cloud_studio_daemon.sh && "
    "screen -dmS studio bash scripts/cloud_studio_daemon.sh",
    wait=3,
)
time.sleep(10)
run("screen -ls")
run("ps aux | grep 'studio/app' | grep -v grep")
run("curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:6006/")
run("curl -s -I http://127.0.0.1:6006/ | head -6")
run(f"grep UI_VERSION {remote}/studio/app.py | head -1")
run("tail -8 /tmp/studio_app.log 2>/dev/null")

# 公网代理地址
help_txt = run("cat /init/others/help 2>/dev/null")
urls = []
for line in help_txt.splitlines():
    if "URL=" in line and "seetacloud" in line:
        urls.append(line.split("=", 1)[1].strip())

print("\n======== 访问地址 ========")
for u in urls:
    print(u)
if urls:
    primary = urls[0]
    run(f"curl -s -o /dev/null -w '%{{http_code}}' -k {primary}/ 2>/dev/null || curl -s -o /dev/null -w '%{{http_code}}' {primary}/")

c.close()
print("\n完成。请用上面 https://...:8443 地址访问（须含 https 和 :8443）。")
