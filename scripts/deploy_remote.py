"""把本地项目同步到 AutoDL/SeetaCloud，并执行 setup / 下模型 / 冒烟测试。"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(__file__).resolve().parent / ".env"

SKIP_DIRS = {".git", "__pycache__", ".venv", "raw_videos", "models"}
SKIP_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".pyc"}
SKIP_NAMES = {".env"}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    # 环境变量可覆盖
    for k in ("SSH_HOST", "SSH_PORT", "SSH_USER", "SSH_PASSWORD", "REMOTE_DIR"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    need = ["SSH_HOST", "SSH_PORT", "SSH_USER", "SSH_PASSWORD", "REMOTE_DIR"]
    miss = [k for k in need if not env.get(k)]
    if miss:
        raise SystemExit(f"缺少配置 {miss}，请写 scripts/.env")
    return env


def connect(env: dict[str, str]) -> paramiko.SSHClient:
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
    return client


def run(client: paramiko.SSHClient, cmd: str, timeout: int = 3600) -> int:
    print(f"\n$ {cmd}")
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=timeout)
    while True:
        line = stdout.readline()
        if not line:
            break
        try:
            print(line, end="")
        except UnicodeEncodeError:
            print(line.encode("utf-8", errors="replace").decode("ascii", errors="replace"), end="")
    code = stdout.channel.recv_exit_status()
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        try:
            print(err)
        except UnicodeEncodeError:
            print(err.encode("utf-8", errors="replace"))
    print(f"[exit={code}]")
    return code


def should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if set(rel.parts) & SKIP_DIRS:
        return True
    if path.name in SKIP_NAMES or path.name.startswith("_ssh"):
        return True
    if path.suffix.lower() in SKIP_SUFFIXES:
        return True
    return False


def sync_project_fast(client: paramiko.SSHClient, remote_dir: str) -> None:
    """用 tar 管道更快同步。"""
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in ROOT.rglob("*"):
            if p.is_dir():
                continue
            if should_skip(p, ROOT):
                continue
            # 单独放行 scripts/*.sh 与 deploy
            rel = p.relative_to(ROOT)
            tar.add(str(p), arcname=str(rel).replace("\\", "/"))
    data = buf.getvalue()
    print(f"[sync] archive {len(data)/1024:.1f} KB -> {remote_dir}")
    run(client, f"mkdir -p {remote_dir}")
    sftp = client.open_sftp()
    remote_tar = "/tmp/video_platform_sync.tar.gz"
    with sftp.file(remote_tar, "wb") as rf:
        rf.write(data)
    sftp.close()
    code = run(client, f"tar -xzf {remote_tar} -C {remote_dir} && rm -f {remote_tar}")
    if code != 0:
        raise SystemExit("同步失败")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync-only", action="store_true")
    ap.add_argument("--setup", action="store_true")
    ap.add_argument("--download-model", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--all", action="store_true", help="sync+setup+download+test")
    args = ap.parse_args()

    if not any([args.sync_only, args.setup, args.download_model, args.test, args.all]):
        args.all = True

    env = load_env()
    client = connect(env)
    remote = env["REMOTE_DIR"]
    try:
        sync_project_fast(client, remote)
        if args.sync_only and not args.all:
            return
        if args.setup or args.all:
            code = run(
                client,
                f"sed -i 's/\\r$//' {remote}/scripts/*.sh && chmod +x {remote}/scripts/*.sh && REMOTE_DIR={remote} bash {remote}/scripts/remote_setup.sh",
                timeout=3600,
            )
            if code != 0:
                raise SystemExit("setup 失败")
        if args.download_model or args.all:
            code = run(
                client,
                f"REMOTE_DIR={remote} bash {remote}/scripts/remote_download_model.sh",
                timeout=7200,
            )
            if code != 0:
                raise SystemExit("模型下载失败")
        if args.test or args.all:
            code = run(
                client,
                f"REMOTE_DIR={remote} bash {remote}/scripts/remote_smoke_test.sh",
                timeout=3600,
            )
            if code != 0:
                raise SystemExit("冒烟测试失败")
    finally:
        client.close()


if __name__ == "__main__":
    main()
