import paramiko

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    "connect.weste.seetacloud.com",
    port=48396,
    username="root",
    password="lDceMezDApu7",
    timeout=20,
    allow_agent=False,
    look_for_keys=False,
)
cmds = [
    "du -sh /root/autodl-tmp/shiping_shengce/models/*",
    "ls -lh /root/autodl-tmp/shiping_shengce/models/Qwen2.5-1.5B-Instruct/model.safetensors 2>&1",
    "ls /root/autodl-tmp/shiping_shengce/models/Qwen2.5-VL-3B-Instruct/ 2>&1 | head -10",
    "ps aux | grep download_models | grep -v grep",
    "ps aux | grep studio | grep -v grep",
    "tail -30 /tmp/studio_app.log 2>&1",
    "netstat -tlnp 2>/dev/null | grep 7860 || true",
    "df -h /root/autodl-tmp | tail -1",
]
for cmd in cmds:
    print("====", cmd)
    _, o, _ = c.exec_command(cmd, get_pty=True, timeout=30)
    print(o.read().decode("utf-8", "replace"))
c.close()
