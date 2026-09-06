#!/usr/bin/env python3
"""同步本地代码到云端并重启 Studio（端口 6006）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.deploy_remote import connect, load_env, sync_project_fast  # noqa: E402


def main() -> int:
    env = load_env()
    remote = env["REMOTE_DIR"]
    client = connect(env)
    try:
        print("[1/3] 同步代码...")
        sync_project_fast(client, remote)

        # 写入云端 .env（含 MINIMAX，不提交 git）
        env_local = Path(__file__).resolve().parent / ".env"
        if env_local.exists():
            sftp = client.open_sftp()
            with sftp.file(f"{remote}/scripts/.env", "w") as f:
                f.write(env_local.read_text(encoding="utf-8").replace("\r\n", "\n"))
            sftp.close()
            print("[2/3] 已同步 scripts/.env")

        restart = f"""
set -e
cd {remote}
export PATH=/root/miniconda3/bin:$PATH
PY=$(command -v python3)
"$PY" -m pip install -q -r studio/requirements.txt
screen -S studio -X quit 2>/dev/null || true
sleep 1
chmod +x scripts/cloud_studio_daemon.sh
screen -dmS studio bash scripts/cloud_studio_daemon.sh
sleep 12
echo "=== screen ==="
screen -ls || true
echo "=== port 6006 ==="
curl -s -I http://127.0.0.1:6006/ | head -5 || true
echo "=== app marker ==="
grep -m1 'UI_VERSION\\|分步向导' studio/app.py || true
echo "=== log ==="
tail -n 20 /tmp/studio_app.log 2>/dev/null || true
"""
        print("[3/3] 重启 Studio...")
        _, stdout, _ = client.exec_command(restart, get_pty=True, timeout=120)
        out = stdout.read().decode("utf-8", "replace")
        print(out)
        if "6006" not in out and "Running" not in out:
            print("WARN: 请检查云端日志 /tmp/studio_app.log")
    finally:
        client.close()
    print("\n完成。公网访问 AutoDL 6006 代理地址，页面应显示「界面版本 2026-08-29-wizard-v2」")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
