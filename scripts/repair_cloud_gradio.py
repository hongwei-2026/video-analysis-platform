from pathlib import Path
import paramiko
import time

env = {}
for line in Path("scripts/.env").read_text(encoding="utf-8").splitlines():
    if line.strip() and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], int(env["SSH_PORT"]), env["SSH_USER"], env["SSH_PASSWORD"], timeout=30, allow_agent=False, look_for_keys=False)
cmd = f"""
/root/miniconda3/bin/pip uninstall -y gradio gradio-client 2>/dev/null || true
/root/miniconda3/bin/pip install 'gradio==6.26.0' -q
/root/miniconda3/bin/python -c 'import gradio as gr; print("gradio", gr.__version__)'
cd {remote}
screen -S studio -X quit 2>/dev/null || true
sleep 1
screen -dmS studio bash scripts/cloud_studio_daemon.sh
sleep 15
curl -s -I http://127.0.0.1:6006/ | head -3
tail -6 /tmp/studio_app.log
"""
_, o, e = c.exec_command(cmd, timeout=300)
time.sleep(60)
print(o.read().decode("utf-8", "replace"))
print(e.read().decode("utf-8", "replace")[-2000:])
c.close()
