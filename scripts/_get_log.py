import paramiko
import time
from pathlib import Path

env = {}
for line in Path(__file__).resolve().parent.joinpath(".env").read_text(encoding="utf-8").splitlines():
    if line.strip() and "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], int(env["SSH_PORT"]), env["SSH_USER"], env["SSH_PASSWORD"], timeout=20, allow_agent=False, look_for_keys=False)
_, o, _ = c.exec_command("tail -60 /tmp/studio_app.log", timeout=30)
time.sleep(2)
print(o.read().decode("utf-8", "replace"))
c.close()
