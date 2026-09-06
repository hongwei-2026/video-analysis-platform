from __future__ import annotations

import json
from typing import Any

import torch

from src.video_platform.utils import extract_json

SCRIPT_SYSTEM = (
    "你是爆款短视频编导。根据用户输入输出可拍摄的结构脚本 JSON。"
    "字段含 meta、hook、beats、script_skeleton、replication_notes、characters、products。"
    "只输出合法 JSON，不要 Markdown 围栏。"
)

DIRECTOR_SYSTEM = (
    "你是分镜导演。根据脚本 JSON 输出 storyboard 规划 JSON，包含 beats 数组。"
    "每个 beat 含：idx、role、duration_sec、motion_prompt、spoken、gen_mode(t2va|i2va|i2va_fl|r2va)、"
    "first_frame_prompt、last_frame_prompt(可选)、use_reference_video(布尔)。"
    "motion_prompt 用电影运镜动词，首尾帧 prompt 保持光线色调人物一致。只输出 JSON。"
)

ASSET_SYSTEM = (
    "你是视觉资产策划。根据脚本输出资产规划 JSON："
    "character_sheet(人设描述+angles数组，每项含id/label/prompt)、"
    "product(prompt)、scene_style(prompt)。只输出 JSON。"
)


def generate_text(system: str, user: str, max_new_tokens: int = 2800) -> str:
    """纯文本生成（非 JSON）。"""
    from src.studio_pipeline.agnes_llm import agnes_chat_text, use_agnes_llm

    if use_agnes_llm():
        return agnes_chat_text(system, user, max_new_tokens=max_new_tokens)

    from src.studio_pipeline.model_loader import load_script_model as _load

    tokenizer, model = _load()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=0.65,
            top_p=0.9,
            repetition_penalty=1.08,
        )
    return tokenizer.decode(out[0][inputs["input_ids"].shape[-1] :], skip_special_tokens=True).strip()


def _generate_json(system: str, user: str, max_new_tokens: int = 1400) -> dict[str, Any]:
    from src.studio_pipeline.agnes_llm import agnes_chat_text, use_agnes_llm

    if use_agnes_llm():
        text = agnes_chat_text(system, user, max_new_tokens=max_new_tokens)
        return extract_json(text)

    from src.studio_pipeline.model_loader import load_script_model as _load

    tokenizer, model = _load()

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            repetition_penalty=1.05,
        )
    text = tokenizer.decode(out[0][inputs["input_ids"].shape[-1] :], skip_special_tokens=True)
    return extract_json(text)


def pretty_json(data: dict | list | str) -> str:
    if isinstance(data, str):
        try:
            data = extract_json(data)
        except Exception:
            return data
    return json.dumps(data, ensure_ascii=False, indent=2)


def meta_from_dissect(dissect: dict[str, Any]) -> dict[str, str]:
    """从视频拆解结果自动提取选题信息。"""
    products = dissect.get("products") or []
    product = products[0].get("name_guess", "") if products else ""
    meta = dissect.get("meta") or {}
    hook = dissect.get("hook") or {}
    topic = meta.get("one_line_summary") or hook.get("first_3s_script", "")
    style = hook.get("type") or meta.get("genre") or "痛点钩子"
    return {
        "product": product,
        "topic": topic,
        "style": style,
        "audience": "通用用户",
        "user_script": "",
    }


