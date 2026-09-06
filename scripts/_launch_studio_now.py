from pathlib import Path

import paramiko
import time

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "connect.weste.seetacloud.com", 48396, "root", "lDceMezDApu7",
    timeout=30, allow_agent=False, look_for_keys=False,
)

sh = Path(__file__).resolve().parent.joinpath("cloud_studio_daemon.sh").read_text(encoding="utf-8")
sftp = c.open_sftp()
with sftp.file("/tmp/cloud_studio_daemon.sh", "w") as f:
    f.write(sh.replace("\r\n", "\n"))
sftp.chmod("/tmp/cloud_studio_daemon.sh", 0o755)
sftp.close()

cmd = (
    "screen -S studio -X quit 2>/dev/null; "
    "screen -dmS studio /tmp/cloud_studio_daemon.sh; "
    "sleep 15; screen -ls; "
    "curl -s -I http://127.0.0.1:7860/ | head -3; "
    "tail -5 /tmp/studio_app.log 2>/dev/null; "
    "ps aux | grep 'python -u studio' | grep -v grep"
)
_, o, _ = c.exec_command(cmd, get_pty=True, timeout=40)
print(o.read().decode("utf-8", "replace"))
time.sleep(5)
_, o2, _ = c.exec_command("curl -s -I http://127.0.0.1:7860/ | head -3; ps aux | grep 'python -u studio' | grep -v grep", get_pty=True, timeout=15)
print("--- after disconnect check ---")
print(o2.read().decode("utf-8", "replace"))
c.close()
