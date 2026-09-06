"""同步代码到云端并后台启动：拆解→SFT→LoRA 训练。"""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "scripts" / ".env"
SKIP_DIRS = {".git", "__pycache__", ".venv", "raw_videos", "scripts"}
# 仍同步 scripts 下的 sh
ALLOW_SCRIPT_NAMES = {
    "remote_train_pipeline.sh",
    "remote_setup.sh",
    "remote_download_model.sh",
    "remote_smoke_test.sh",
}


def load_env():
    env = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def should_skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if "scripts" in rel.parts:
        return path.name not in ALLOW_SCRIPT_NAMES and not path.name.endswith(".sh")
    if set(rel.parts) & {".git", "__pycache__", ".venv", "raw_videos"}:
        return True
    if path.suffix.lower() in {".mp4", ".mov", ".webm", ".mkv", ".pyc"}:
        return True
    if path.name == ".env" or path.name.startswith("_"):
        return True
    return False


def main():
    env = load_env()
    remote = env["REMOTE_DIR"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in ROOT.rglob("*"):
            if p.is_dir() or should_skip(p):
                continue
            tar.add(str(p), arcname=str(p.relative_to(ROOT)).replace("\\", "/"))
    data = buf.getvalue()
    print(f"[sync] {len(data)/1024:.1f} KB -> {remote}")

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        env["SSH_HOST"],
        port=int(env["SSH_PORT"]),
        username=env["SSH_USER"],
        password=env["SSH_PASSWORD"],
        timeout=60,
        allow_agent=False,
        look_for_keys=False,
    )
    c.exec_command(f"mkdir -p {remote}", timeout=30)[1].channel.recv_exit_status()
    sftp = c.open_sftp()
    with sftp.file("/tmp/vp_train_sync.tar.gz", "wb") as f:
        f.write(data)
    sftp.close()
    cmd = f"tar -xzf /tmp/vp_train_sync.tar.gz -C {remote} && rm -f /tmp/vp_train_sync.tar.gz"
    print(c.exec_command(cmd, get_pty=True)[1].read().decode())

    # LF fix + start pipeline in background
    start = f"""
sed -i 's/\\r$//' {remote}/scripts/*.sh
chmod +x {remote}/scripts/*.sh
pkill -f batch_dissect || true
pkill -f train_lora || true
nohup bash -lc 'export REMOTE_DIR={remote}; bash {remote}/scripts/remote_train_pipeline.sh' > {remote}/logs/pipeline.out 2>&1 &
echo PID=$!
sleep 1
tail -20 {remote}/logs/pipeline.out || true
"""
    stdin, stdout, stderr = c.exec_command(start, get_pty=True, timeout=60)
    print(stdout.read().decode("utf-8", errors="replace"))
    c.close()
    print("[ok] training pipeline started on remote")


if __name__ == "__main__":
    main()
