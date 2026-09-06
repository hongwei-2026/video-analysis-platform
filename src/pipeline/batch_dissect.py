from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from tqdm import tqdm

from src.video_platform.dissector import VideoDissector
from src.video_platform.engine import QwenVLEngine
from src.video_platform.utils import ensure_dir, load_config

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def main():
    ap = argparse.ArgumentParser(description="批量拆解短视频 → 结构脚本 JSON")
    ap.add_argument("--videos", type=str, default=None)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--config", type=str, default=None)
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条，0=全部")
    args = ap.parse_args()

    cfg = load_config(args.config)
    videos_dir = Path(args.videos or cfg["paths"]["raw_videos"])
    out_dir = ensure_dir(args.out or cfg["paths"]["scripts"])
    mcfg = cfg["model"]
    frames = args.frames or mcfg.get("num_frames", 96)
    skip_existing = cfg.get("dissect", {}).get("skip_existing", True)

    files = sorted([p for p in videos_dir.iterdir() if p.suffix.lower() in VIDEO_EXTS])
    if args.limit and args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"没有视频: {videos_dir}")

    engine = QwenVLEngine(
        model_dir=mcfg["local_dir"],
        dtype=mcfg.get("dtype", "bfloat16"),
        attn_implementation=mcfg.get("attn_implementation", "flash_attention_2"),
    )
    engine.load()
    dissector = VideoDissector(engine, num_frames=frames, max_new_tokens=mcfg.get("max_new_tokens", 4096))

    ok, fail = 0, 0
    for vp in tqdm(files, desc="dissect"):
        out_path = out_dir / f"{vp.stem}.json"
        if skip_existing and out_path.exists():
            continue
        try:
            dissector.dissect_to_file(vp, out_path)
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            err = out_dir / f"{vp.stem}.error.txt"
            err.write_text(f"{e}\n\n{traceback.format_exc()}", encoding="utf-8")
            print(f"[fail] {vp.name}: {e}")

    print(f"[done] ok={ok} fail={fail} out={out_dir}")


if __name__ == "__main__":
    main()
