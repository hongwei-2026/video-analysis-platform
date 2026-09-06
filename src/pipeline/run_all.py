from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="下载 + 批量拆解一条龙")
    ap.add_argument("--urls", type=str, default="data/urls.txt")
    ap.add_argument("--skip-download", action="store_true")
    ap.add_argument("--frames", type=int, default=96)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(root)}

    if not args.skip_download:
        subprocess.check_call(
            [sys.executable, "-m", "src.pipeline.download_videos", "--urls", args.urls],
            cwd=str(root),
            env=env,
        )

    cmd = [
        sys.executable,
        "-m",
        "src.pipeline.batch_dissect",
        "--frames",
        str(args.frames),
    ]
    if args.limit:
        cmd.extend(["--limit", str(args.limit)])
    subprocess.check_call(cmd, cwd=str(root), env=env)


if __name__ == "__main__":
    main()
