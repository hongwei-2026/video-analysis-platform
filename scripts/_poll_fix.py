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
ps aux | grep -E 'fix_and_train|preprocess|dissect_frames|train_lora|seed_scripts' | grep -v grep || echo IDLE
echo '---OUT---'
tail -25 {remote}/logs/fix_train.out 2>/dev/null
echo '---COUNTS---'
echo scripts=$(ls {remote}/data/scripts/*.json 2>/dev/null | wc -l)
echo clean=$(ls {remote}/data/clean_videos/*.mp4 2>/dev/null | wc -l)
echo frames=$(ls -d {remote}/data/frames/*/ 2>/dev/null | wc -l)
echo sft=$(wc -l < {remote}/data/train/sft.jsonl 2>/dev/null || echo 0)
ls {remote}/models/script_lora/adapter 2>/dev/null | head || echo no_adapter
"""
stdin, stdout, stderr = c.exec_command(cmd, timeout=30, get_pty=True)
print(stdout.read().decode("utf-8", errors="replace").encode("utf-8", "replace").decode("utf-8", "replace"))
c.close()
