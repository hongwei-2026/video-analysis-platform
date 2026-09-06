import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "connect.weste.seetacloud.com", 48396, "root", "lDceMezDApu7",
    timeout=30, allow_agent=False, look_for_keys=False,
)
cmds = [
    "screen -ls",
    "ps aux | grep 'studio/app' | grep -v grep",
    "ps aux | grep 'python -u studio' | grep -v grep",
    "curl -s -I http://127.0.0.1:7860/ 2>&1 | head -8",
    "curl -s -I http://0.0.0.0:7860/ 2>&1 | head -5",
    "netstat -tlnp 2>/dev/null | grep 7860 || ss -tlnp 2>/dev/null | grep 7860 || lsof -i:7860 2>/dev/null",
    "tail -30 /tmp/studio_app.log 2>/dev/null",
    "cat /etc/autodl*.json 2>/dev/null; ls /init/ 2>/dev/null | head",
    "env | grep -i proxy; env | grep -i port",
]
for cmd in cmds:
    print("====", cmd[:70])
    _, o, e = c.exec_command(cmd, get_pty=True, timeout=20)
    print(o.read().decode("utf-8", "replace")[:3000])
c.close()
