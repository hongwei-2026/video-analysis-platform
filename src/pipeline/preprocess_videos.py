"""把 raw_videos 重编码为干净 ASCII 文件名 mp4，并抽帧备用。"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


def bvid_of(name: str) -> str | None:
    m = re.match(r"(BV[\w]+)", name)
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="data/raw_videos")
    ap.add_argument("--out", default="data/clean_videos")
    ap.add_argument("--frames_dir", default="data/frames")
    ap.add_argument("--num_frames", type=int, default=32)
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    frames_root = Path(args.frames_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames_root.mkdir(parents=True, exist_ok=True)

    files = [p for p in src.iterdir() if p.suffix.lower() == ".mp4" and not p.name.startswith("_")]
    for i, p in enumerate(files, 1):
        bvid = bvid_of(p.name) or f"vid{i:03d}"
        dst = out / f"{bvid}.mp4"
        print(f"[{i}/{len(files)}] {p.name} -> {dst.name}")
        # 重编码保证有视频流
        cmd = [
            "ffmpeg", "-y", "-i", str(p),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=720:-2",
            "-c:a", "aac", "-shortest", "-movflags", "+faststart",
            str(dst),
        ]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not dst.exists() or dst.stat().st_size < 1000:
            print("  reencode fail, try video-only")
            cmd2 = [
                "ffmpeg", "-y", "-i", str(p),
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=720:-2",
                str(dst),
            ]
            subprocess.run(cmd2, check=False)

        # 抽帧
        fdir = frames_root / bvid
        fdir.mkdir(parents=True, exist_ok=True)
        # fps 估算：取固定数量帧
        # 用 fps=1/N*duration 不好算，改用 select
        pattern = str(fdir / "f_%03d.jpg")
        # 先取时长
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(dst)],
            capture_output=True, text=True,
        )
        try:
            dur = float(probe.stdout.strip() or "10")
        except ValueError:
            dur = 10.0
        fps = max(args.num_frames / max(dur, 1.0), 0.2)
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(dst), "-vf", f"fps={fps}", "-frames:v", str(args.num_frames), pattern],
            capture_output=True,
        )
        n = len(list(fdir.glob("*.jpg")))
        print(f"  frames={n} dur={dur:.1f}s")

    print("[ok] clean videos:", len(list(out.glob("*.mp4"))))


if __name__ == "__main__":
    main()
