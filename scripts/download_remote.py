"""同步 urls 后在云端批量下载。"""
from __future__ import annotations

from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / "scripts" / ".env"


def load_env():
    env = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def main():
    env = load_env()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        env["SSH_HOST"],
        port=int(env["SSH_PORT"]),
        username=env["SSH_USER"],
        password=env["SSH_PASSWORD"],
        timeout=60,
        allow_agent=False,
        look_for_keys=False,
    )
    remote = env["REMOTE_DIR"]
    sftp = client.open_sftp()
    # ensure dirs
    for d in (remote, f"{remote}/data", f"{remote}/data/raw_videos"):
        try:
            sftp.stat(d)
        except OSError:
            stdin, stdout, stderr = client.exec_command(f"mkdir -p {d}")
            stdout.channel.recv_exit_status()
    sftp.put(str(ROOT / "data" / "urls.txt"), f"{remote}/data/urls.txt")
    sftp.close()
    print("[ok] urls.txt uploaded")

    cmd = f"""
source /root/miniconda3/bin/activate || source /root/miniconda3/etc/profile.d/conda.sh && conda activate base
cd {remote}
export PYTHONPATH={remote}
mkdir -p data/raw_videos
# 同步下载脚本（若未最新）
python -m src.pipeline.download_videos --urls data/urls.txt --out data/raw_videos
echo '---- files ----'
ls -lh data/raw_videos | head -50
echo '---- count ----'
find data/raw_videos -type f \\( -name '*.mp4' -o -name '*.mkv' -o -name '*.webm' -o -name '*.mov' \\) | wc -l
"""
    print("$ download...")
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=3600)
    while True:
        line = stdout.readline()
        if not line:
            break
        try:
            print(line, end="")
        except UnicodeEncodeError:
            print(line.encode("utf-8", errors="replace").decode("ascii", errors="replace"), end="")
    code = stdout.channel.recv_exit_status()
    print(f"[exit={code}]")
    client.close()


if __name__ == "__main__":
    main()
