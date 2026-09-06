from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from PIL import Image


def estimate_speech_duration(text: str) -> float:
    text = re.sub(r"\s+", "", text or "")
    if not text:
        return 3.0
    # 中文约 4 字/秒
    return max(2.0, min(15.0, len(text) / 4.0 + 0.5))


def _image_stats(path: str) -> dict[str, float]:
    img = Image.open(path).convert("RGB")
    img.thumbnail((128, 128))
    pixels = list(img.getdata())
    r = sum(p[0] for p in pixels) / len(pixels)
    g = sum(p[1] for p in pixels) / len(pixels)
    b = sum(p[2] for p in pixels) / len(pixels)
    return {"r": r, "g": g, "b": b}


def _color_distance(a: dict[str, float], b: dict[str, float]) -> float:
    return ((a["r"] - b["r"]) ** 2 + (a["g"] - b["g"]) ** 2 + (a["b"] - b["b"]) ** 2) ** 0.5


def run_qc(plan: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    storyboard = plan.get("storyboard", [])
    char_ref = (plan.get("assets") or {}).get("character_ref")
    ref_stats = _image_stats(char_ref) if char_ref and Path(char_ref).exists() else None

    for beat in storyboard:
        idx = beat.get("idx")
        ff = (beat.get("first_frame") or {}).get("path")
        if not ff or not Path(ff).exists():
            issues.append({"beat": idx, "level": "error", "msg": "缺少首帧"})
            continue

        spoken = beat.get("spoken", "")
        dur = beat.get("duration_sec", 5)
        est = estimate_speech_duration(spoken)
        if spoken and abs(dur - est) > 4:
            issues.append(
                {
                    "beat": idx,
                    "level": "warn",
                    "msg": f"口播时长约 {est:.1f}s，镜头 {dur}s，可能不同步",
                }
            )

        if ref_stats:
            dist = _color_distance(ref_stats, _image_stats(ff))
            if dist > 90:
                issues.append(
                    {"beat": idx, "level": "warn", "msg": "首帧色调与角色参考偏差较大，一致性风险"}
                )

        lf = (beat.get("last_frame") or {}).get("path")
        if lf and Path(lf).exists():
            dist_fl = _color_distance(_image_stats(ff), _image_stats(lf))
            if dist_fl > 70:
                issues.append(
                    {"beat": idx, "level": "warn", "msg": "首尾帧色调不一致，插值可能穿帮"}
                )

        if beat.get("status") == "failed":
            issues.append({"beat": idx, "level": "error", "msg": beat.get("error", "生成失败")})

        clip = beat.get("clip_path")
        if clip and not Path(clip).exists():
            issues.append({"beat": idx, "level": "error", "msg": "片段文件缺失"})

    score = max(0, 100 - 15 * sum(1 for i in issues if i["level"] == "error") - 5 * sum(1 for i in issues if i["level"] == "warn"))
    return {
        "score": score,
        "passed": score >= 70 and not any(i["level"] == "error" for i in issues),
        "issues": issues,
        "summary": f"质检得分 {score}，问题 {len(issues)} 项",
    }
