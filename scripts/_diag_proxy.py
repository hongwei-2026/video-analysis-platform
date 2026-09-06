import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "connect.weste.seetacloud.com", 48396, "root", "lDceMezDApu7",
    timeout=30, allow_agent=False, look_for_keys=False,
)
cmds = [
    "cat /init/proxy/proxy.ini",
    "cat /init/others/help 2>/dev/null",
    "ls /init/bin/ 2>/dev/null",
    "which autodl 2>/dev/null; ls /usr/local/bin/ 2>/dev/null | head -20",
]
for cmd in cmds:
    print("====", cmd)
    _, o, _ = c.exec_command(cmd, get_pty=True, timeout=20)
    print(o.read().decode("utf-8", "replace"))
c.close()
