"""分镜确认后，用 Agnes / 即梦 CLI 生成单段视频。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    return (args.prompt or "").strip()


def _check_gate(gate_file: str | None) -> None:
    if not gate_file:
        return
    p = Path(gate_file)
    if not p.exists():
        print(f"BLOCKED: 缺少分镜确认文件 {gate_file}")
        sys.exit(1)
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("status") != "approved":
        print(f"BLOCKED: 分镜未确认 status={data.get('status')}")
        sys.exit(1)


def cmd_agnes(args: argparse.Namespace) -> None:
    _check_gate(args.gate)
    from src.studio_pipeline.agnes_client import AgnesVideoClient

    prompt = _load_prompt(args)
    client = AgnesVideoClient()
    beat = {
        "motion_prompt": prompt,
        "duration_sec": args.seconds,
        "first_frame": {"path": args.image} if args.image else None,
    }
    result = client.generate_beat_clip(beat, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_jimeng(args: argparse.Namespace) -> None:
    _check_gate(args.gate)
    from src.studio_pipeline.jimeng_client import JimengVideoClient

    prompt = _load_prompt(args)
    client = JimengVideoClient()
    beat = {
        "motion_prompt": prompt,
        "duration_sec": args.seconds,
        "first_frame": {"path": args.image} if args.image else None,
    }
    result = client.generate_beat_clip(beat, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Storyboard → video CLI (Agnes / Jimeng)")
    sub = parser.add_subparsers(dest="provider", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--image", required=True, help="首帧分镜图路径")
        p.add_argument("--out", required=True, help="输出 mp4 路径")
        p.add_argument("--seconds", type=int, default=5, help="时长 4-10s")
        p.add_argument("--prompt", default="", help="运动提示词")
        p.add_argument("--prompt-file", default="", help="从文件读取提示词")
        p.add_argument("--gate", default="", help="storyboard_approval.json 路径（可选门禁）")

    pa = sub.add_parser("agnes", help="小云雀 Agnes 视频")
    add_common(pa)
    pa.set_defaults(func=cmd_agnes)

    pj = sub.add_parser("jimeng", help="即梦 Jimeng 视频")
    add_common(pj)
    pj.set_defaults(func=cmd_jimeng)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
