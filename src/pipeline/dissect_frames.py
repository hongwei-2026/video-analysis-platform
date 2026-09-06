"""基于抽帧图片做结构拆解（绕过视频解码失败）。"""
from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from tqdm import tqdm

from src.video_platform.engine import QwenVLEngine
from src.video_platform.prompts import DISSECT_SYSTEM, DISSECT_USER
from src.video_platform.utils import ensure_dir, extract_json, load_config


def build_image_messages(frame_paths: list[Path]):
    content = [{"type": "image", "image": str(p.resolve())} for p in frame_paths]
    content.append({"type": "text", "text": DISSECT_USER + "\n（以上是按时间顺序抽取的关键帧）"})
    return [
        {"role": "system", "content": [{"type": "text", "text": DISSECT_SYSTEM}]},
        {"role": "user", "content": content},
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="data/frames")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max_images", type=int, default=24)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    out_dir = ensure_dir(args.out or cfg["paths"]["scripts"])
    frames_root = Path(args.frames)
    dirs = sorted([p for p in frames_root.iterdir() if p.is_dir()])
    if not dirs:
        raise SystemExit(f"无帧目录: {frames_root}")

    engine = QwenVLEngine(
        model_dir=cfg["model"]["local_dir"],
        dtype=cfg["model"].get("dtype", "bfloat16"),
        attn_implementation=cfg["model"].get("attn_implementation", "sdpa"),
    )
    engine.load()

    ok = fail = 0
    for d in tqdm(dirs, desc="frame-dissect"):
        out_path = out_dir / f"{d.name}.json"
        if out_path.exists() and not out_path.name.startswith("_"):
            # 覆盖失败的空结构时可删；这里跳过已有非空
            try:
                old = json.loads(out_path.read_text(encoding="utf-8"))
                if old.get("beats") or (old.get("script_skeleton") or {}).get("spoken_script_full"):
                    continue
            except Exception:
                pass
        imgs = sorted(d.glob("*.jpg"))[: args.max_images]
        if len(imgs) < 2:
            fail += 1
            continue
        try:
            messages = build_image_messages(imgs)
            raw = engine.chat(messages, max_new_tokens=cfg["model"].get("max_new_tokens", 4096))
            try:
                data = extract_json(raw)
            except Exception:
                data = {"parse_error": True, "raw_text": raw}
            data["_source_frames"] = str(d)
            data["_num_images"] = len(imgs)
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            (out_dir / f"{d.name}.error.txt").write_text(f"{e}\n{traceback.format_exc()}", encoding="utf-8")
            print("fail", d.name, e)
    print(f"[done] ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
