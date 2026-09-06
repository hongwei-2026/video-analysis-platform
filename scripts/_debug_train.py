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
ls -la {remote}/logs/ || true
wc -c {remote}/logs/pipeline.out 2>/dev/null || true
# children of pipeline
pstree -p 10229 2>/dev/null || ps --forest -g $(ps -o sid= -p 10229) 2>/dev/null || true
ps aux | grep -E '10229|pip|python|dissect' | grep -v grep | head -20
# try activate path
ls /root/miniconda3/bin/activate /root/miniconda3/bin/activate 2>&1 | head
"""
stdin, stdout, stderr = c.exec_command(cmd, timeout=30, get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
