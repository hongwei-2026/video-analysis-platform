"""新云端：部署 + 启动 studio。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

ENV = Path(__file__).resolve().parent / ".env"
env: dict[str, str] = {}
for line in ENV.read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

token = env["GITCODE_TOKEN"]
work = "/root/autodl-tmp/shiping_shengce"
auth_repo = f"https://oauth2:{token}@gitcode.com/hongwei-2026/shiping_shengce.git"

setup = f"""#!/bin/bash
set -euo pipefail
export PATH=/root/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:$PATH
PY=$(command -v python3 || command -v python)
echo "PY=$PY"
nvidia-smi -L || echo "NO_GPU"
df -h /root/autodl-tmp 2>/dev/null | tail -1 || df -h / | tail -1

WORK="{work}"
AUTH_REPO="{auth_repo}"
mkdir -p /root/autodl-tmp

if [[ -d "$WORK/.git" ]]; then
  cd "$WORK" && git pull origin main || true
else
  rm -rf "$WORK"
  GIT_LFS_SKIP_SMUDGE=1 git clone "$AUTH_REPO" "$WORK"
fi
cd "$WORK"

# 安装 git-lfs（LoRA 需要）
if ! command -v git-lfs >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq git-lfs 2>/dev/null || true
fi
git lfs install
git lfs pull 2>/dev/null || true

# 下载轻量模型
if [[ ! -f models/Qwen2.5-1.5B-Instruct/config.json ]] || [[ ! -f models/Qwen2.5-VL-3B-Instruct/config.json ]]; then
  echo "[download models]"
  "$PY" scripts/download_models.py
fi

"$PY" -m pip install -q -r studio/requirements.txt

pkill -f 'studio/app.py' 2>/dev/null || true
sleep 1

export PYTHONPATH="$WORK"
export BASE_MODEL_DIR="$WORK/models/Qwen2.5-1.5B-Instruct"
export VL_MODEL_DIR="$WORK/models/Qwen2.5-VL-3B-Instruct"
export ADAPTER_DIR="$WORK/models/script_lora/adapter"
export PORT=7860

nohup "$PY" studio/app.py > /tmp/studio_app.log 2>&1 &
echo STUDIO_PID=$!
sleep 12
echo "=== log ==="
tail -n 40 /tmp/studio_app.log || true
echo "=== port ==="
ss -tlnp 2>/dev/null | grep 7860 || netstat -tlnp 2>/dev/null | grep 7860 || true
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print(f"connect {env['SSH_HOST']}:{env['SSH_PORT']}")
c.connect(
    env["SSH_HOST"],
    port=int(env["SSH_PORT"]),
    username=env["SSH_USER"],
    password=env["SSH_PASSWORD"],
    timeout=30,
    allow_agent=False,
    look_for_keys=False,
)
sftp = c.open_sftp()
with sftp.file("/tmp/run_studio.sh", "w") as f:
    f.write(setup.replace("\r\n", "\n"))
sftp.chmod("/tmp/run_studio.sh", 0o755)
sftp.close()

print("[cloud] deploy + start...")
_, o, _ = c.exec_command("bash /tmp/run_studio.sh 2>&1", get_pty=True, timeout=900)
# read in chunks
chan = o.channel
buf = b""
deadline = time.time() + 880
while time.time() < deadline:
    if chan.recv_ready():
        buf += chan.recv(65536)
    elif chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    else:
        time.sleep(2)
text = buf.decode("utf-8", "replace")
print(text[-10000:])
c.close()
