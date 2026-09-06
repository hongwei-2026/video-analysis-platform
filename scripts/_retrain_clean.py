from pathlib import Path
import time
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

# kill GPU procs
for cmd in [
    "nvidia-smi --query-compute-apps=pid --format=csv,noheader",
    "pkill -9 -f train_lora || true",
    "pkill -9 -f batch_dissect || true",
    "pkill -9 -f dissect_frames || true",
]:
    stdin, stdout, stderr = c.exec_command(cmd, timeout=30)
    out = stdout.read().decode()
    print(cmd, "->", out.strip()[:200])
    if "nvidia-smi" in cmd and out.strip():
        for pid in out.strip().splitlines():
            pid = pid.strip()
            if pid.isdigit():
                c.exec_command(f"kill -9 {pid}")[1].channel.recv_exit_status()
                print("killed", pid)

time.sleep(2)
stdin, stdout, stderr = c.exec_command("nvidia-smi --query-gpu=memory.used --format=csv,noheader", timeout=30)
print("vram", stdout.read().decode())

# ensure max_len arg exists in remote file - already has --max_len
start = f"""
source /root/miniconda3/bin/activate
cd {remote}
export PYTHONPATH={remote}
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
rm -f {remote}/logs/train_only.out
nohup python -m src.train.train_lora \
  --data data/train/sft.jsonl \
  --modelscope_id Qwen/Qwen2.5-1.5B-Instruct \
  --base_model /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct \
  --out {remote}/models/script_lora \
  --epochs 3 --batch_size 1 --grad_accum 4 --max_len 768 \
  > {remote}/logs/train_only.out 2>&1 &
echo PID=$!
"""
stdin, stdout, stderr = c.exec_command(start, get_pty=True, timeout=30)
print(stdout.read().decode())
time.sleep(10)
stdin, stdout, stderr = c.exec_command(f"tail -50 {remote}/logs/train_only.out; ps aux | grep train_lora | grep -v grep", get_pty=True, timeout=30)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
