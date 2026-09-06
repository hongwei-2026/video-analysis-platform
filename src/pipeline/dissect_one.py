from __future__ import annotations

import argparse
from pathlib import Path

from src.video_platform.dissector import VideoDissector
from src.video_platform.engine import QwenVLEngine
from src.video_platform.utils import load_config


def main():
    ap = argparse.ArgumentParser(description="单条短视频结构拆解")
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--config", type=str, default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    mcfg = cfg["model"]
    frames = args.frames or mcfg.get("num_frames", 96)

    engine = QwenVLEngine(
        model_dir=mcfg["local_dir"],
        dtype=mcfg.get("dtype", "bfloat16"),
        attn_implementation=mcfg.get("attn_implementation", "flash_attention_2"),
    )
    engine.load()
    dissector = VideoDissector(engine, num_frames=frames, max_new_tokens=mcfg.get("max_new_tokens", 4096))
    data = dissector.dissect_to_file(args.video, args.out)
    print(f"[ok] wrote {args.out}")
    if data.get("meta"):
        print("summary:", data["meta"].get("one_line_summary"))
        print("pattern:", (data.get("script_skeleton") or {}).get("structure_pattern"))


if __name__ == "__main__":
    main()
