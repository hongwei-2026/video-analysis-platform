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
c.connect(
    env["SSH_HOST"],
    port=int(env["SSH_PORT"]),
    username=env["SSH_USER"],
    password=env["SSH_PASSWORD"],
    timeout=30,
    allow_agent=False,
    look_for_keys=False,
)

# ensure latest train files exist
sftp = c.open_sftp()
for rel in [
    "scripts/remote_train_pipeline.sh",
    "src/train/build_sft_dataset.py",
    "src/train/train_lora.py",
    "src/train/__init__.py",
    "src/pipeline/batch_dissect.py",
]:
    local = Path(__file__).resolve().parents[1] / rel
    remote_path = f"{remote}/{rel}"
    # mkdir parent
    parent = "/".join(remote_path.split("/")[:-1])
    c.exec_command(f"mkdir -p {parent}")[1].channel.recv_exit_status()
    # write lf
    data = local.read_bytes().replace(b"\r\n", b"\n")
    with sftp.file(remote_path, "wb") as f:
        f.write(data)
    print("put", rel)
sftp.close()

cmd = f"""
mkdir -p {remote}/logs {remote}/data/scripts {remote}/data/train {remote}/models/script_lora
sed -i 's/\\r$//' {remote}/scripts/remote_train_pipeline.sh
chmod +x {remote}/scripts/remote_train_pipeline.sh
# quick syntax check
bash -n {remote}/scripts/remote_train_pipeline.sh && echo SYNTAX_OK
# start
nohup env REMOTE_DIR={remote} bash {remote}/scripts/remote_train_pipeline.sh > {remote}/logs/pipeline.out 2>&1 &
echo PID=$!
sleep 2
head -50 {remote}/logs/pipeline.out
ps aux | grep -E 'batch_dissect|train_lora|remote_train' | grep -v grep || true
"""
stdin, stdout, stderr = c.exec_command(cmd, get_pty=True, timeout=60)
print(stdout.read().decode("utf-8", errors="replace"))
c.close()