def dissect_to_script(dissect: dict[str, Any]) -> dict[str, Any]:
    """A 模式：拆解结果即脚本；时间轴已规范化后写出可读口播/分镜。"""
    meta = dissect.get("meta") or {}
    hook = dissect.get("hook") or {}
    skel = dict(dissect.get("script_skeleton") or {})
    beats = list(dissect.get("beats") or [])

    spoken_lines: list[str] = []
    for b in beats:
        t0 = b.get("t_start_sec", "?")
        t1 = b.get("t_end_sec", "?")
        spoken = (b.get("spoken") or b.get("spoken_or_subtitle") or "").strip()
        visual = (b.get("visual") or "").strip()
        spoken_lines.append(f"[{t0}-{t1}s] {spoken}" + (f"（画面：{visual}）" if visual else ""))

    full_spoken = "\n".join(spoken_lines).strip()
    # 模板骨架被糊成「请在…」时用时间轴重写
    old_full = str(skel.get("spoken_script_full") or "")
    if (not old_full) or ("请在" in old_full) or ("请根据" in old_full) or len(old_full) < 20:
        skel["spoken_script_full"] = full_spoken or "沿用原片口播节奏（按时间轴分段复刻）"
    if not skel.get("cta") or "请" in str(skel.get("cta")):
        skel["cta"] = "沿用原片结尾转化/行动号召"
    if not (hook.get("first_3s_script") or "").strip() or "请" in str(hook.get("first_3s_script") or ""):
        hook = dict(hook)
        hook["first_3s_script"] = (beats[0].get("spoken") or beats[0].get("spoken_or_subtitle") or "沿用原片开场钩子") if beats else "沿用原片开场钩子"
        hook.setdefault("visual_hook", (beats[0].get("visual") if beats else "") or "沿用原片前 3 秒画面")
        hook.setdefault("type", "复刻开场")

    return {
        "meta": {
            "one_line_summary": meta.get("one_line_summary") or "原片结构复刻",
            "estimated_duration_sec": meta.get("estimated_duration_sec", 30),
            "genre": meta.get("genre", "短视频复刻"),
            "platform_style": meta.get("platform_style", "竖屏"),
        },
        "hook": hook,
        "beats": beats,
        "script_skeleton": skel,
        "replication_notes": dissect.get("replication_notes") or {},
        "characters": dissect.get("characters") or [],
        "products": dissect.get("products") or [],
        "_beats_rebuilt": bool(dissect.get("_beats_rebuilt")),
    }


def generate_script(
    *,
    product: str,
    topic: str,
    audience: str,
    style: str,
    video_context: str = "",
    user_script: str = "",
) -> dict[str, Any]:
    ctx = f"\n参考视频拆解：\n{video_context}\n" if video_context.strip() else ""
    if user_script.strip():
        user = (
            f"目标人群：{audience or '通用用户'}\n"
            f"内容风格：{style or '痛点钩子种草'}\n"
            f"产品/主题：{product or topic}\n"
            f"补充：{topic}\n"
            f"{ctx}"
            f"用户手稿（口播/分镜描述，请保留核心表达并深化）：\n{user_script}\n"
            "请输出完整结构脚本 JSON（hook/beats/口播/CTA/replication_notes/characters/products）。"
        )
        return _generate_json(SCRIPT_SYSTEM, user)

    user = (
        f"目标人群：{audience or '通用用户'}\n"
        f"内容风格：{style or '痛点钩子种草'}\n"
        f"产品/主题：{product or topic}\n"
        f"补充：{topic}\n"
        f"{ctx}"
        "请输出完整结构脚本 JSON（hook/beats/口播/CTA/replication_notes/characters/products）。"
    )
    return _generate_json(SCRIPT_SYSTEM, user)


def script_from_plaintext(
    text: str,
    *,
    product: str,
    topic: str,
    audience: str,
    style: str,
) -> dict[str, Any]:
    """把手稿文本重新结构化为脚本 JSON。"""
    user = (
        f"目标人群：{audience or '通用用户'}\n"
        f"内容风格：{style or '痛点钩子'}\n"
        f"产品/主题：{product or topic}\n"
        f"用户确认后的手稿：\n{text}\n"
        "请输出完整结构脚本 JSON。"
    )
    return _generate_json(SCRIPT_SYSTEM, user)


def plan_assets(script: dict[str, Any]) -> dict[str, Any]:
    user = f"脚本：\n{json.dumps(script, ensure_ascii=False)}\n请输出资产规划 JSON。"
    return _generate_json(ASSET_SYSTEM, user, max_new_tokens=1200)


def plan_storyboard(script: dict[str, Any], mode: str, dissect: dict | None = None) -> dict[str, Any]:
    extra = ""
    if mode == "A" and dissect:
        extra = f"\n原片拆解（用于保留节奏与参考运动）：\n{json.dumps(dissect, ensure_ascii=False)[:6000]}"
    user = (
        f"模式：{'爆款复刻A' if mode == 'A' else '脚本创作B'}\n"
        f"脚本：\n{json.dumps(script, ensure_ascii=False)}\n"
        f"{extra}\n"
        "规则：口播镜优先 i2va；转场用 i2va_fl；产品 B-roll 可用 t2va；"
        "A 模式需保留原片运动的 beat 设 use_reference_video=true 且 gen_mode=r2va。"
        "每 beat duration_sec 4-15，总时长贴合 script meta。"
    )
    return _generate_json(DIRECTOR_SYSTEM, user, max_new_tokens=1600)
