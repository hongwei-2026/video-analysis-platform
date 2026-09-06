import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "connect.weste.seetacloud.com", 48396, "root", "lDceMezDApu7",
    timeout=20, allow_agent=False, look_for_keys=False,
)
cmds = [
    "ps aux | grep python | grep studio",
    "lsof -i:7860 2>/dev/null || fuser 7860/tcp 2>/dev/null",
    "curl -s -I http://127.0.0.1:7860/ 2>/dev/null | head -5",
    "tail -10 /tmp/studio_app.log",
]
for cmd in cmds:
    print("====", cmd)
    _, o, _ = c.exec_command(cmd, get_pty=True, timeout=15)
    print(o.read().decode("utf-8", "replace"))
c.close()
