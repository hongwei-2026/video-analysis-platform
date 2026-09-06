"""新云端：用已有 1.5B 权重，继续下 VL-3B 并启动 studio。"""
import paramiko
import time

HOST, PORT, USER, PWD = "connect.weste.seetacloud.com", 48396, "root", "lDceMezDApu7"
WORK = "/root/autodl-tmp/shiping_shengce"

sh = f"""#!/bin/bash
set -euo pipefail
export PATH=/root/miniconda3/bin:$PATH
PY=/root/miniconda3/bin/python

# 停掉卡住的部署
pkill -f download_models.py 2>/dev/null || true
pkill -f run_studio.sh 2>/dev/null || true
sleep 2

cd {WORK}
mkdir -p models

# 复用克隆容器里已有的 1.5B（省 ~3GB 下载）
if [[ -f /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct/model.safetensors ]]; then
  rm -rf models/Qwen2.5-1.5B-Instruct
  ln -sfn /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct models/Qwen2.5-1.5B-Instruct
  echo "[link] 1.5B ok"
fi

# 只下 VL-3B（若未完成）
if [[ ! -f models/Qwen2.5-VL-3B-Instruct/model.safetensors ]] && [[ ! -f models/Qwen2.5-VL-3B-Instruct/model-00001-of-00002.safetensors ]]; then
  rm -rf models/Qwen2.5-VL-3B-Instruct
  echo "[download] VL-3B only"
  "$PY" - <<'PY'
from pathlib import Path
from modelscope import snapshot_download
dest = Path("{WORK}/models/Qwen2.5-VL-3B-Instruct")
dest.mkdir(parents=True, exist_ok=True)
snapshot_download("Qwen/Qwen2.5-VL-3B-Instruct", local_dir=str(dest))
print("[ok]", dest)
PY
else
  echo "[skip] VL exists or downloading"
fi

"$PY" -m pip install -q -r studio/requirements.txt

pkill -f 'studio/app.py' 2>/dev/null || true
sleep 1

export PYTHONPATH="{WORK}"
export BASE_MODEL_DIR="{WORK}/models/Qwen2.5-1.5B-Instruct"
export VL_MODEL_DIR="{WORK}/models/Qwen2.5-VL-3B-Instruct"
export ADAPTER_DIR="{WORK}/models/script_lora/adapter"
export PORT=7860

nohup "$PY" studio/app.py > /tmp/studio_app.log 2>&1 &
echo STUDIO_PID=$!
sleep 15
tail -n 35 /tmp/studio_app.log
netstat -tlnp 2>/dev/null | grep 7860 || true
df -h /root/autodl-tmp | tail -1
"""

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, PORT, USER, PWD, timeout=30, allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
with sftp.file("/tmp/start_studio2.sh", "w") as f:
    f.write(sh)
sftp.chmod("/tmp/start_studio2.sh", 0o755)
sftp.close()

print("[start] optimized deploy...")
chan = c.get_transport().open_session()
chan.get_pty()
chan.exec_command("bash /tmp/start_studio2.sh 2>&1")
buf = b""
t0 = time.time()
while time.time() - t0 < 600:
    if chan.recv_ready():
        buf += chan.recv(65536)
        if b"STUDIO_PID" in buf and b"Running on" in buf:
            break
    elif chan.exit_status_ready():
        while chan.recv_ready():
            buf += chan.recv(65536)
        break
    time.sleep(3)
print(buf.decode("utf-8", "replace")[-8000:])
c.close()
