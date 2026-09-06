"""从关键帧按人物/产品分槽提取多角度白底资产。"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

CHAR_VIEWS = ("正面", "三分之二侧面", "侧面")
PROD_VIEWS = ("特写", "手持", "使用中")

# 人物：尽量半身；产品：偏下/居中，避免整个人
CHAR_BOXES = [
    (0.08, 0.05, 0.72, 0.92),
    (0.28, 0.05, 0.92, 0.92),
    (0.18, 0.05, 0.82, 0.92),
]
PROD_BOXES = {
    "bottle": (0.35, 0.35, 0.95, 0.95),
    "fruit": (0.15, 0.35, 0.85, 0.95),
    "default": (0.30, 0.42, 0.90, 0.96),
}


def _frame_paths(keyframes: list[dict] | None) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for k in keyframes or []:
        if not isinstance(k, dict):
            continue
        p = k.get("path")
        if not p or not Path(p).exists():
            continue
        try:
            t = float(k.get("t_sec", 0))
        except (TypeError, ValueError):
            t = 0.0
        out.append((p, t))
    return out


def _pick_by_time(frames: list[tuple[str, float]], t_sec: float) -> tuple[str, float] | None:
    if not frames:
        return None
    best = frames[0]
    best_d = float("inf")
    for item in frames:
        d = abs(item[1] - t_sec)
        if d < best_d:
            best_d = d
            best = item
    return best


def _beat_time(beat: dict) -> float | None:
    for key in ("t_start_sec", "t_sec", "t_end_sec"):
        try:
            return float(beat.get(key, 0))
        except (TypeError, ValueError):
            continue
    return None


def _img_fp(path: str) -> str:
    try:
        return hashlib.md5(Path(path).read_bytes()).hexdigest()
    except Exception:
        return path


def _beat_text(b: dict) -> str:
    return " ".join(
        str(b.get(k, "") or "")
        for k in ("role", "visual", "spoken_or_subtitle", "spoken", "camera", "emotion")
    )


def _all_text(dissect: dict | None) -> str:
    parts = [_beat_text(b) for b in (dissect or {}).get("beats") or []]
    meta = (dissect or {}).get("meta") or {}
    for k in ("product", "topic", "one_line_summary", "style"):
        parts.append(str(meta.get(k, "") or ""))
    for c in (dissect or {}).get("characters") or []:
        parts.append(str(c.get("role", "") or ""))
        parts.append(str(c.get("appearance", "") or ""))
    for p in (dissect or {}).get("products") or []:
        parts.append(str(p.get("name_guess", "") or ""))
        parts.append(str(p.get("category", "") or ""))
        parts.append(str(p.get("visual", "") or ""))
    skel = (dissect or {}).get("script_skeleton") or {}
    parts.append(str(skel.get("spoken_script_full", "") or ""))
    return " ".join(parts)


def _slot_label_char(c: dict, idx: int) -> str:
    role = str(c.get("role") or "").strip().split("|")[0].strip()
    app = str(c.get("appearance") or c.get("gender_age") or "").strip()
    if role and app:
        return f"人物{idx + 1}·{role}（{app[:18]}）"
    if role:
        return f"人物{idx + 1}·{role}"
    if app:
        return f"人物{idx + 1}·{app[:24]}"
    return f"人物{idx + 1}"


def _slot_label_prod(p: dict, idx: int) -> str:
    name = str(p.get("name_guess") or p.get("category") or "").strip()
    return f"产品{idx + 1}·{name}" if name else f"产品{idx + 1}"


def _char_keywords(c: dict) -> list[str]:
    bits: list[str] = []
    for k in ("role", "appearance", "gender_age", "clothing"):
        v = str(c.get(k) or "").strip()
        if not v:
            continue
        for part in re.split(r"[|、,/；;]", v):
            part = part.strip()
            if len(part) >= 2:
                bits.append(part)
    return bits


def _color_sig(path: str, box: tuple[float, float, float, float]) -> tuple[float, float, float] | None:
    """人物半身区域平均色，用于区分不同穿着的人。"""
    from PIL import Image

    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        x0, y0, x1, y1 = box
        crop = img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1)))
        crop = crop.resize((32, 48))
        pixels = list(crop.getdata())
        n = max(1, len(pixels))
        r = sum(p[0] for p in pixels) / n
        g = sum(p[1] for p in pixels) / n
        b = sum(p[2] for p in pixels) / n
        return (r, g, b)
    except Exception:
        return None


def _dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _cluster_frames_by_appearance(
    frames: list[tuple[str, float]],
    *,
    max_clusters: int = 2,
) -> list[list[tuple[str, float]]]:
    """按半身平均色硬分成最多 2 簇；每帧只属于一簇，互不混用。"""
    if not frames:
        return []
    box = (0.18, 0.10, 0.82, 0.70)
    scored: list[tuple[tuple[str, float], tuple[float, float, float]]] = []
    for fr in frames:
        sig = _color_sig(fr[0], box)
        if sig:
            scored.append((fr, sig))
    if len(scored) < 2:
        return [frames]

    # 选差异最大的两个种子
    seed_a, seed_b = scored[0][1], scored[0][1]
    best = -1.0
    for i in range(len(scored)):
        for j in range(i + 1, len(scored)):
            d = _dist(scored[i][1], scored[j][1])
            if d > best:
                best = d
                seed_a, seed_b = scored[i][1], scored[j][1]

    # 色差不够 → 单人片
    if best < 55:
        return [frames]

    c0: list[tuple[str, float]] = []
    c1: list[tuple[str, float]] = []
    for fr, sig in scored:
        d0 = _dist(sig, seed_a)
        d1 = _dist(sig, seed_b)
        # 必须明显更靠近某一簇，否则丢弃（宁缺毋滥，避免混人）
        if abs(d0 - d1) < 12:
            continue
        if d0 < d1:
            c0.append(fr)
        else:
            c1.append(fr)

    clusters = [c for c in (c0, c1) if len(c) >= 1]
    if len(clusters) < 2:
        return [frames]
    clusters.sort(key=lambda cl: min(t for _, t in cl))
    return clusters[:max_clusters]


def infer_characters_from_dissect(dissect: dict | None) -> list[dict[str, Any]]:
    """结合脚本/VL/穿着关键词推断多人。"""
    meta = (dissect or {}).get("meta") or {}
    orig = list((dissect or {}).get("characters") or [])
    text = _all_text(dissect)

    # 拆 VL 用 | 糊成一个人的角色
    expanded: list[dict[str, Any]] = []
    for c in orig:
        role = str(c.get("role") or "")
        parts = [p.strip() for p in re.split(r"[|/]+", role) if p.strip() and p.strip() not in ("可替换",)]
        # 过滤模板词
        parts = [p for p in parts if p not in ("配角", "路人", "出镜") or len(parts) == 1]
        if len(parts) >= 2 and any(k in role for k in ("主播", "妈妈", "阿姨", "女儿", "配角")):
            for i, p in enumerate(parts[:2]):
                expanded.append(
                    {
                        "role": p,
                        "appearance": str(c.get("appearance") or "") if i == 0 else f"与{parts[0]}不同的另一位出镜者",
                        "replaceable": True,
                    }
                )
        else:
            expanded.append(c)

    role_defs: list[dict[str, Any]] = []
    if any(k in text for k in ("妈妈", "母亲", "中年女", "毛衣")):
        role_defs.append({"role": "妈妈", "appearance": "中年女性，米色/浅色毛衣或居家服，厨房"})
    if any(k in text for k in ("围裙", "年轻", "女儿", "主播", "博主", "灰T", "灰 T")):
        role_defs.append({"role": "年轻女主播", "appearance": "年轻女性，灰T恤+白围裙，厨房出镜"})
    if "阿姨" in text and not any(r["role"] == "妈妈" for r in role_defs):
        role_defs.append({"role": "阿姨", "appearance": "年长女性，居家服"})

    if len(role_defs) >= 2:
        return role_defs[:3]
    if len(expanded) >= 2:
        return expanded[:3]
    if role_defs and expanded:
        base = expanded[0]
        if base.get("role") != role_defs[0].get("role"):
            return [base, role_defs[0]]
        return [role_defs[0], {"role": "第二人物", "appearance": "与第一位穿着不同的出镜者"}]
    if role_defs:
        return role_defs[:2] if len(role_defs) >= 2 else role_defs + [
            {"role": "第二人物", "appearance": "与第一位穿着不同的出镜者"}
        ]
    if expanded:
        # 即便 VL 只给 1 人，脚本里有两人迹象也补第二槽
        if any(k in text for k in ("妈妈", "两人", "对话", "配角", "阿姨")):
            return expanded[:1] + [{"role": "第二人物", "appearance": "与主角不同的另一位出镜者"}]
        return expanded[:1]
    return [{"role": "出镜人物", "appearance": meta.get("one_line_summary", "短视频人物")}]


def infer_products_from_dissect(dissect: dict | None) -> list[dict[str, Any]]:
    products = list((dissect or {}).get("products") or [])
    meta = (dissect or {}).get("meta") or {}
    text = _all_text(dissect)
    cleaned: list[dict[str, Any]] = []

    for p in products:
        name = str(p.get("name_guess") or p.get("category") or "").strip()
        if not name or name in ("人物", "出镜者", "主播"):
            continue
        kind = "default"
        if any(k in name + text for k in ("草莓", "果蔬", "水果")):
            kind = "fruit"
        if any(k in name + text for k in ("洗洁精", "清洁剂", "洗衣液", "瓶")):
            kind = "bottle"
        cleaned.append({**p, "name_guess": name, "_crop_kind": kind})

    # 洗洁精 + 草莓经常同片出现：拆成两个产品槽更清晰
    has_soap = any(
        any(k in str(p.get("name_guess") or "") for k in ("洗碗", "洗洁精", "清洁剂", "洗衣液"))
        for p in cleaned
    )
    if not has_soap and any(k in text for k in ("洗洁精", "清洁剂", "一瓶")):
        cleaned.insert(0, {"name_guess": "洗洁精", "category": "清洁剂", "_crop_kind": "bottle"})

    if not cleaned:
        guess = meta.get("product") or meta.get("topic") or "种草产品"
        kind = "bottle" if any(k in str(guess) + text for k in ("洗碗", "清洁", "瓶", "洗洁精")) else "default"
        cleaned = [{"name_guess": guess, "category": guess, "_crop_kind": kind}]

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in cleaned:
        key = str(p.get("name_guess") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    return deduped[:2]


def _beat_matches_char(beat: dict, keywords: list[str], slot_idx: int, label: str = "") -> bool:
    text = _beat_text(beat)
    label_t = label + " ".join(keywords)
    if "妈妈" in label_t and any(k in text for k in ("妈妈", "母亲", "中年")):
        return True
    if any(k in label_t for k in ("主播", "年轻", "围裙")) and any(
        k in text for k in ("主播", "女儿", "年轻", "围裙", "博主", "讲解")
    ):
        return True
    if any(k in text for k in keywords if len(k) >= 2):
        return True
    if slot_idx == 1 and any(k in text for k in ("阿姨", "大叔", "嘉宾", "配角", "路人", "老人", "女二", "妈妈")):
        return True
    if slot_idx == 0 and any(k in text for k in ("主播", "博主", "女主", "出镜", "口播", "围裙")):
        return True
    return False


def active_slots_for_beat(beat: dict, slots: list[dict], dissect: dict | None) -> list[str]:
    text = _beat_text(beat)
    product_kw = ("洗洁精", "清洁剂", "洗衣液", "产品", "商品", "特写", "手持", "包装", "试用", "瓶", "一瓶", "果蔬")
    person_kw = ("人物", "出镜", "口播", "博主", "女主", "妈妈", "阿姨", "讲解", "厨房", "围裙", "毛衣", "她", "他", "站在")
    has_person = any(k in text for k in person_kw)
    product_show = any(k in text for k in product_kw)

    active: list[str] = []
    chars = [s for s in slots if s.get("type") == "character"]
    for s in chars:
        idx = int(s.get("slot_index", 0))
        if _beat_matches_char(beat, _char_keywords(s), idx, str(s.get("label", ""))):
            active.append(s["id"])
    if product_show and (not has_person or any(k in text for k in ("洗洁精", "瓶", "手持", "特写", "一瓶", "产品"))):
        for s in slots:
            if s.get("type") == "product" and s["id"] not in active:
                active.append(s["id"])
    # 纯人物镜头：至少绑一个已替换人物槽
    if has_person and not active:
        for s in chars:
            active.append(s["id"])
            break
    return active


def _sig_dist(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _slot_color_signature(slot: dict) -> tuple[float, float, float] | None:
    """用槽位已提取裁剪图估穿着色。"""
    for img in slot.get("images") or []:
        p = img.get("crop_path") or img.get("path")
        if p and Path(p).exists():
            sig = _color_sig(p, (0.1, 0.1, 0.9, 0.75))
            if sig:
                return sig
    return None


def _frame_has_product_cue(path: str) -> bool:
    """粗判关键帧是否像产品露出（非大面积人像）。"""
    from PIL import Image

    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        # 看下半/前景区域
        crop = img.crop((int(w * 0.25), int(h * 0.4), int(w * 0.95), int(h * 0.95))).resize((40, 40))
        pixels = list(crop.getdata())
        n = max(1, len(pixels))
        skin = sum(
            1
            for r, g, b in pixels
            if r > 90 and g > 60 and b > 40 and r >= g >= b and (r - b) > 15
        )
        # 肤色占比低 → 更可能是产品/道具特写
        return (skin / n) < 0.22
    except Exception:
        return False


def _frame_has_person(path: str) -> bool:
    """全帧是否有明显人物（看中心半身区肤色）。"""
    from PIL import Image

    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        crop = img.crop((int(w * 0.2), int(h * 0.08), int(w * 0.8), int(h * 0.7))).resize((40, 48))
        pixels = list(crop.getdata())
        n = max(1, len(pixels))
        skin = sum(
            1
            for r, g, b in pixels
            if r > 90 and g > 60 and b > 40 and r >= g >= b and (r - b) > 15
        )
        return (skin / n) > 0.12
    except Exception:
        return True


def pick_slots_for_keyframe(
    keyframe_path: str,
    t_sec: float,
    slots: list[dict],
    beat: dict | None,
    dissect: dict | None,
    *,
    approved_ids: set[str] | None = None,
) -> list[str]:
    """只返回「本帧该换、且用户已生成替换资产」的槽。

    关键：先识别原片是谁，再看用户有没有为「这个人」生成替换。
    只生成了人物1 → 人物2镜头、产品镜头一律保持原片。
    """
    approved_ids = approved_ids or set()
    if not approved_ids:
        return []

    chars_all = [s for s in slots if s.get("type") == "character"]
    approved_chars = [s for s in chars_all if s["id"] in approved_ids]
    approved_prods = [s for s in slots if s.get("type") == "product" and s["id"] in approved_ids]
    beat_text = _beat_text(beat or {})

    personish = _frame_has_person(keyframe_path)
    productish = _frame_has_product_cue(keyframe_path)

    # 纯产品特写：绝不用人物资产去换
    if productish and not personish:
        if approved_prods:
            return [approved_prods[0]["id"]]
        return []

    if not chars_all:
        return []

    # 1) 时间命中：该槽提取帧时刻接近本关键帧 → 优先认作该角色出镜
    time_hit = None
    best_dt = 2.8
    for s in approved_chars:
        for img in s.get("images") or []:
            try:
                dt = abs(float(img.get("t_sec", -9999)) - float(t_sec))
            except (TypeError, ValueError):
                continue
            if dt < best_dt:
                best_dt = dt
                time_hit = s
    if time_hit is not None:
        active = [time_hit["id"]]
        if approved_prods and any(k in beat_text for k in ("瓶", "手持", "洗洁精", "一瓶", "产品")):
            active.append(approved_prods[0]["id"])
        return active

    # 2) 颜色签名认人
    frame_sig = _color_sig(keyframe_path, (0.12, 0.08, 0.88, 0.78))
    best_slot = None
    best_d = float("inf")
    if frame_sig:
        for s in chars_all:
            sig = _slot_color_signature(s)
            if not sig:
                continue
            d = _sig_dist(frame_sig, sig)
            if d < best_d:
                best_d = d
                best_slot = s

    if best_slot is not None and best_slot["id"] in approved_ids:
        active = [best_slot["id"]]
        if approved_prods and any(k in beat_text for k in ("瓶", "手持", "洗洁精", "一瓶", "产品")):
            active.append(approved_prods[0]["id"])
        return active

    # 认出来了但用户没给这个人生成替换 → 原片保留
    if best_slot is not None and best_slot["id"] not in approved_ids:
        return []

    # 3) 有人物画面、且只批准了一个人物槽：默认替换该槽（避免漏认导致原角色残留）
    if personish and len(approved_chars) == 1:
        active = [approved_chars[0]["id"]]
        if approved_prods and any(k in beat_text for k in ("瓶", "手持", "洗洁精", "一瓶", "产品")):
            active.append(approved_prods[0]["id"])
        return active

    return []


def box_for_slot_on_frame(
    slot: dict,
    keyframe_path: str,
    t_sec: float,
    w: int,
    h: int,
) -> tuple[int, int, int, int]:
    """取与该关键帧时间最近的裁剪框；没有则用槽位默认框。"""
    best_box = slot.get("box_norm")
    best_dt = float("inf")
    for img in slot.get("images") or []:
        try:
            dt = abs(float(img.get("t_sec", 0)) - t_sec)
        except (TypeError, ValueError):
            continue
        if dt < best_dt and img.get("box_norm"):
            best_dt = dt
            best_box = img["box_norm"]
    if not best_box:
        if slot.get("type") == "product":
            best_box = (0.45, 0.38, 0.96, 0.92)
        else:
            best_box = (0.12, 0.04, 0.88, 0.62)  # 人物上半身，避免盖住手持产品
    x0, y0, x1, y1 = best_box
    return int(w * x0), int(h * y0), int(w * x1), int(h * y1)


def _collect_times_for_slot(
    dissect: dict | None,
    frames: list[tuple[str, float]],
    slot_idx: int,
    keywords: list[str],
    max_n: int,
    *,
    label: str = "",
    preferred_frames: list[tuple[str, float]] | None = None,
) -> list[tuple[float, str]]:
    slots: list[tuple[float, str]] = []
    for b in (dissect or {}).get("beats") or []:
        if not _beat_matches_char(b, keywords, slot_idx, label):
            continue
        t = _beat_time(b)
        if t is None:
            continue
        if any(abs(t - s[0]) < 1.2 for s in slots):
            continue
        visual = str(b.get("visual", ""))
        if "侧" in visual:
            view = "侧面"
        elif slot_idx == 0 and len(slots) == 0:
            view = "正面"
        else:
            view = CHAR_VIEWS[min(len(slots), len(CHAR_VIEWS) - 1)]
        slots.append((t, view))
        if len(slots) >= max_n:
            break

    pool = preferred_frames if preferred_frames else frames
    if pool and len(slots) < max_n:
        # 均匀从该人物簇取帧，避免两个人采到同一帧
        duration = max((f[1] for f in frames), default=10) or 10
        for i, fr in enumerate(pool):
            if len(slots) >= max_n:
                break
            t = fr[1]
            if any(abs(t - s[0]) < 1.2 for s in slots):
                continue
            # 不同人物错开采样比例
            if preferred_frames is None:
                fracs = (0.12, 0.38, 0.62, 0.85) if slot_idx == 0 else (0.25, 0.48, 0.72, 0.92)
                t = duration * fracs[min(i, len(fracs) - 1)]
            slots.append((t, CHAR_VIEWS[min(len(slots), len(CHAR_VIEWS) - 1)]))
    slots.sort(key=lambda x: x[0])
    return slots[:max_n]


def _collect_prod_times(
    dissect: dict | None,
    frames: list[tuple[str, float]],
    product: dict,
    max_n: int,
) -> list[tuple[float, str]]:
    """只采真正的产品镜头，禁止拿人物全景滥竽充数。"""
    name = str(product.get("name_guess") or "")
    text_all = _all_text(dissect)
    hard_kw = ("洗洁精", "清洁剂", "洗衣液", "瓶", "产品特写", "手持产品", "包装")
    if "草莓" in name:
        hard_kw = ("草莓", "果蔬", "清洗", "特写")

    slots: list[tuple[float, str]] = []
    try:
        t0 = float(product.get("first_appear_sec") or 0)
        if t0 > 0.5:
            slots.append((t0, "特写"))
    except (TypeError, ValueError):
        pass

    for b in (dissect or {}).get("beats") or []:
        text = _beat_text(b)
        if not any(k in text for k in hard_kw):
            # 弱匹配：产品名出现且视觉像特写
            if name and name[:2] in text and any(k in text for k in ("特写", "手持", "展示", "瓶")):
                pass
            else:
                continue
        t = _beat_time(b)
        if t is None or any(abs(t - s[0]) < 1.0 for s in slots):
            continue
        view = "特写" if "特写" in text else ("手持" if "手持" in text or "拿" in text else PROD_VIEWS[min(len(slots), 2)])
        slots.append((t, view))
        if len(slots) >= max_n:
            break

    # 仍不够：从后半段找（产品常后出），但之后会用 _looks_like_product 过滤
    if frames and len(slots) < max_n:
        duration = max(f[1] for f in frames) or 10
        for frac in (0.55, 0.68, 0.80, 0.90):
            if len(slots) >= max_n:
                break
            t = duration * frac
            if any(abs(t - s[0]) < 1.5 for s in slots):
                continue
            slots.append((t, "特写"))
    return slots[:max_n]


def _looks_like_person_crop(crop_path: Path) -> bool:
    """粗判：肤色像素过高 → 更像人物而非产品。"""
    from PIL import Image

    try:
        img = Image.open(crop_path).convert("RGB").resize((48, 64))
        pixels = list(img.getdata())
        n = max(1, len(pixels))
        skin = 0
        for r, g, b in pixels:
            if r > 90 and g > 60 and b > 40 and r >= g >= b and (r - b) > 15:
                skin += 1
        return (skin / n) > 0.28
    except Exception:
        return False


def _looks_like_product_crop(crop_path: Path, kind: str) -> bool:
    """产品裁剪应明显不是半身人像。"""
    if _looks_like_person_crop(crop_path):
        return False
    from PIL import Image

    try:
        img = Image.open(crop_path).convert("RGB").resize((48, 48))
        pixels = list(img.getdata())
        n = max(1, len(pixels))
        # 果蔬：偏红
        if kind == "fruit":
            red = sum(1 for r, g, b in pixels if r > 120 and r > g + 20 and r > b + 20)
            return (red / n) > 0.12
        # 瓶装：色彩对比/非肤色即可
        return True
    except Exception:
        return True


def _crop_region(src: str, box_norm: tuple[float, float, float, float], out_crop: Path) -> Path | None:
    from PIL import Image

    try:
        img = Image.open(src).convert("RGB")
        w, h = img.size
        x0, y0, x1, y1 = box_norm
        crop = img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1)))
        out_crop.parent.mkdir(parents=True, exist_ok=True)
        crop.save(out_crop, quality=90)
        return out_crop
    except Exception:
        return None


def _to_white(crop: Path, white: Path, *, size: tuple[int, int]) -> str | None:
    from src.studio_pipeline.image_gen import compose_white_bg

    try:
        compose_white_bg(str(crop), white, size=size)
        return str(white.resolve())
    except Exception:
        return None


def _extract_views_for_slot(
    slot_id: str,
    slot_type: str,
    slot_idx: int,
    label: str,
    description: str,
    times: list[tuple[float, str]],
    frames: list[tuple[str, float]],
    out: Path,
    max_views: int = 3,
    *,
    box: tuple[float, float, float, float] | None = None,
    prod_kind: str = "default",
    frame_pool: list[tuple[str, float]] | None = None,
) -> dict[str, Any]:
    if box is None:
        box = CHAR_BOXES[min(slot_idx, len(CHAR_BOXES) - 1)] if slot_type == "character" else PROD_BOXES.get(prod_kind, PROD_BOXES["default"])
    size = (768, 1024) if slot_type == "character" else (768, 768)
    images: list[dict[str, Any]] = []
    used_frames: set[str] = set()
    used_fp: set[str] = set()
    pool = frame_pool or frames

    for i, (t_sec, view) in enumerate(times[: max_views + 4]):
        if len(images) >= max_views:
            break
        pick = _pick_by_time(pool if pool else frames, t_sec)
        if not pick:
            pick = _pick_by_time(frames, t_sec)
        if not pick:
            continue
        src, t_real = pick
        if src in used_frames:
            continue
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", view)[:12]
        crop_path = out / f"{slot_id}_{len(images)}_{safe}_crop.jpg"
        if not _crop_region(src, box, crop_path):
            continue
        if slot_type == "product" and not _looks_like_product_crop(crop_path, prod_kind):
            try:
                crop_path.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        if slot_type == "character" and not _looks_like_person_crop(crop_path):
            # 人物槽裁到空景/产品：跳过
            try:
                crop_path.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        fp = _img_fp(str(crop_path))
        if fp in used_fp:
            continue
        white_path = out / f"{slot_id}_{len(images)}_{safe}_white.jpg"
        white = _to_white(crop_path, white_path, size=size)
        if not white:
            continue
        used_frames.add(src)
        used_fp.add(fp)
        images.append(
            {
                "path": white,
                "crop_path": str(crop_path.resolve()),
                "label": f"{label}·{view}（白底）",
                "view": view,
                "t_sec": round(t_real, 2),
                "source_frame": src,
                "source": "keyframe",
                "box_norm": box,
            }
        )

    return {
        "id": slot_id,
        "type": slot_type,
        "slot_index": slot_idx,
        "label": label,
        "description": description,
        "box_norm": box,
        "images": images,
    }


def build_asset_slots(
    keyframes: list[dict] | None,
    dissect: dict[str, Any] | None,
    out_dir: str | Path,
    *,
    max_views: int = 3,
) -> dict[str, Any]:
    """按人物/产品分槽提取；人物用颜色聚类拆人，产品过滤人像误检。"""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = _frame_paths(keyframes)
    chars = infer_characters_from_dissect(dissect)
    products = infer_products_from_dissect(dissect)

    # 视觉聚类：强制拆出 2 个穿着不同的人
    clusters = _cluster_frames_by_appearance(frames, max_clusters=2)
    if len(clusters) >= 2 and len(chars) < 2:
        chars = [
            chars[0] if chars else {"role": "人物A", "appearance": "穿着类型A"},
            {"role": "人物B", "appearance": "穿着与人物A明显不同"},
        ]
    if len(clusters) >= 2 and len(chars) == 1:
        chars.append({"role": "第二人物", "appearance": "与第一位穿着不同的出镜者"})

    # 保证至少尝试 2 人（本片常见母女同框）
    text = _all_text(dissect)
    if len(chars) < 2 and any(k in text for k in ("妈妈", "围裙", "毛衣", "两人", "配角")):
        chars.append({"role": "第二人物", "appearance": "另一位出镜者"})

    slots: list[dict[str, Any]] = []
    used_char_frames: set[str] = set()
    for idx, c in enumerate(chars[:3]):
        sid = f"char_{idx}"
        preferred = clusters[idx] if idx < len(clusters) else None
        # 互斥：已分给别人的帧不再用
        if preferred:
            preferred = [(p, t) for p, t in preferred if p not in used_char_frames]
        if preferred:
            # 只从该人物专属帧取时间点，禁止跨人混帧
            times = [
                (t, CHAR_VIEWS[min(i, len(CHAR_VIEWS) - 1)])
                for i, (_, t) in enumerate(sorted(preferred, key=lambda x: x[1])[:max_views])
            ]
            # 用簇内实际样貌重写标签，避免「年轻女主播」槽里塞进妈妈图
            sample = preferred[0][0]
            sig = _color_sig(sample, (0.18, 0.10, 0.82, 0.70))
            if sig and sig[0] + sig[1] > sig[2] + 80:
                c = {"role": "妈妈/毛衣出镜", "appearance": "中年女性，浅色毛衣或居家服"}
            elif "围裙" in str(c.get("appearance", "")) or "年轻" in str(c.get("role", "")):
                pass
            else:
                c = {**c, "appearance": c.get("appearance") or "厨房出镜人物"}
        else:
            times = _collect_times_for_slot(
                dissect, frames, idx, _char_keywords(c), max_views, label=_slot_label_char(c, idx)
            )
        label = _slot_label_char(c, idx)
        desc = "；".join(filter(None, [label, *_char_keywords(c)]))
        slot = _extract_views_for_slot(
            sid,
            "character",
            idx,
            label,
            desc,
            times,
            frames,
            out,
            max_views,
            box=CHAR_BOXES[min(idx, len(CHAR_BOXES) - 1)],
            frame_pool=preferred,
        )
        # 再次互斥登记
        for img in slot.get("images") or []:
            sf = img.get("source_frame")
            if sf:
                used_char_frames.add(sf)
        if slot["images"]:
            slots.append(slot)

    for idx, p in enumerate(products[:2]):
        sid = f"prod_{idx}"
        label = _slot_label_prod(p, idx)
        kind = str(p.get("_crop_kind") or "default")
        desc = " · ".join(
            filter(None, [str(p.get("name_guess") or ""), str(p.get("category") or ""), str(p.get("visual") or "")])
        )
        times = _collect_prod_times(dissect, frames, p, max_views)
        slot = _extract_views_for_slot(
            sid,
            "product",
            idx,
            label,
            desc,
            times,
            frames,
            out,
            max_views,
            box=PROD_BOXES.get(kind, PROD_BOXES["default"]),
            prod_kind=kind,
        )
        if slot["images"]:
            slots.append(slot)
        elif frames:
            # 产品过滤太严时：放宽一次，仍用产品框
            loose = _extract_views_for_slot(
                sid,
                "product",
                idx,
                label,
                desc,
                times or [(frames[len(frames) // 2][1], "特写")],
                frames,
                out,
                1,
                box=PROD_BOXES.get(kind, PROD_BOXES["default"]),
                prod_kind="default",
            )
            # 手动跳过 person check：复用已有逻辑但 kind=default 仍会拒人像
            if loose["images"]:
                slots.append(loose)

    note = "；".join(f"{s['label']} {len(s['images'])}张" for s in slots) or "无可用资产"
    n_char = sum(1 for s in slots if s["type"] == "character")
    n_prod = sum(1 for s in slots if s["type"] == "product")
    return {
        "slots": slots,
        "gen_note": f"已分槽：人物{n_char}个、产品{n_prod}个 → {note}",
    }


def extract_multi_view_assets(
    keyframes: list[dict] | None,
    dissect: dict[str, Any] | None,
    out_dir: str | Path,
    **_,
) -> dict[str, Any]:
    data = build_asset_slots(keyframes, dissect, out_dir)
    slots = data["slots"]
    char_views = [img for s in slots if s["type"] == "character" for img in s["images"]]
    prod_views = [img for s in slots if s["type"] == "product" for img in s["images"]]
    result = {**data, "char_views": char_views, "prod_views": prod_views}
    if char_views:
        result["char_crop"] = char_views[0].get("crop_path")
        result["char_white"] = char_views[0]["path"]
        result["char_frame"] = char_views[0].get("source_frame")
    if prod_views:
        result["prod_crop"] = prod_views[0].get("crop_path")
        result["prod_white"] = prod_views[0]["path"]
        result["prod_frame"] = prod_views[0].get("source_frame")
    return result


def pick_reference_crops(
    keyframes: list[dict] | None,
    dissect: dict[str, Any] | None,
    out_dir: str | Path,
) -> dict[str, str]:
    data = extract_multi_view_assets(keyframes, dissect, out_dir)
    out: dict[str, str] = {}
    for k in ("char_crop", "char_white", "char_frame", "prod_crop", "prod_white", "prod_frame"):
        if data.get(k):
            out[k] = data[k]
    return out


def extract_reference_assets(keyframes: list[dict] | None, out_dir: str | Path) -> dict[str, str]:
    refs = pick_reference_crops(keyframes, None, out_dir)
    out: dict[str, str] = {}
    if refs.get("char_crop"):
        out["ref_character"] = refs["char_crop"]
    if refs.get("prod_crop"):
        out["ref_product"] = refs["prod_crop"]
    if refs.get("char_frame"):
        out["source_frame"] = refs["char_frame"]
    return out
