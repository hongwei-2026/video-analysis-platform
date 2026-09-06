"""推送到魔搭：模型仓库 + 创空间 Studio + Skills 中心。

需要环境变量或 scripts/.env:
  MODELSCOPE_API_TOKEN=你的令牌
  （在 https://www.modelscope.cn/my/myaccesstoken 创建）
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import paramiko
import requests

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(__file__).resolve().parent / ".env"

STUDIO_OWNER = "Yhw050920"
STUDIO_REPO = "shiping_moxing"
MODEL_REPO = "shuju"  # 模型仓库：Yhw050920/shuju（用户指定）
SKILL_NAME = "viral-short-script"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for k in (
        "SSH_HOST",
        "SSH_PORT",
        "SSH_USER",
        "SSH_PASSWORD",
        "REMOTE_DIR",
        "MODELSCOPE_API_TOKEN",
    ):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def require_token(env: dict[str, str]) -> str:
    token = (env.get("MODELSCOPE_API_TOKEN") or "").strip()
    if not token or token in {"your_token", "YOUR_TOKEN", "xxx"}:
        raise SystemExit(
            "缺少 MODELSCOPE_API_TOKEN。\n"
            "1) 打开 https://www.modelscope.cn/my/myaccesstoken 创建令牌\n"
            "2) 写入 scripts/.env：MODELSCOPE_API_TOKEN=ms-xxxx\n"
            "3) 再运行：python scripts/push_modelscope.py"
        )
    return token


def ssh_connect(env: dict[str, str]) -> paramiko.SSHClient:
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
    return c


def download_dir(sftp: paramiko.SFTPClient, remote: str, local: Path) -> None:
    local.mkdir(parents=True, exist_ok=True)
    for attr in sftp.listdir_attr(remote):
        r = f"{remote}/{attr.filename}"
        l = local / attr.filename
        if stat_is_dir(attr):
            download_dir(sftp, r, l)
        else:
            sftp.get(r, str(l))
            print("  get", r)


def stat_is_dir(attr) -> bool:
    import stat

    return stat.S_ISDIR(attr.st_mode)


def push_model(token: str, adapter_local: Path) -> None:
    from modelscope.hub.api import HubApi

    api = HubApi()
    api.login(token)
    model_id = f"{STUDIO_OWNER}/{MODEL_REPO}"
    print("[model] create/upload", model_id)
    try:
        api.create_model(model_id, visibility=5, license="Apache License 2.0")
    except Exception as e:
        print("[model] create skip:", e)
    api.upload_folder(
        repo_id=model_id,
        folder_path=str(adapter_local),
        commit_message="Upload viral short-script LoRA adapter",
        repo_type="model",
    )
    print("[model] done https://www.modelscope.cn/models/" + model_id)


def push_studio(token: str, adapter_local: Path, work: Path) -> None:
    studio_dir = work / "studio_repo"
    if studio_dir.exists():
        shutil.rmtree(studio_dir)
    url = f"https://oauth2:{token}@www.modelscope.cn/studios/{STUDIO_OWNER}/{STUDIO_REPO}.git"
    print("[studio] clone", STUDIO_OWNER, STUDIO_REPO)
    subprocess.run(["git", "clone", url, str(studio_dir)], check=True)

    # 拷贝应用与适配器（创空间入口必须是 app.py）
    shutil.copy2(ROOT / "studio" / "app.py", studio_dir / "app.py")
    shutil.copy2(ROOT / "studio" / "requirements.txt", studio_dir / "requirements.txt")
    shutil.copy2(ROOT / "studio" / "README.md", studio_dir / "README.md")
    adapter_dst = studio_dir / "adapter"
    if adapter_dst.exists():
        shutil.rmtree(adapter_dst)
    shutil.copytree(adapter_local, adapter_dst)

    # git push
    subprocess.run(["git", "-C", str(studio_dir), "add", "-A"], check=True)
    st = subprocess.run(
        ["git", "-C", str(studio_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    if not st.stdout.strip():
        print("[studio] nothing to commit")
        return
    subprocess.run(
        ["git", "-C", str(studio_dir), "commit", "-m", "Deploy script generator + LoRA adapter"],
        check=True,
    )
    # ModelScope 默认 master
    branch = subprocess.check_output(
        ["git", "-C", str(studio_dir), "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip()
    subprocess.run(["git", "-C", str(studio_dir), "push", "-u", "origin", branch], check=True)
    print(f"[studio] pushed https://www.modelscope.cn/studios/{STUDIO_OWNER}/{STUDIO_REPO}")


def push_skill(token: str, work: Path) -> None:
    skill_src = ROOT / "skill"
    zip_path = work / f"{SKILL_NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # zip 根目录只能有一份 SKILL.md（及可选附属文件）
        zf.write(skill_src / "SKILL.md", arcname="SKILL.md")

    headers = {"Authorization": f"Bearer {token}"}
    print("[skill] upload zip")
    with zip_path.open("rb") as f:
        r = requests.post(
            "https://www.modelscope.cn/openapi/v1/files/upload",
            headers=headers,
            files={"file": (zip_path.name, f, "application/zip")},
            data={"type": "skill"},
            timeout=120,
        )
    print(r.status_code, r.text[:500])
    r.raise_for_status()
    file_id = r.json()["data"]["id"]

    payload = {
        "owner": STUDIO_OWNER,
        "skill_name": SKILL_NAME,
        "display_name": "爆款短视频结构脚本",
        "description": "根据品类/卖点/人群生成可拍摄的爆款短视频结构脚本（钩子、分镜、口播、CTA）。",
        "skill_file": file_id,
        "category": "ai-media",
        "license": "Apache License 2.0",
        "tags": ["短视频", "脚本", "种草", "爆款"],
        "source_url": f"https://www.modelscope.cn/studios/{STUDIO_OWNER}/{STUDIO_REPO}",
    }
    r2 = requests.post(
        "https://www.modelscope.cn/openapi/v1/skills",
        headers={**headers, "Content-Type": "application/json"},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=60,
    )
    print(r2.status_code, r2.text[:800])
    if r2.status_code >= 400:
        # 可能已存在 → 更新
        r3 = requests.patch(
            f"https://www.modelscope.cn/openapi/v1/skills/{STUDIO_OWNER}/{SKILL_NAME}/settings",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps(
                {
                    "display_name": payload["display_name"],
                    "description": payload["description"],
                    "skill_file": file_id,
                    "tags": payload["tags"],
                    "category": payload["category"],
                    "source_url": payload["source_url"],
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            timeout=60,
        )
        print("[skill] update", r3.status_code, r3.text[:500])
        r3.raise_for_status()
    else:
        r2.raise_for_status()
    print(f"[skill] https://www.modelscope.cn/skills/@{STUDIO_OWNER}/{SKILL_NAME}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-model", action="store_true")
    ap.add_argument("--skip-studio", action="store_true")
    ap.add_argument("--skip-skill", action="store_true")
    ap.add_argument("--adapter-local", type=str, default="", help="若已拉到本地的 adapter 路径")
    args = ap.parse_args()

    env = load_env()
    token = require_token(env)

    work = Path(tempfile.mkdtemp(prefix="ms_push_"))
    adapter_local = Path(args.adapter_local) if args.adapter_local else work / "adapter"

    if not args.adapter_local:
        print("[pull] adapter from remote GPU box")
        client = ssh_connect(env)
        sftp = client.open_sftp()
        remote_adapter = f"{env['REMOTE_DIR']}/models/script_lora/adapter"
        try:
            sftp.stat(remote_adapter)
        except OSError as e:
            raise SystemExit(f"远端还没有 adapter：{remote_adapter}，请先跑完训练") from e
        download_dir(sftp, remote_adapter, adapter_local)
        sftp.close()
        client.close()

    if not any(adapter_local.iterdir()):
        raise SystemExit(f"adapter 目录为空: {adapter_local}")

    if not args.skip_model:
        push_model(token, adapter_local)
    if not args.skip_studio:
        push_studio(token, adapter_local, work)
    if not args.skip_skill:
        push_skill(token, work)

    print("[all done]", work)


if __name__ == "__main__":
    main()
