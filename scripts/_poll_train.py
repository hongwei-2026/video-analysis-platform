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
echo '=== proc ==='
ps aux | grep -E 'batch_dissect|train_lora|build_sft' | grep -v grep || echo IDLE
echo '=== scripts json ==='
ls {remote}/data/scripts/*.json 2>/dev/null | wc -l
echo '=== dissect log tail ==='
tail -15 {remote}/logs/dissect.log 2>/dev/null
echo '=== pipeline out tail ==='
tail -20 {remote}/logs/pipeline.out 2>/dev/null
echo '=== adapter ==='
ls {remote}/models/script_lora/adapter 2>/dev/null | head || echo no_adapter_yet
"""
stdin, stdout, stderr = c.exec_command(cmd, timeout=30, get_pty=True)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
