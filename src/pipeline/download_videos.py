from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from src.video_platform.utils import ensure_dir, load_config


VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _run_ytdlp(url: str, out_dir: Path, fmt: str, cookies: str | None) -> None:
    out_tpl = str(out_dir / "%(id)s_%(title).80B.%(ext)s")
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "-f",
        fmt,
        "--no-playlist",
        "-o",
        out_tpl,
        "--merge-output-format",
        "mp4",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        url,
    ]
    if cookies and Path(cookies).exists():
        cmd.extend(["--cookies", cookies])
    print("[yt-dlp]", url)
    subprocess.run(cmd, check=False)


def download_from_urls(urls_file: Path, out_dir: Path, fmt: str, cookies: str | None) -> list[Path]:
    ensure_dir(out_dir)
    lines = [
        ln.strip()
        for ln in urls_file.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    before = {p.resolve() for p in out_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS}
    for url in lines:
        if re.match(r"^https?://", url, re.I):
            _run_ytdlp(url, out_dir, fmt, cookies)
        else:
            print(f"[skip] 非 URL: {url}")
    after = [p for p in out_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS and p.resolve() not in before]
    # 也返回目录里全部视频，方便后续批处理
    all_videos = sorted(out_dir.glob("*"))
    all_videos = [p for p in all_videos if p.suffix.lower() in VIDEO_EXTS]
    print(f"[done] 目录内视频数: {len(all_videos)} (本次新增约 {len(after)})")
    return all_videos


def main():
    ap = argparse.ArgumentParser(description="批量下载短视频（yt-dlp）")
    ap.add_argument("--urls", type=str, default=None, help="URL 列表文件，一行一个")
    ap.add_argument("--out", type=str, default=None, help="输出目录")
    ap.add_argument("--config", type=str, default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    urls = Path(args.urls or cfg["paths"]["urls"])
    out = Path(args.out or cfg["paths"]["raw_videos"])
    fmt = cfg.get("download", {}).get("format", "best")
    cookies = cfg.get("download", {}).get("cookies_file") or None
    if not urls.exists():
        raise SystemExit(f"URL 文件不存在: {urls}，请先写 data/urls.txt")
    download_from_urls(urls, out, fmt, cookies)


if __name__ == "__main__":
    main()
