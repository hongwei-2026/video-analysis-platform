from pathlib import Path
import paramiko

env = {}
for line in Path(__file__).resolve().parent.joinpath(".env").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], port=int(env["SSH_PORT"]), username=env["SSH_USER"], password=env["SSH_PASSWORD"], timeout=30, allow_agent=False, look_for_keys=False)

for f in ["train_lora.log", "fix_train.out"]:
    print("====", f)
    stdin, stdout, stderr = c.exec_command(f"cat {remote}/logs/{f}", get_pty=True, timeout=30)
    print(stdout.read().decode("utf-8", errors="replace")[-3000:])
    print()

# Try foreground short start to capture error
cmd = f"""
cd {remote}
export PYTHONPATH={remote}
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
/root/miniconda3/bin/python -m src.train.train_lora \
  --data data/train/sft.jsonl \
  --modelscope_id Qwen/Qwen2.5-1.5B-Instruct \
  --base_model /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct \
  --out {remote}/models/script_lora \
  --epochs 3 --batch_size 1 --grad_accum 4 --max_len 768 \
  > {remote}/logs/train_only.out 2>&1
echo EXIT=$?
tail -100 {remote}/logs/train_only.out
"""
print("==== starting train in background via bash -lc")
# Write a start script remotely
start_sh = f"""#!/bin/bash
cd {remote}
export PYTHONPATH={remote}
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
exec /root/miniconda3/bin/python -m src.train.train_lora \
  --data data/train/sft.jsonl \
  --modelscope_id Qwen/Qwen2.5-1.5B-Instruct \
  --base_model /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct \
  --out {remote}/models/script_lora \
  --epochs 3 --batch_size 1 --grad_accum 4 --max_len 768
"""
sftp = c.open_sftp()
with sftp.file(f"{remote}/logs/run_train.sh", "w") as f:
    f.write(start_sh)
sftp.chmod(f"{remote}/logs/run_train.sh", 0o755)

# sync local train_lora.py first
local_train = Path(r"D:\视频分析平台\src\train\train_lora.py")
sftp.put(str(local_train), f"{remote}/src/train/train_lora.py")
print("synced train_lora.py")
sftp.close()

stdin, stdout, stderr = c.exec_command(
    f"nohup bash {remote}/logs/run_train.sh > {remote}/logs/train_only.out 2>&1 & echo PID=$!; sleep 8; wc -l {remote}/logs/train_only.out; head -80 {remote}/logs/train_only.out; ps aux | grep train_lora | grep -v grep",
    get_pty=True,
    timeout=60,
)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
