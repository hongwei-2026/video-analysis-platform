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

# stop slow preprocess
c.exec_command("pkill -f preprocess_videos || true; pkill -f remote_fix_and_train || true; pkill -f dissect_frames || true")[1].channel.recv_exit_status()

cmd = f"""
source /root/miniconda3/bin/activate
cd {remote}
export PYTHONPATH={remote}
mkdir -p logs data/train models/script_lora

# ensure seeds
python -m src.pipeline.seed_scripts --catalog data/catalog.json --out data/scripts
python -m src.train.build_sft_dataset --scripts data/scripts --out data/train/sft.jsonl
wc -l data/train/sft.jsonl

nohup bash -lc 'source /root/miniconda3/bin/activate; cd {remote}; export PYTHONPATH={remote}; pip install -q datasets peft accelerate sentencepiece -i https://pypi.tuna.tsinghua.edu.cn/simple; python -m src.train.train_lora --data data/train/sft.jsonl --modelscope_id Qwen/Qwen2.5-1.5B-Instruct --base_model /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct --out {remote}/models/script_lora --epochs 3 --batch_size 1 --grad_accum 8' > {remote}/logs/train_only.out 2>&1 &
echo TRAIN_PID=$!
sleep 3
tail -20 {remote}/logs/train_only.out
"""
stdin, stdout, stderr = c.exec_command(cmd, get_pty=True, timeout=120)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
