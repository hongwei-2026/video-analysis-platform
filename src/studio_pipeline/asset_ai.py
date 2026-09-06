"""用 VL + Agnes 做原片资产分人/分产品提取（严防混人、人货混淆）。"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CLASSIFY_SYSTEM = (
    "你是短视频资产分拣员。任务：把关键帧分到「互不相同的人物」和「主推商品」两类。"
    "硬规则："
    "1) 不同的人必须分到不同 characters，绝不能把年轻围裙女和中年毛衣妈妈混成同一人；"
    "2) 人物帧必须能看清脸或上半身人像；纯手部、倒液体、只有瓶子的特写绝不能进 characters；"
    "3) 产品帧必须是瓶子/包装特写或产品占画面主体；有清晰人脸的半身人像绝不能进 products；"
    "4) 同一帧只能属于一个人或一个产品，不要重复分配；"
    "5) 只输出 JSON，不要 Markdown。"
)


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError("VL 未返回 JSON")
    return json.loads(m.group(0))


def _skin_ratio(path: str, box: tuple[float, float, float, float]) -> float:
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB")
        w, h = img.size
        x0, y0, x1, y1 = box
        crop = img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1))).resize((48, 48))
        pixels = list(crop.getdata())
        n = max(1, len(pixels))
        skin = sum(
            1
            for r, g, b in pixels
            if r > 90 and g > 55 and b > 40 and r >= g >= b and (r - b) > 12 and abs(r - g) < 60
        )
        return skin / n
    except Exception:
        return 0.0


def _upper_skin(path: str) -> float:
    return _skin_ratio(path, (0.18, 0.05, 0.82, 0.55))


def _lower_skin(path: str) -> float:
    return _skin_ratio(path, (0.2, 0.55, 0.9, 0.98))


def _center_skin(path: str) -> float:
    return _skin_ratio(path, (0.25, 0.2, 0.75, 0.75))


def _is_character_asset_frame(path: str) -> bool:
    """人物资产帧：上半身要有明显肤色；排除纯手部/产品特写。"""
    up = _upper_skin(path)
    low = _lower_skin(path)
    center = _center_skin(path)
    # 手部倒液体：下半/中心肤色高、上半脸区肤色低
    if up < 0.08 and (low > 0.18 or center > 0.15):
        return False
    # 几乎无人脸/上半身
    if up < 0.10 and center < 0.12:
        return False
    return up >= 0.10 or (center >= 0.14 and up >= 0.06)


def _is_product_asset_frame(path: str) -> bool:
    """产品资产帧：不能是清晰半身人像；允许手+瓶，但人脸不能占主导。"""
    up = _upper_skin(path)
    # 上半身人脸明显 → 这是人像，不是产品图
    if up > 0.16:
        return False
    # 中心也是大面积脸
    if _center_skin(path) > 0.22 and up > 0.12:
        return False
    return True


def _looks_non_person_frame(path: str) -> bool:
    return not _is_character_asset_frame(path)


def _color_sig_upper(path: str) -> tuple[float, float, float] | None:
    try:
        from PIL import Image

        img = Image.open(path).convert("RGB")
        w, h = img.size
        crop = img.crop((int(w * 0.2), int(h * 0.08), int(w * 0.8), int(h * 0.55))).resize((24, 24))
        pixels = list(crop.getdata())
        if not pixels:
            return None
        n = len(pixels)
        return (sum(p[0] for p in pixels) / n, sum(p[1] for p in pixels) / n, sum(p[2] for p in pixels) / n)
    except Exception:
        return None


def _sig_dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _dissect_character_hints(dissect: dict[str, Any] | None) -> str:
    chars = (dissect or {}).get("characters") or []
    if not chars:
        return ""
    lines = []
    for i, c in enumerate(chars[:4]):
        if not isinstance(c, dict):
            continue
        lines.append(
            f"- 人物候选{i + 1}: {c.get('role') or c.get('id') or ''}｜{c.get('appearance') or ''}"
        )
    return "\n".join(lines)


def _dissect_product_hints(dissect: dict[str, Any] | None) -> str:
    prods = (dissect or {}).get("products") or []
    if not prods:
        return ""
    lines = []
    for i, p in enumerate(prods[:3]):
        if not isinstance(p, dict):
            continue
        lines.append(
            f"- 产品候选{i + 1}: {p.get('name_guess') or p.get('id') or ''}｜"
            f"{','.join(p.get('selling_points') or [])}"
        )
    return "\n".join(lines)


def classify_assets_with_vl(
    keyframes: list[dict],
    dissect: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """识别：几个人、每人对应哪些帧、产品在哪些帧（严防混人/人货混淆）。"""
    from src.studio_pipeline.model_loader import load_vl

    frames = [k for k in keyframes if k.get("path") and Path(k["path"]).exists()]
    if not frames:
        return {"characters": [], "products": []}

    step = max(1, len(frames) // 14)
    sample = frames[::step][:14]
    meta = (dissect or {}).get("meta") or {}
    hint = meta.get("one_line_summary") or ""
    char_hints = _dissect_character_hints(dissect)
    prod_hints = _dissect_product_hints(dissect)

    char_block = f"拆解人物提示：\n{char_hints}\n" if char_hints else ""
    prod_block = f"拆解产品提示：\n{prod_hints}\n" if prod_hints else ""
    user_text = (
        f"视频概要：{hint}\n"
        f"{char_block}{prod_block}"
        f"共 {len(sample)} 张关键帧（按下标 0..{len(sample) - 1} 顺序）。\n"
        "请输出 JSON：\n"
        "{\n"
        '  "characters": [\n'
        '    {"id":0,"label":"年轻围裙女","appearance":"年龄/发型/上衣颜色/是否围裙","frame_indices":[0,1]},\n'
        '    {"id":1,"label":"中年毛衣妈妈","appearance":"年龄/发型/米色毛衣","frame_indices":[4,5]}\n'
        "  ],\n"
        '  "products": [\n'
        '    {"id":0,"label":"洗洁精黄盖白瓶","appearance":"瓶身颜色/盖色/形状","frame_indices":[9]}\n'
        "  ]\n"
        "}\n"
        "规则（必须遵守）：\n"
        "1) 有几张不同脸就分几个人，label 要能区分年龄/衣服；\n"
        "2) characters.frame_indices 只能选「脸或上半身清晰」的帧；\n"
        "3) 倒洗洁精的手部特写、只有瓶的特写 → 不要放 characters；\n"
        "4) products.frame_indices 只能选产品为主体的帧；半身人像拿瓶不要当产品帧；\n"
        "5) 同一 frame_index 不要同时出现在两个 characters，也不要人物和产品抢同一张脸部大图；\n"
        "6) 每人最多 3 个 frame_indices，每个产品最多 2 个。"
    )

    engine = load_vl()
    # Agnes VL 用 OpenAI 格式；本地 Qwen 用 type=image
    from src.studio_pipeline.agnes_llm import use_agnes_llm

    if use_agnes_llm():
        content: list[dict[str, Any]] = []
        for k in sample:
            p = str(Path(k["path"]).resolve())
            content.append({"type": "image", "image": p})
        content.append({"type": "text", "text": user_text})
        messages = [
            {"role": "system", "content": CLASSIFY_SYSTEM},
            {"role": "user", "content": content},
        ]
    else:
        messages = [
            {"role": "system", "content": [{"type": "text", "text": CLASSIFY_SYSTEM}]},
            {
                "role": "user",
                "content": [
                    *[{"type": "image", "image": str(Path(k["path"]).resolve())} for k in sample],
                    {"type": "text", "text": user_text},
                ],
            },
        ]

    raw = engine.chat(messages, max_new_tokens=1400)
    data = _extract_json(raw)

    # —— 产品优先认领（避免产品帧被塞进人物）——
    product_claimed: set[str] = set()
    prods_out: list[dict[str, Any]] = []
    for p in data.get("products") or []:
        mapped = []
        seen: set[str] = set()
        for i in p.get("frame_indices") or []:
            try:
                ii = int(i)
            except (TypeError, ValueError):
                continue
            if not (0 <= ii < len(sample)):
                continue
            src = sample[ii]["path"]
            if src in seen or src in product_claimed:
                continue
            if not _is_product_asset_frame(src):
                continue
            seen.add(src)
            product_claimed.add(src)
            mapped.append({"path": src, "t_sec": float(sample[ii].get("t_sec", 0)), "sample_idx": ii})
        if not mapped:
            continue
        prods_out.append(
            {
                "id": int(p.get("id", len(prods_out))),
                "label": str(p.get("label") or f"产品{len(prods_out) + 1}"),
                "appearance": str(p.get("appearance") or ""),
                "frames": mapped[:2],
            }
        )

    chars_out: list[dict[str, Any]] = []
    for c in data.get("characters") or []:
        idxs = []
        for i in c.get("frame_indices") or []:
            try:
                ii = int(i)
            except (TypeError, ValueError):
                continue
            if 0 <= ii < len(sample):
                idxs.append(ii)
        seen = set()
        mapped = []
        for ii in idxs:
            p = sample[ii]["path"]
            if p in seen or p in product_claimed:
                continue
            if not _is_character_asset_frame(p):
                continue
            seen.add(p)
            mapped.append({"path": p, "t_sec": float(sample[ii].get("t_sec", 0)), "sample_idx": ii})
        if not mapped:
            continue
        label = str(c.get("label") or f"人物{len(chars_out) + 1}")
        # 避免两个槽都叫「妈妈」却混脸：强制带 appearance 关键词
        appearance = str(c.get("appearance") or "")
        chars_out.append(
            {
                "id": int(c.get("id", len(chars_out))),
                "label": label,
                "appearance": appearance,
                "frames": mapped[:3],
            }
        )

    # 人物帧互斥
    claimed: set[str] = set()
    for ch in chars_out:
        kept = []
        for fr in ch["frames"]:
            if fr["path"] in claimed:
                continue
            claimed.add(fr["path"])
            kept.append(fr)
        ch["frames"] = kept
    chars_out = [c for c in chars_out if c.get("frames")]

    # 用上半身颜色签名纠正「串人」：帧更像另一个人则挪走
    chars_out = _reassign_frames_by_appearance(chars_out)
    chars_out = [c for c in chars_out if c.get("frames")]

    # 标签去重：两个槽 label 几乎一样时，用 appearance 区分
    used_labels: set[str] = set()
    for i, ch in enumerate(chars_out):
        base = re.sub(r"\s+", "", ch.get("label") or f"人物{i + 1}")
        if base in used_labels or any(base in u or u in base for u in used_labels if len(u) > 2):
            ap = (ch.get("appearance") or "")[:18] or f"角色{i + 1}"
            ch["label"] = f"{ch.get('label') or '人物'}·{ap}"
        used_labels.add(re.sub(r"\s+", "", ch["label"]))

    return {
        "characters": chars_out,
        "products": prods_out,
        "sample_count": len(sample),
        "raw": raw[:800],
    }


def _reassign_frames_by_appearance(chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每人算平均上半身色；若某帧更接近别人，则改挂到别人（减少围裙女进妈妈槽）。"""
    if len(chars) < 2:
        return chars

    centroids: list[tuple[float, float, float] | None] = []
    for ch in chars:
        sigs = []
        for fr in ch.get("frames") or []:
            s = _color_sig_upper(fr["path"])
            if s:
                sigs.append(s)
        if not sigs:
            centroids.append(None)
        else:
            n = len(sigs)
            centroids.append(
                (sum(s[0] for s in sigs) / n, sum(s[1] for s in sigs) / n, sum(s[2] for s in sigs) / n)
            )

    # 收集全部帧再重新分配
    all_frames: list[tuple[int, dict]] = []
    for i, ch in enumerate(chars):
        for fr in ch.get("frames") or []:
            all_frames.append((i, fr))

    buckets: list[list[dict]] = [[] for _ in chars]
    for orig_i, fr in all_frames:
        sig = _color_sig_upper(fr["path"])
        if not sig:
            buckets[orig_i].append(fr)
            continue
        best_i = orig_i
        best_d = 1e9
        for j, cen in enumerate(centroids):
            if cen is None:
                continue
            d = _sig_dist(sig, cen)
            if d < best_d:
                best_d = d
                best_i = j
        # 只有明显更像别人时才挪（避免抖动）
        if best_i != orig_i and centroids[orig_i] is not None:
            d_self = _sig_dist(sig, centroids[orig_i])  # type: ignore[arg-type]
            if best_d + 18 < d_self:
                buckets[best_i].append(fr)
            else:
                buckets[orig_i].append(fr)
        else:
            buckets[best_i].append(fr)

    out = []
    for i, ch in enumerate(chars):
        # 去重 path
        seen = set()
        frames = []
        for fr in buckets[i]:
            if fr["path"] in seen:
                continue
            seen.add(fr["path"])
            frames.append(fr)
        ch = dict(ch)
        ch["frames"] = frames[:3]
        out.append(ch)
    return out


