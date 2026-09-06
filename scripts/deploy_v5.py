from pathlib import Path
import paramiko
import time

env = {}
for line in Path("scripts/.env").read_text(encoding="utf-8").splitlines():
    if line.strip() and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
files = [
    "studio/app.py",
    "studio/ui_helpers.py",
    "scripts/cloud_studio_daemon.sh",
    "src/studio_pipeline/orchestrator.py",
]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], int(env["SSH_PORT"]), env["SSH_USER"], env["SSH_PASSWORD"], timeout=30, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
for f in files:
    print("upload", f)
    sftp.put(f, f"{remote}/{f}")
sftp.close()

cmd = f"""
cd {remote}
chmod +x scripts/cloud_studio_daemon.sh
screen -S studio -X quit 2>/dev/null || true
sleep 2
screen -dmS studio bash scripts/cloud_studio_daemon.sh
sleep 25
/root/miniconda3/bin/python -c 'import gradio as gr; print(gr.__version__)'
grep UI_VERSION studio/app.py | head -1
curl -s -I http://127.0.0.1:6006/ | head -2
tail -6 /tmp/studio_app.log
"""
_, o, _ = c.exec_command(cmd, timeout=120)
time.sleep(30)
print(o.read().decode("utf-8", "replace"))
c.close()
