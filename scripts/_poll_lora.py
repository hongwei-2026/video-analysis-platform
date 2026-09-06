from pathlib import Path
import paramiko

env = {}
for line in (Path(__file__).resolve().parent / ".env").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], port=int(env["SSH_PORT"]), username=env["SSH_USER"], password=env["SSH_PASSWORD"], timeout=30, allow_agent=False, look_for_keys=False)
cmd = f"""
ps -p 459586 -o pid= 2>/dev/null || echo DEAD
ps aux | grep train_lora | grep -v grep || echo no_train
echo '---'
tail -40 {remote}/logs/train_only.out
echo '---adapter---'
ls -lah {remote}/models/script_lora/adapter 2>/dev/null | head || echo none
"""
stdin, stdout, stderr = c.exec_command(cmd, timeout=30, get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
