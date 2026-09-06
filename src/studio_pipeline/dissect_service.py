"""视频拆解辅助：Skill 注入、关键帧拼图、深度扩写。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = ROOT / "skill" / "video-dissect" / "SKILL.md"
JEWELRY_REVERSE_PATH = ROOT / "skill" / "replicate-jewelry-videos" / "references" / "reverse-prompt.md"
CODEX_JEWELRY_REVERSE = Path.home() / ".codex" / "skills" / "replicate-jewelry-videos" / "references" / "reverse-prompt.md"

ENRICH_SYSTEM = (
    "你是资深爆款短视频编导与拆解专家。根据视频拆解 JSON，写一份详细的中文编导分析报告。"
    "要求：纯中文段落，禁止任何 Markdown 符号（禁止 # * ** ### #### - 列表符等），禁止 JSON。"
    "至少 1800 字，必须写满，结构清晰，包含："
    "1) 视频整体定位、目标人群、观看动机；"
    "2) 开场钩子为何有效（画面细节+口播原文+节奏+音效）；"
    "3) 按时间顺序逐段拆解，每段至少 120 字，写清：场景、人物动作、镜头、口播原文、情绪变化、对留存的贡献；"
    "4) 产品/卖点如何植入、何时露出、如何说服；"
    "5) 结尾 CTA 与复刻建议（哪些必须保留、哪些可换、拍摄注意）。"
    "口播必须大量引用原文，画面描述要具体到物品、颜色、位置，禁止空泛套话。"
)

EXPAND_SYSTEM = (
    "你是短视频拆解专家。输入是偏简略的视频拆解 JSON，请补全细节后输出完整 JSON。"
    "要求：保持原结构字段不变；每个 beat 的 visual 至少 40 字、spoken_or_subtitle 尽量写出口播/字幕原文；"
    "script_skeleton.spoken_script_full 串联全片口播，至少 120 字；"
    "hook、products、characters、replication_notes 都要写具体，禁止占位符。"
    "只输出合法 JSON，不要 Markdown 围栏，不要解释。"
)


def load_dissect_skill() -> str:
    if SKILL_PATH.exists():
        return SKILL_PATH.read_text(encoding="utf-8")
    return ""


def load_jewelry_reverse_skill() -> str:
    for p in (JEWELRY_REVERSE_PATH, CODEX_JEWELRY_REVERSE):
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def build_dissect_system() -> str:
    from src.video_platform.prompts import DISSECT_SYSTEM

    skill = load_dissect_skill()
    jewelry = ""
    if os.environ.get("JEWELRY_MODE", "").strip().lower() in ("1", "true", "yes"):
        jewelry = load_jewelry_reverse_skill()

    base = DISSECT_SYSTEM
    if skill:
        base = base + "\n\n## 拆解规范（Skill）\n" + skill
    if jewelry:
        base = base + "\n\n## 饰品反推规范（去产品细节）\n" + jewelry
    return base


def merge_dissect(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    """合并两次拆解，优先保留内容更详尽的字段。"""
    out = dict(primary)
    beats_a = primary.get("beats") or []
    beats_b = secondary.get("beats") or []
    if len(beats_b) > len(beats_a):
        out["beats"] = beats_b
    elif beats_a and beats_b and len(beats_a) == len(beats_b):
        merged_beats: list[dict] = []
        for ba, bb in zip(beats_a, beats_b):
            pick = bb if _beat_detail_len(bb) > _beat_detail_len(ba) else ba
            merged_beats.append({**ba, **bb, **pick})
        out["beats"] = merged_beats
    for key in ("hook", "meta", "script_skeleton", "products", "characters", "replication_notes"):
        if not out.get(key) and secondary.get(key):
            out[key] = secondary[key]
        elif key == "script_skeleton" and secondary.get(key):
            sk_a = out.get("script_skeleton") or {}
            sk_b = secondary.get("script_skeleton") or {}
            if len(str(sk_b.get("spoken_script_full", ""))) > len(str(sk_a.get("spoken_script_full", ""))):
                out["script_skeleton"] = {**sk_a, **sk_b}
            else:
                out["script_skeleton"] = {**sk_b, **sk_a}
    return out


def _beat_detail_len(beat: dict) -> int:
    return len(str(beat.get("visual") or "")) + len(str(beat.get("spoken_or_subtitle") or ""))


def dissect_needs_expansion(dissect: dict[str, Any]) -> bool:
    beats = dissect.get("beats") or []
    if not beats:
        return True
    avg = sum(_beat_detail_len(b) for b in beats) / len(beats)
    spoken = str((dissect.get("script_skeleton") or {}).get("spoken_script_full") or "")
    return avg < 45 or len(spoken) < 80


def expand_dissect_details(dissect: dict[str, Any]) -> dict[str, Any]:
    """VL 拆解过简时，用文本模型补全 beat 细节。"""
    if not dissect_needs_expansion(dissect):
        return dissect
    from src.studio_pipeline.llm_service import _generate_json

    payload = {k: v for k, v in dissect.items() if not str(k).startswith("_")}
    user = (
        "以下拆解 JSON 内容过于简略，请补全每个字段的具体描述与口播原文，输出完整 JSON：\n"
        + json.dumps(payload, ensure_ascii=False)[:12000]
    )
    try:
        expanded = _generate_json(EXPAND_SYSTEM, user, max_new_tokens=3500)
        return merge_dissect(expanded, dissect)
    except Exception:
        return dissect


def enrich_dissect_narrative(dissect: dict[str, Any]) -> str:
    from src.studio_pipeline.llm_service import generate_text

    payload = {k: v for k, v in dissect.items() if not str(k).startswith("_")}
    user = (
        "请根据以下视频拆解数据，写详细编导分析报告（至少 1200 字）：\n"
        + json.dumps(payload, ensure_ascii=False)[:14000]
    )
    try:
        text = generate_text(ENRICH_SYSTEM, user, max_new_tokens=4096)
        import re

        t = text
        t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
        t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
        t = re.sub(r"\*(.+?)\*", r"\1", t)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        return t.strip()
    except Exception as e:
        return f"（深度扩写失败：{e}）"


def make_keyframe_montage(keyframes: list[dict] | None, out_path: str | Path | None = None):
    """生成关键帧拼图（单张图，Gradio Image 稳定显示）。"""
    from PIL import Image, ImageDraw

    if not keyframes:
        return None
    paths: list[tuple[str, str]] = []
    for i, k in enumerate(keyframes):
        p = k.get("path") if isinstance(k, dict) else k
        if p and Path(p).exists() and Path(p).stat().st_size > 500:
            t = k.get("t_sec", "") if isinstance(k, dict) else ""
            paths.append((str(p), f"#{i + 1} {t}s"))

    if not paths:
        return None

    tw, th, label_h = 108, 192, 20
    cols = min(10, len(paths))
    rows = (len(paths) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * tw, rows * (th + label_h)), (24, 24, 32))
    draw = ImageDraw.Draw(canvas)
    for i, (p, cap) in enumerate(paths):
        r, c = divmod(i, cols)
        img = Image.open(p).convert("RGB").resize((tw, th))
        x, y = c * tw, r * (th + label_h)
        canvas.paste(img, (x, y))
        draw.rectangle([x, y + th, x + tw - 1, y + th + label_h - 1], fill=(40, 40, 55))
        draw.text((x + 6, y + th + 4), cap, fill=(220, 220, 230))

    if out_path:
        op = Path(out_path)
        op.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(op, "JPEG", quality=90)
    return canvas
