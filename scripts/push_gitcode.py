"""把代码 + LoRA + Skill 推到 GitCode（不含大模型权重）。

环境变量：
  GITCODE_TOKEN  个人访问令牌
  GITCODE_REPO   默认 https://gitcode.com/hongwei-2026/shiping_shengce.git
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / "release_staging"
ENV_FILE = ROOT / "scripts" / ".env"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for k in ("GITCODE_TOKEN", "GITCODE_REPO"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".ms_upload_cache", "._____temp", ".msc", ".mv"))


def prepare(work: Path) -> None:
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    shutil.copy2(STAGING / "README.md", work / "README.md")
    copy_tree(STAGING / "scripts", work / "scripts")
    for sh in (work / "scripts").glob("*.sh"):
        sh.write_bytes(sh.read_bytes().replace(b"\r\n", b"\n"))

    copy_tree(ROOT / "skill", work / "skill")
    copy_tree(ROOT / "studio", work / "studio")
    copy_tree(ROOT / "src", work / "src")
    copy_tree(ROOT / "configs", work / "configs")
    shutil.copy2(ROOT / "requirements.txt", work / "requirements.txt")

    # LoRA only (~81MB)
    adapter_src = ROOT / "studio" / "adapter"
    if not (adapter_src / "adapter_model.safetensors").exists():
        raise SystemExit(f"缺少 LoRA: {adapter_src}")
    copy_tree(adapter_src, work / "models" / "script_lora" / "adapter")

    # 模型占位说明
    for name, note in (
        ("Qwen2.5-1.5B-Instruct", "脚本基座，运行 bash scripts/download_models.sh 下载"),
        ("Qwen2.5-VL-3B-Instruct", "轻量视频理解，同上"),
    ):
        d = work / "models" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "README.md").write_text(f"# {name}\n\n{note}\n", encoding="utf-8")


def auth_url(repo: str, token: str) -> str:
    rest = repo.removeprefix("https://")
    return f"https://oauth2:{token}@{rest}"


def main() -> None:
    env = load_env()
    token = (env.get("GITCODE_TOKEN") or "").strip()
    repo = env.get("GITCODE_REPO", "https://gitcode.com/hongwei-2026/shiping_shengce.git").strip()
    if not token:
        raise SystemExit("请设置 GITCODE_TOKEN（scripts/.env 或环境变量）")

    work = Path(tempfile.mkdtemp(prefix="gitcode_push_"))
    print("work =", work)
    prepare(work)

    run(["git", "init", "-b", "main"], cwd=work)
    run(["git", "lfs", "install"], cwd=work)
    run(["git", "lfs", "track", "*.safetensors", "*.bin", "*.pt"], cwd=work)
    run(["git", "add", ".gitattributes"], cwd=work)
    run(["git", "add", "-A"], cwd=work)
    run(
        [
            "git",
            "-c",
            "user.name=shiping",
            "-c",
            "user.email=shiping@local",
            "commit",
            "-m",
            "轻量版：Qwen2.5-VL-3B + 脚本网站 + LoRA + Skill",
        ],
        cwd=work,
    )
    run(["git", "remote", "add", "origin", auth_url(repo, token)], cwd=work)
    run(["git", "push", "-u", "origin", "main", "--force"], cwd=work)
    print("[ok]", repo)


if __name__ == "__main__":
    main()
