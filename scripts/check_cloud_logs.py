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
for cmd in [
    "tail -100 /tmp/studio_app.log",
    "/root/miniconda3/bin/python -c 'import gradio as gr; print(gr.__version__)'",
    f"grep -n 'file_types\\|type=\\|elem_id' {remote}/studio/app.py | head -20",
]:
    print("===", cmd, "===")
    _, o, e = c.exec_command(cmd, timeout=20)
    time.sleep(2)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR:", err)
c.close()
