#!/usr/bin/env python3
"""仅同步 Studio 前端与流水线代码，并重启云端服务。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

ENV = Path(__file__).resolve().parent / ".env"
ROOT = Path(__file__).resolve().parents[1]

FILES = [
    "studio/app.py",
    "studio/ui_helpers.py",
    "studio/__init__.py",
    "studio/requirements.txt",
    "scripts/cloud_studio_daemon.sh",
    "scripts/.env",
    "src/studio_pipeline/__init__.py",
    "src/studio_pipeline/orchestrator.py",
    "src/studio_pipeline/llm_service.py",
    "src/studio_pipeline/model_loader.py",
    "src/studio_pipeline/minimax_client.py",
    "src/studio_pipeline/agnes_client.py",
    "src/studio_pipeline/asset_ai.py",
    "src/studio_pipeline/asset_service.py",
    "src/studio_pipeline/image_gen.py",
    "src/studio_pipeline/frame_extract.py",
    "src/studio_pipeline/video_frames.py",
    "src/studio_pipeline/qc_service.py",
    "src/studio_pipeline/project_store.py",
    "src/studio_pipeline/dissect_service.py",
    "src/studio_pipeline/timeline.py",
    "src/studio_pipeline/schemas.py",
    "skill/video-dissect/SKILL.md",
    "scripts/download_vl_model.py",
]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def main() -> int:
    env = load_env()
    remote = env["REMOTE_DIR"]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"connect {env['SSH_HOST']}:{env['SSH_PORT']}")
    client.connect(
        env["SSH_HOST"],
        port=int(env["SSH_PORT"]),
        username=env["SSH_USER"],
        password=env["SSH_PASSWORD"],
        timeout=30,
        allow_agent=False,
        look_for_keys=False,
    )
    sftp = client.open_sftp()
    for rel in FILES:
        local = ROOT / rel
        if not local.exists():
            print(f"skip missing {rel}")
            continue
        dst = f"{remote}/{rel.replace(chr(92), '/')}"
        parent = "/".join(dst.split("/")[:-1])
        try:
            sftp.stat(parent)
        except OSError:
            client.exec_command(f"mkdir -p {parent}")
        print(f"upload {rel}")
        sftp.put(str(local), dst)
    sftp.close()

    cmd = f"""
cd {remote}
export PATH=/root/miniconda3/bin:$PATH
screen -S studio -X quit 2>/dev/null || true
sleep 2
chmod +x scripts/cloud_studio_daemon.sh
screen -dmS studio bash scripts/cloud_studio_daemon.sh
sleep 8
screen -ls
curl -s -I http://127.0.0.1:6006/ | head -2
grep UI_VERSION studio/app.py | head -1
tail -3 /tmp/studio_app.log 2>/dev/null || true
"""
    _, stdout, _ = client.exec_command(cmd, get_pty=True, timeout=60)
    time.sleep(12)
    print(stdout.read().decode("utf-8", "replace"))
    client.close()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
