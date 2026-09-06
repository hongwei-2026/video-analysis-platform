from pathlib import Path
import paramiko

env = {}
for line in (Path(__file__).resolve().parent / ".env").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

remote = env["REMOTE_DIR"]
root = Path(__file__).resolve().parents[1]
files = [
    "src/pipeline/preprocess_videos.py",
    "src/pipeline/dissect_frames.py",
    "src/pipeline/seed_scripts.py",
    "src/train/build_sft_dataset.py",
    "src/train/train_lora.py",
    "scripts/remote_fix_and_train.sh",
    "data/catalog.json",
]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(env["SSH_HOST"], port=int(env["SSH_PORT"]), username=env["SSH_USER"], password=env["SSH_PASSWORD"], timeout=30, allow_agent=False, look_for_keys=False)
# kill old
c.exec_command("pkill -f batch_dissect || true; pkill -f train_lora || true; pkill -f dissect_frames || true")[1].channel.recv_exit_status()
sftp = c.open_sftp()
for rel in files:
    local = root / rel
    rpath = f"{remote}/{rel}"
    parent = "/".join(rpath.split("/")[:-1])
    c.exec_command(f"mkdir -p {parent}")[1].channel.recv_exit_status()
    data = local.read_bytes().replace(b"\r\n", b"\n")
    with sftp.file(rpath, "wb") as f:
        f.write(data)
    print("put", rel)
sftp.close()

cmd = f"""
mkdir -p {remote}/logs
sed -i 's/\\r$//' {remote}/scripts/remote_fix_and_train.sh
chmod +x {remote}/scripts/remote_fix_and_train.sh
nohup env REMOTE_DIR={remote} bash {remote}/scripts/remote_fix_and_train.sh > {remote}/logs/fix_train.out 2>&1 &
echo PID=$!
sleep 2
tail -30 {remote}/logs/fix_train.out || true
"""
stdin, stdout, stderr = c.exec_command(cmd, get_pty=True, timeout=60)
out = stdout.read().decode("utf-8", errors="replace")
try:
    print(out)
except UnicodeEncodeError:
    print(out.encode("utf-8", "replace").decode("ascii", "replace"))
c.close()