def build_asset_slots_with_ai(
    keyframes: list[dict] | None,
    dissect: dict[str, Any] | None,
    out_dir: str | Path,
    *,
    max_views: int = 3,
    whiten_with_agnes: bool = True,
) -> dict[str, Any]:
    """VL 分人 +（可选）Agnes 白底提取，生成互不混淆的资产槽。"""
    from src.studio_pipeline.agnes_client import AgnesImageClient
    from src.studio_pipeline.frame_extract import _to_white

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = [k for k in (keyframes or []) if k.get("path") and Path(k["path"]).exists()]
    if not frames:
        return {"slots": [], "gen_note": "无关键帧"}

    try:
        classified = classify_assets_with_vl(frames, dissect)
    except Exception as e:
        return {"slots": [], "gen_note": f"AI 分人失败：{e}", "error": str(e)}

    has_agnes = bool(os.environ.get("AGNES_API_KEY", "").strip()) and whiten_with_agnes
    agnes = AgnesImageClient() if has_agnes else None
    slots: list[dict[str, Any]] = []
    used_frames: set[str] = set()

    def _fallback_white(crop: Path, white: Path, *, product: bool = False) -> bool:
        size = (768, 768) if product else (720, 1280)
        return _to_white(crop, white, size=size) is not None

    for ci, ch in enumerate(classified.get("characters") or []):
        own = [
            f
            for f in ch.get("frames") or []
            if f["path"] not in used_frames and _is_character_asset_frame(f["path"])
        ]
        if not own:
            continue
        for f in own:
            used_frames.add(f["path"])

        sid = f"char_{ci}"
        label = f"人物{ci + 1}·{ch.get('label') or '出镜者'}"
        appearance = ch.get("appearance") or ""
        desc = "；".join(filter(None, [label, appearance]))
        images: list[dict[str, Any]] = []

        for vi, fr in enumerate(own[:max_views]):
            src = fr["path"]
            t_sec = fr.get("t_sec", 0)
            crop = out / f"{sid}_v{vi}_crop.jpg"
            try:
                from PIL import Image

                Image.open(src).convert("RGB").save(crop, "JPEG", quality=92)
            except Exception:
                continue

            white = out / f"{sid}_v{vi}_white.png"
            source_tag = "agnes"
            char_hint = (
                f"只抠出这一个人：{appearance or label}。"
                "半身或正面人像，不要瓶子特写，不要只剩双手，不要把另一个人抠进来。"
            )
            try:
                if agnes is not None:
                    agnes.extract_subject_white_bg(src, white, kind="character", hint=char_hint)
                else:
                    if not _fallback_white(crop, white):
                        continue
                    source_tag = "local_white"
            except Exception:
                if not _fallback_white(crop, white):
                    continue
                source_tag = "local_white"

            # 白底结果仍像产品则丢弃
            if not _is_character_asset_frame(str(white)) and not _is_character_asset_frame(str(crop)):
                continue

            images.append(
                {
                    "path": str(Path(white).resolve()),
                    "crop_path": str(Path(crop).resolve()),
                    "label": f"{label}·视角{vi + 1}",
                    "view": ["front", "three_quarter", "side"][min(vi, 2)],
                    "t_sec": t_sec,
                    "source_frame": src,
                    "source": source_tag,
                }
            )

        if not images:
            continue
        slots.append(
            {
                "id": sid,
                "type": "character",
                "slot_index": ci,
                "label": label,
                "description": desc,
                "appearance": appearance,
                "box_norm": (0.18, 0.08, 0.82, 0.92),
                "images": images,
                "ai_classified": True,
            }
        )

    for pi, pr in enumerate(classified.get("products") or []):
        own = [
            f
            for f in pr.get("frames") or []
            if f["path"] not in used_frames and _is_product_asset_frame(f["path"])
        ]
        if not own:
            continue
        sid = f"prod_{pi}"
        label = f"产品{pi + 1}·{pr.get('label') or '主推产品'}"
        appearance = pr.get("appearance") or ""
        desc = "；".join(filter(None, [label, appearance]))
        images = []
        for vi, fr in enumerate(own[: max(1, max_views - 1)]):
            src = fr["path"]
            used_frames.add(src)
            crop = out / f"{sid}_v{vi}_crop.jpg"
            try:
                from PIL import Image

                Image.open(src).convert("RGB").save(crop, "JPEG", quality=92)
            except Exception:
                continue
            white = out / f"{sid}_v{vi}_white.png"
            source_tag = "agnes"
            prod_hint = (
                f"只抠商品本身：{appearance or label}。"
                "纯白底产品图，不要人脸，不要半身人像，双手可以裁掉。"
            )
            try:
                if agnes is not None:
                    agnes.extract_subject_white_bg(src, white, kind="product", hint=prod_hint)
                else:
                    if not _fallback_white(crop, white, product=True):
                        continue
                    source_tag = "local_white"
            except Exception:
                if not _fallback_white(crop, white, product=True):
                    continue
                source_tag = "local_white"

            # 白底结果仍是人脸大图 → 丢掉，避免「人当商品」
            if _upper_skin(str(white)) > 0.18 or _upper_skin(str(crop)) > 0.20:
                continue

            images.append(
                {
                    "path": str(Path(white).resolve()),
                    "crop_path": str(Path(crop).resolve()),
                    "label": f"{label}·视角{vi + 1}",
                    "view": "product",
                    "t_sec": fr.get("t_sec", 0),
                    "source_frame": src,
                    "source": source_tag,
                }
            )
        if images:
            slots.append(
                {
                    "id": sid,
                    "type": "product",
                    "slot_index": pi,
                    "label": label,
                    "description": desc,
                    "appearance": appearance,
                    "box_norm": (0.28, 0.25, 0.72, 0.85),
                    "images": images,
                    "ai_classified": True,
                }
            )

    n_char = sum(1 for s in slots if s["type"] == "character")
    n_prod = sum(1 for s in slots if s["type"] == "product")
    note = f"AI分人+{'Agnes白底' if agnes else '本地白底'}：人物{n_char}、产品{n_prod}（已过滤混人/人货混淆）"
    return {
        "slots": slots,
        "gen_note": note,
        "classified": {
            "characters": [
                {"label": c.get("label"), "n_frames": len(c.get("frames") or [])}
                for c in classified.get("characters") or []
            ],
            "products": [
                {"label": p.get("label"), "n_frames": len(p.get("frames") or [])}
                for p in classified.get("products") or []
            ],
        },
    }
