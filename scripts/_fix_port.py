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

# 不用 pkill，直接 screen 启动
transport = c.get_transport()
assert transport is not None
chan = transport.open_session()
chan.exec_command("screen -dmS studio /tmp/cloud_studio_daemon.sh")
chan.close()
print("started screen studio")
time.sleep(20)

_, o, _ = c.exec_command(
    "screen -ls; ps aux | grep 'python -u studio' | grep -v grep; "
    "curl -s -I http://127.0.0.1:6006/ | head -5; "
    "grep AutoDLService6006 /init/others/help",
    get_pty=True,
    timeout=30,
)
print(o.read().decode("utf-8", "replace"))
c.close()
