from pathlib import Path
import paramiko
import time

env = {}
for line in Path("scripts/.env").read_text(encoding="utf-8").splitlines():
    if line.strip() and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], int(env["SSH_PORT"]), env["SSH_USER"], env["SSH_PASSWORD"], timeout=30, allow_agent=False, look_for_keys=False)
cmd = """
/root/miniconda3/bin/pip install 'gradio==4.44.1' -q
/root/miniconda3/bin/python -c 'import gradio as gr; print(gr.__version__)'
cd /root/autodl-tmp/shiping_shengce
screen -S studio -X quit 2>/dev/null || true
sleep 2
screen -dmS studio bash scripts/cloud_studio_daemon.sh
sleep 12
curl -s -I http://127.0.0.1:6006/ | head -3
tail -8 /tmp/studio_app.log
"""
_, o, e = c.exec_command(cmd, timeout=180)
time.sleep(90)
print(o.read().decode("utf-8", "replace"))
print(e.read().decode("utf-8", "replace"))
c.close()
