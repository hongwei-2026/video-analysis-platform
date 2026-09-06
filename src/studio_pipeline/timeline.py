"""A 模式时间轴：按原片真实时长重建节拍，保留原片口播/画面语义。"""
from __future__ import annotations

import math
from typing import Any

GARBAGE_MARKERS = (
    "请在",
    "请根据",
    "画面要素",
    "字幕要点",
    "口播或字幕",
    "人物动作、场景",
    "字幕重点",
    "沿用原片",
    "复刻原片",
)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def beat_text_is_garbage(beat: dict) -> bool:
    text = " ".join(
        str(beat.get(k) or "")
        for k in ("spoken_or_subtitle", "spoken", "visual", "role", "first_frame_prompt")
    )
    if any(m in text for m in GARBAGE_MARKERS):
        # 「沿用/复刻」占位视为垃圾；其它模板词亦然
        if any(m in text for m in ("请在", "请根据", "画面要素", "字幕要点", "口播或字幕", "人物动作、场景", "字幕重点")):
            return True
        if "沿用原片" in text or "复刻原片" in text:
            spoken = str(beat.get("spoken") or beat.get("spoken_or_subtitle") or "")
            visual = str(beat.get("visual") or "")
            # 仅占位、无真实内容
            if len(spoken) < 40 and len(visual) < 40:
                return True
    role = str(beat.get("role") or "")
    if role.count("|") >= 3:
        return True
    return False


