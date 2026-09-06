from pathlib import Path
import paramiko

env = {}
for line in (Path(__file__).resolve().parent / ".env").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
cmd = f"""
source /root/miniconda3/bin/activate
cd {remote}
echo '=== scripts ==='
ls data/scripts 2>/dev/null | head -30
ls data/scripts/*.json 2>/dev/null | wc -l
echo '=== videos ==='
ls data/raw_videos/*.mp4 2>/dev/null | wc -l
echo '=== disk ==='
df -h /root/autodl-tmp | tail -1
echo '=== modelscope ==='
pip show modelscope 2>/dev/null | head -3 || true
ls -la ~/.modelscope 2>/dev/null || true
python -c "import os; print('TOKEN', 'set' if os.environ.get('MODELSCOPE_API_TOKEN') or os.environ.get('MODELSCOPE_SDK_TOKEN') else 'missing')"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(
    env["SSH_HOST"],
    port=int(env["SSH_PORT"]),
    username=env["SSH_USER"],
    password=env["SSH_PASSWORD"],
    timeout=30,
    allow_agent=False,
    look_for_keys=False,
)
stdin, stdout, stderr = c.exec_command(cmd, timeout=60, get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
