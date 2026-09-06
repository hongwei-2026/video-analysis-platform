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

checks = [
    f"ls -la {remote}/logs/ 2>&1 | head -20",
    f"ls -la {remote}/data/train/sft.jsonl 2>&1",
    f"ls -la /root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct 2>&1 | head -10",
    f"ls -la {remote}/src/train/train_lora.py 2>&1",
    f"which python; which conda; ls /root/miniconda3/bin/python 2>&1",
    f"cat {remote}/logs/train_only.out 2>&1 | head -100",
    "ps aux | grep -E 'train_lora|python' | grep -v grep | head -20",
    "nvidia-smi",
]
for cmd in checks:
    print("====", cmd)
    stdin, stdout, stderr = c.exec_command(cmd, get_pty=True, timeout=60)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    print(out or err or "(empty)")
    print()

c.close()