def timeline_is_broken(beats: list[dict], duration: float) -> bool:
    if not beats:
        return True
    if duration <= 1:
        return False
    ends = [_f(b.get("t_end_sec"), _f(b.get("t_start_sec"))) for b in beats]
    starts = [_f(b.get("t_start_sec")) for b in beats]
    same = sum(1 for s, e in zip(starts, ends) if abs(e - s) < 0.4)
    if same >= max(1, len(beats) // 2):
        return True
    cover = max(ends) - min(starts) if ends else 0
    if cover < duration * 0.4:
        return True
    return False


def choose_story_seg_sec(duration: float) -> float:
    """选 5–10 秒一段，使节拍数约在 5–12（对应剧情段，而非密集体抽帧）。"""
    duration = max(4.0, float(duration))
    best = 6.0
    best_score = 1e9
    for seg in (5.0, 6.0, 7.0, 8.0, 9.0, 10.0):
        n = max(1, int(math.ceil(duration / seg)))
        score = abs(n - 8) + (0 if 5 <= n <= 12 else 20)
        if score < best_score:
            best_score = score
            best = seg
    return best


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _is_placeholder_text(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 8:
        return True
    return any(m in t for m in ("沿用原片", "复刻原片", "请在", "请根据", "字幕要点", "口播或字幕"))


def motion_prompt_from_beat(beat: dict[str, Any]) -> str:
    """从 camera / visual / role 生成可复刻原片的运动提示，禁止空泛自我介绍。"""
    existing = str(beat.get("motion_prompt") or "").strip()
    if existing and "gentle dolly" not in existing.lower() and "keep original camera" not in existing.lower():
        if "自我介绍" not in existing and "introduce" not in existing.lower():
            return existing[:400]

    camera = str(beat.get("camera") or "").strip()
    visual = str(beat.get("visual") or "").strip()
    role = str(beat.get("role") or "").strip()
    parts = [
        "Continue the SAME short-video scene and SAME people; do not restart as a new introduction.",
        "Speech and on-screen captions must be Simplified Chinese only; no English/foreign subtitles.",
        "Match original pacing and camera language; vertical 9:16.",
    ]
    if camera:
        parts.append(f"Camera: {camera}")
    if role:
        parts.append(f"Beat role: {role}")
    if visual and not _is_placeholder_text(visual):
        parts.append(f"Action/composition to continue: {visual[:220]}")
    else:
        parts.append("Keep natural body motion and product interaction continuous from previous shot.")
    return " ".join(parts)[:500]


def fill_beat_from_sources(
    target: dict[str, Any],
    source_beats: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """按时间重叠，把原片拆解的口播/画面/角色填进新剧情段。"""
    if not source_beats:
        return target
    t0 = _f(target.get("t_start_sec"))
    t1 = _f(target.get("t_end_sec"), t0 + 5)
    scored: list[tuple[float, dict]] = []
    for src in source_beats:
        if beat_text_is_garbage(src):
            continue
        s0 = _f(src.get("t_start_sec"))
        s1 = _f(src.get("t_end_sec"), s0 + 5)
        ov = _overlap(t0, t1, s0, s1)
        if ov > 0.15:
            scored.append((ov, src))
    if not scored:
        # 无重叠时取中点最近的非垃圾 beat
        mid = (t0 + t1) / 2
        nearest = None
        best_d = 1e9
        for src in source_beats:
            if beat_text_is_garbage(src):
                continue
            s0 = _f(src.get("t_start_sec"))
            s1 = _f(src.get("t_end_sec"), s0 + 5)
            d = abs((s0 + s1) / 2 - mid)
            if d < best_d:
                best_d = d
                nearest = src
        if nearest is None:
            return target
        scored = [(1.0, nearest)]

    scored.sort(key=lambda x: x[0], reverse=True)
    primary = scored[0][1]

    spoken_parts: list[str] = []
    visual_parts: list[str] = []
    for _ov, src in scored[:3]:
        sp = str(src.get("spoken") or src.get("spoken_or_subtitle") or "").strip()
        vis = str(src.get("visual") or "").strip()
        if sp and not _is_placeholder_text(sp) and sp not in spoken_parts:
            spoken_parts.append(sp)
        if vis and not _is_placeholder_text(vis) and vis not in visual_parts:
            visual_parts.append(vis)

    if spoken_parts:
        target["spoken"] = " / ".join(spoken_parts)[:400]
        target["spoken_or_subtitle"] = target["spoken"]
    elif primary.get("spoken") or primary.get("spoken_or_subtitle"):
        sp = str(primary.get("spoken") or primary.get("spoken_or_subtitle"))
        if not _is_placeholder_text(sp):
            target["spoken"] = sp[:400]
            target["spoken_or_subtitle"] = target["spoken"]

    if visual_parts:
        target["visual"] = "；".join(visual_parts)[:420]
    elif primary.get("visual") and not _is_placeholder_text(str(primary.get("visual"))):
        target["visual"] = str(primary["visual"])[:420]

    if primary.get("role") and "|" not in str(primary.get("role")):
        target["role"] = primary["role"]
    if primary.get("camera"):
        target["camera"] = primary["camera"]
    if primary.get("emotion"):
        target["emotion"] = primary["emotion"]

    target["motion_prompt"] = motion_prompt_from_beat(target)
    return target


def rebuild_beats_from_duration(
    duration: float,
    keyframes: list[dict] | None = None,
    *,
    seg_sec: float | None = None,
    source_beats: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """按原片时长切剧情段；若有 source_beats，按时间重叠回填真实口播/画面。"""
    duration = max(4.0, float(duration))
    seg = float(seg_sec) if seg_sec else choose_story_seg_sec(duration)
    seg = max(5.0, min(10.0, seg))
    beats: list[dict[str, Any]] = []
    t = 0.0
    idx = 1
    kfs = keyframes or []

    while t < duration - 0.25:
        remain = duration - t
        if remain < 3.5 and beats:
            beats[-1]["t_end_sec"] = round(duration, 2)
            beats[-1]["duration_sec"] = int(
                max(4, min(15, round(duration - _f(beats[-1]["t_start_sec"]))))
            )
            fill_beat_from_sources(beats[-1], source_beats)
            break
        length = min(seg, remain)
        api_dur = int(max(4, min(15, round(length))))
        t1 = min(duration, t + length)
        nearest_t = (t + t1) / 2
        if kfs:
            best_d = 1e9
            for k in kfs:
                try:
                    kt = float(k.get("t_sec", 0))
                except (TypeError, ValueError):
                    continue
                d = abs(kt - nearest_t)
                if d < best_d:
                    best_d = d
                    nearest_t = kt
        beat: dict[str, Any] = {
            "idx": idx,
            "t_start_sec": round(t, 2),
            "t_end_sec": round(t1, 2),
            "duration_sec": api_dur,
            "role": f"第{idx}段",
            "spoken_or_subtitle": "",
            "spoken": "",
            "visual": "",
            "motion_prompt": "",
            "gen_mode": "i2va",
            "use_reference_video": True,
            "keyframe_t_sec": round(nearest_t, 2),
        }
        fill_beat_from_sources(beat, source_beats)
        if _is_placeholder_text(str(beat.get("spoken") or "")):
            beat["spoken"] = f"（本段对应原片 {t:.1f}-{t1:.1f}s，沿用该时段剧情与口播，禁止新开自我介绍）"
            beat["spoken_or_subtitle"] = beat["spoken"]
        if _is_placeholder_text(str(beat.get("visual") or "")):
            beat["visual"] = (
                f"继续原片 {t:.1f}-{t1:.1f}s 的同一场景与人物动作（代表帧约 {nearest_t:.1f}s），"
                "不要切换成新的人物介绍镜头"
            )
        beat["motion_prompt"] = motion_prompt_from_beat(beat)
        beats.append(beat)
        t = t1
        idx += 1
        if idx > 40:
            break
    return beats


def repair_beat_timeline(beats: list[dict], duration: float) -> list[dict[str, Any]]:
    """保留有效文案，校正时间轴；过密则合并为 5–10s 段，并按时间重叠回填。"""
    duration = max(4.0, float(duration))
    n = max(1, len(beats))
    target_seg = choose_story_seg_sec(duration)
    target_n = max(1, int(math.ceil(duration / target_seg)))
    if n > target_n + 2:
        return rebuild_beats_from_duration(duration, seg_sec=target_seg, source_beats=beats)

    out: list[dict[str, Any]] = []
    for i, b in enumerate(beats):
        t0 = duration * i / n
        t1 = duration * (i + 1) / n
        nb = dict(b)
        nb["idx"] = i + 1
        nb["t_start_sec"] = round(t0, 2)
        nb["t_end_sec"] = round(t1, 2)
        nb["duration_sec"] = int(max(4, min(15, round(t1 - t0))))
        nb["keyframe_t_sec"] = round((t0 + t1) / 2, 2)
        if beat_text_is_garbage(nb):
            fill_beat_from_sources(nb, beats)
        nb["spoken"] = nb.get("spoken") or nb.get("spoken_or_subtitle") or ""
        nb["spoken_or_subtitle"] = nb.get("spoken_or_subtitle") or nb["spoken"]
        nb["use_reference_video"] = True
        nb["gen_mode"] = nb.get("gen_mode") or "i2va"
        nb["motion_prompt"] = motion_prompt_from_beat(nb)
        out.append(nb)
    return out


def normalize_replica_timeline(
    dissect: dict[str, Any] | None,
    duration: float,
    keyframes: list[dict] | None = None,
) -> dict[str, Any]:
    """校正/重建 A 模式节拍：5–10s 剧情段，覆盖全片，尽量保留原片语义。"""
    d = dict(dissect or {})
    beats = list(d.get("beats") or [])
    garbage_n = sum(1 for b in beats if beat_text_is_garbage(b))
    need_rebuild = (
        not beats
        or garbage_n >= max(1, (len(beats) + 1) // 2)
        or timeline_is_broken(beats, duration)
        or len(beats) > max(14, int(duration / 4) + 2)
    )
    if need_rebuild:
        d["beats"] = rebuild_beats_from_duration(duration, keyframes, source_beats=beats)
        d["_beats_rebuilt"] = True
        d["_beats_rebuild_reason"] = "模板/时间轴损坏或过密，已按 5–10s 重建并回填原片口播画面"
    else:
        d["beats"] = repair_beat_timeline(beats, duration)
        d["_beats_rebuilt"] = False

    meta = dict(d.get("meta") or {})
    meta["estimated_duration_sec"] = int(round(max(4.0, float(duration))))
    d["meta"] = meta
    d["_story_seg_sec"] = choose_story_seg_sec(duration)
    return d


def pick_source_for_beat(
    beat: dict[str, Any],
    keyframes: list[dict] | None,
    *,
    video_path: str | None = None,
    out_image: str | None = None,
) -> dict[str, Any]:
    """为剧情段选一张代表原片帧（段内最近；没有则抽帧）。"""
    from pathlib import Path

    from src.studio_pipeline.video_frames import extract_frame_at

    t0 = _f(beat.get("t_start_sec"))
    t1 = _f(beat.get("t_end_sec"), t0 + 5)
    prefer = _f(beat.get("keyframe_t_sec"), (t0 + t1) / 2)
    kfs = keyframes or []
    in_seg = []
    for k in kfs:
        try:
            kt = float(k.get("t_sec", 0))
        except (TypeError, ValueError):
            continue
        if t0 - 0.15 <= kt <= t1 + 0.15 and k.get("path") and Path(k["path"]).exists():
            in_seg.append(k)
    if in_seg:
        best = min(in_seg, key=lambda k: abs(float(k["t_sec"]) - prefer))
        return {"path": best["path"], "t_sec": float(best["t_sec"]), "extracted": False}

    if kfs:
        valid = [k for k in kfs if k.get("path") and Path(k["path"]).exists()]
        if valid:
            best = min(valid, key=lambda k: abs(_f(k.get("t_sec")) - prefer))
            if abs(_f(best.get("t_sec")) - prefer) <= 2.5:
                return {"path": best["path"], "t_sec": float(best["t_sec"]), "extracted": False}

    if video_path and out_image:
        p = extract_frame_at(video_path, out_image, prefer)
        return {"path": str(p), "t_sec": round(prefer, 2), "extracted": True}

    raise ValueError(f"无法为第 {beat.get('idx')} 段找到原片关键帧")
