"""爆款短视频生产平台 — A 复刻 / B 创作 分步向导。"""
from __future__ import annotations

import os
from pathlib import Path

import gradio as gr

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "studio"))

from ui_helpers import (
    assets_gallery_html,
    catalog_refs_gallery_html,
    draft_assets_gallery_html,
    file_path,
    format_dissect_preview,
    format_qc_preview,
    format_replica_catalog,
    format_script_preview,
    format_storyboard_preview,
    keyframe_gallery_html,
    keyframe_montage_html,
    keyframe_zip_path,
    replica_frames_html,
    replaced_keyframes_timeline_text,
    script_to_plaintext,
    slot_dropdown_update,
    slot_gallery_update,
    storyboard_gallery_html,
    video_cover_html,
    video_display_path,
    video_player_from_path,
    video_player_html,
    playable_video_path,
    video_thumbnail,
)
from src.studio_pipeline.orchestrator import StudioOrchestrator

orch = StudioOrchestrator(ROOT / "data" / "studio_projects")
UI_VERSION = "2026-09-06-v48"
VIDEO_EXTS = [".mp4", ".mov", ".webm", ".mkv"]


def _pid(project_line: str) -> str:
    text = (project_line or "").strip()
    if text.startswith("项目："):
        text = text[3:].strip()
    return text or "尚未创建"


def _toggle_mode(mode: str):
    is_a = "A" in mode
    return (
        gr.update(visible=is_a),
        gr.update(visible=not is_a),
        gr.update(value="开始解析" if is_a else "保存选题"),
        gr.update(visible=not is_a),
        gr.update(visible=is_a),
        gr.update(visible=not is_a),
        gr.update(visible=is_a),
        gr.update(visible=not is_a),
    )


def _load_env():
    p = ROOT / "scripts" / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _has_video_api() -> bool:
    from src.studio_pipeline.agnes_client import has_video_api

    return has_video_api()


def _video_provider_label() -> str:
    if os.environ.get("AGNES_API_KEY", "").strip() and (
        (os.environ.get("VIDEO_PROVIDER") or "agnes").lower() in ("agnes", "agens", "")
    ):
        return "Agnes 视频已连接"
    if os.environ.get("MINIMAX_API_KEY", "").strip():
        return "MiniMax 已连接"
    return "视频 API 未配置"


def _has_minimax() -> bool:
    return _has_video_api()


def step_parse(mode, video, product, topic, audience, style, user_script):
    video_path = file_path(video)
    mode_a = "A" in mode
    if mode_a and not video_path:
        return (
            "项目：尚未创建",
            "请先上传参考视频，再点「开始解析视频」",
            "请先完成解析",
            None,
            '<p style="color:#888">（等待解析后可播放）</p>',
            '<p style="color:#888">（等待解析）</p>',
            '<p style="color:#888">（等待解析）</p>',
            None,
            "（等待解析）",
        )

    plan = orch.start_project(
        mode="A" if mode_a else "B",
        product="" if mode_a else (product or ""),
        topic="" if mode_a else (topic or ""),
        audience="通用用户" if mode_a else (audience or "通用用户"),
        style="痛点钩子" if mode_a else (style or "痛点钩子"),
        video_path=video_path,
        user_script="" if mode_a else (user_script or ""),
    )
    pid = plan["project_id"]

    if video_path:
        plan = orch.parse_reference_video(pid)
        n = len(plan.get("keyframes", []))
        if plan.get("dissect", {}).get("error"):
            status = f"关键帧已抽取 {n} 张；AI 分析未完成（VL 模型下载中或缺失）"
        else:
            m = plan.get("meta", {})
            auto = f"已识别：{m.get('product') or '未知品类'} · {m.get('topic', '')[:40]}"
            status = f"解析完成：{n} 张关键帧。{auto}（A 模式已自动提取结构，无需手写脚本）"
        try:
            plan = orch.ensure_replica_catalog(pid, generate_images=False)
        except Exception:
            pass
        if not plan.get("dissect", {}).get("error") and plan.get("dissect", {}).get("beats"):
            try:
                plan = orch.generate_script_step(pid)
            except Exception:
                pass
    else:
        plan["steps"]["parsed"] = True
        orch.store.save_plan(plan)
        status = "选题已保存（B 模式）"

    hint = (
        "解析完成 ↓ 到 ② 替换资产：先查看抠出的原片资产描述，再写提示词生成并确认"
        if mode_a
        else "选题已保存 → 请切换到 ② 写脚本"
    )
    return (
        f"项目：{pid}",
        status,
        hint,
        playable_video_path(video_display_path(plan)),
        video_player_html(plan, label="参考视频（网页内播放）"),
        keyframe_montage_html(plan),
        keyframe_gallery_html(plan),
        keyframe_zip_path(plan),
        format_dissect_preview(plan.get("dissect")),
    )


def step_next_hint(mode, project_line):
    pid = _pid(project_line)
    if pid == "尚未创建":
        return "请先在 ① 完成解析或保存选题"
    if "A" in mode:
        return "请到 ② 替换资产 上传人物/商品"
    return "请到 ② 写脚本 生成口播稿"


def _collect_uploads(char_front, char_34, product_img) -> dict[str, str]:
    uploads: dict[str, str] = {}
    if p := file_path(char_front):
        uploads["character_front"] = p
    if p := file_path(char_34):
        uploads["character_three_quarter"] = p
    if p := file_path(product_img):
        uploads["product"] = p
    return uploads


def _plan_script_text(plan: dict | None) -> str:
    if not plan:
        return "（请先完成 ① 解析）"
    if plan.get("script"):
        return script_to_plaintext(plan["script"])
    if plan.get("replaced_keyframes"):
        return replaced_keyframes_timeline_text(plan["replaced_keyframes"])
    return "（点「一键生成复刻脚本」从视频拆解生成时间轴+口播）"


def _replica_outputs(
    status: str,
    catalog_text: str,
    catalog_gallery: str,
    draft_gallery: str,
    approved_gallery: str,
    frames_gallery: str,
    frames_status: str,
    hint: str,
    slot_update=None,
    script_text: str = "",
    slot_gallery=None,
    selected_image: str = "",
    prompt_ready: bool = False,
    prompt_reviewed: bool = False,
    prompt_box=None,
):
    if slot_update is None:
        slot_update = gr.update()
    if slot_gallery is None:
        slot_gallery = gr.update()
    if prompt_box is None:
        prompt_box = gr.update()
    return (
        status,
        catalog_text,
        catalog_gallery,
        draft_gallery,
        approved_gallery,
        frames_gallery,
        frames_status,
        hint,
        slot_update,
        script_text,
        slot_gallery,
        selected_image,
        prompt_ready,
        gr.update(value=prompt_reviewed),
        prompt_box,
    )


def step_extract_catalog(project_line, *, ai_whiten: bool = False):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return _replica_outputs(
            "请先完成 ① 解析",
            "（等待解析）",
            '<p style="color:#888">（等待）</p>',
            '<p style="color:#888">（等待）</p>',
            '<p style="color:#888">（等待）</p>',
            '<p style="color:#888">（等待）</p>',
            "（等待）",
            "请先解析视频",
            gr.update(),
            "（等待解析）",
        )
    try:
        plan = orch.ensure_replica_catalog(project_id, generate_images=True)
    except Exception as e:
        return _replica_outputs(
            f"失败：{e}",
            "（提取失败）",
            '<p style="color:#c66">（失败）</p>',
            '<p style="color:#888">（等待）</p>',
            '<p style="color:#888">（等待）</p>',
            '<p style="color:#888">（等待）</p>',
            "（等待）",
            "请确认已完成解析",
            gr.update(),
            "（提取失败）",
        )
    cat = plan.get("replica_catalog")
    note = (cat or {}).get("gen_note", "")
    slot_id = ((cat or {}).get("slots") or [{}])[0].get("id") if (cat or {}).get("slots") else None
    return _replica_outputs(
        f"AI资产提取完成。{note}",
        format_replica_catalog(cat),
        catalog_refs_gallery_html(cat, selected_slot_id=slot_id),
        draft_assets_gallery_html(plan.get("replacement_drafts")),
        assets_gallery_html(plan.get("assets") or {}),
        replica_frames_html(plan),
        "（尚未生成替换关键帧）"
        if not plan.get("replaced_keyframes")
        else f"已按剧情段替换 {len(plan['replaced_keyframes'])} 张关键帧（每段 5–10 秒）",
        "① 点选角色/产品框（或框内单张）→ ② AI优化提示词并审阅 → ③ 确认生成",
        slot_dropdown_update(cat, slot_id),
        _plan_script_text(plan),
        slot_gallery_update(cat, slot_id),
        "",
        False,
        False,
    )


def step_select_slot(project_line, target_slot):
    """点选整框：高亮槽位，清空单图选择与提示词门禁。"""
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return (
            catalog_refs_gallery_html(None),
            gr.update(value=None),
            "",
            False,
            gr.update(value=False),
            "请先解析并提取资产",
        )
    plan = orch.store.load_plan(project_id)
    cat = plan.get("replica_catalog") or {}
    label = target_slot or "未选"
    for s in cat.get("slots") or []:
        if s.get("id") == target_slot:
            label = s.get("label") or target_slot
            break
    return (
        catalog_refs_gallery_html(cat, selected_slot_id=target_slot),
        slot_gallery_update(cat, target_slot),
        "",
        False,
        gr.update(value=False),
        f"已选整框「{label}」。可再点框内单张，或直接「AI优化提示词」",
    )


def _as_path_str(val) -> str:
    """Gradio Gallery 选中值可能是 str / dict / list，统一抽成存在的文件路径。"""
    if val is None:
        return ""
    if isinstance(val, (list, tuple)):
        for item in val:
            p = _as_path_str(item)
            if p:
                return p
        return ""
    if isinstance(val, dict):
        for key in ("path", "image", "name", "url"):
            if key in val:
                p = _as_path_str(val.get(key))
                if p:
                    return p
        return ""
    if not isinstance(val, (str, Path)):
        return ""
    s = str(val).strip()
    if not s or s.startswith("data:"):
        return ""
    try:
        p = Path(s)
        return str(p.resolve()) if p.exists() else ""
    except (OSError, TypeError, ValueError):
        return ""


def step_select_slot_image(project_line, target_slot, evt: gr.SelectData):
    """点选框内单张图。"""
    project_id = _pid(project_line)
    plan = orch.store.load_plan(project_id) if project_id != "尚未创建" else {}
    cat = (plan or {}).get("replica_catalog") or {}
    path = ""
    try:
        if evt is not None:
            path = _as_path_str(getattr(evt, "value", None))
            if not path and getattr(evt, "index", None) is not None:
                slot = next((s for s in cat.get("slots", []) if s.get("id") == target_slot), None)
                imgs = [i for i in (slot or {}).get("images") or [] if i.get("path") and Path(i["path"]).exists()]
                if 0 <= int(evt.index) < len(imgs):
                    path = str(Path(imgs[int(evt.index)]["path"]).resolve())
    except Exception as e:
        return (
            catalog_refs_gallery_html(cat, selected_slot_id=target_slot),
            "",
            False,
            gr.update(value=False),
            f"选图失败：{e}",
        )
    return (
        catalog_refs_gallery_html(cat, selected_slot_id=target_slot, selected_image_path=path or None),
        path,
        False,
        gr.update(value=False),
        f"已选单张：{Path(path).name}" if path else "未选中有效图片，仍按整框替换",
    )


def step_ai_prompt(project_line, target_slot, replace_prompt):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return "请先解析并提取资产", gr.update(), False, gr.update(value=False)
    if not target_slot:
        return "请先点选要替换的角色/产品框", gr.update(), False, gr.update(value=False)
    try:
        text = orch.suggest_replacement_prompt(project_id, target_slot, user_hint=replace_prompt or "")
    except Exception as e:
        return f"AI提示词失败：{e}", gr.update(), False, gr.update(value=False)
    return (
        f"AI已优化「{target_slot}」提示词。请审阅下方内容，勾选确认后再生成资产",
        gr.update(value=text),
        True,
        gr.update(value=False),
    )


def step_draft_assets(
    project_line,
    target_slot,
    replace_prompt,
    upload_img,
    prompt_ready,
    prompt_reviewed,
    selected_image,
):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return step_extract_catalog(project_line)
    up = file_path(upload_img)
    if not up and not (prompt_ready and prompt_reviewed):
        plan = orch.store.load_plan(project_id)
        cat = plan.get("replica_catalog")
        return _replica_outputs(
            "请先「AI优化提示词」，审阅后勾选「我已确认提示词」，再生成（或直接上传替换图）",
            format_replica_catalog(cat),
            catalog_refs_gallery_html(cat, selected_slot_id=target_slot, selected_image_path=selected_image or None),
            draft_assets_gallery_html(plan.get("replacement_drafts")),
            assets_gallery_html(plan.get("assets") or {}),
            replica_frames_html(plan),
            "（等待）",
            "门禁：AI提示词 → 人工确认 → 生成",
            slot_dropdown_update(cat, target_slot),
            _plan_script_text(plan),
            slot_gallery_update(cat, target_slot),
            selected_image or "",
            bool(prompt_ready),
            bool(prompt_reviewed),
            gr.update(),
        )
    if not target_slot:
        plan = orch.store.load_plan(project_id)
        cat = plan.get("replica_catalog")
        return _replica_outputs(
            "请先点选要替换的角色/产品框",
            format_replica_catalog(cat),
            catalog_refs_gallery_html(cat),
            draft_assets_gallery_html(plan.get("replacement_drafts")),
            assets_gallery_html(plan.get("assets") or {}),
            replica_frames_html(plan),
            "（等待）",
            "先选槽位",
            slot_dropdown_update(cat),
            _plan_script_text(plan),
            slot_gallery_update(cat),
            "",
            False,
            False,
        )
    uploads = {}
    if up:
        uploads["image"] = up
    elif selected_image and Path(selected_image).exists():
        # 选中的原片图仅作上下文，不作为换人参考（避免锁原脸）；仅上传图才进 uploads
        pass
    try:
        if not orch.store.load_plan(project_id).get("replica_catalog"):
            orch.ensure_replica_catalog(project_id)
        plan = orch.draft_replacement_assets(project_id, target_slot or "", replace_prompt or "", uploads)
    except Exception as e:
        plan = orch.store.load_plan(project_id)
        cat = plan.get("replica_catalog")
        return _replica_outputs(
            f"失败：{e}",
            format_replica_catalog(cat),
            catalog_refs_gallery_html(cat, selected_slot_id=target_slot, selected_image_path=selected_image or None),
            '<p style="color:#c66">（生成失败）</p>',
            assets_gallery_html(plan.get("assets") or {}),
            replica_frames_html(plan),
            "（等待）",
            "请确认提示词与 Agnes 密钥",
            slot_dropdown_update(cat, target_slot),
            _plan_script_text(plan),
            slot_gallery_update(cat, target_slot),
            selected_image or "",
            bool(prompt_ready),
            bool(prompt_reviewed),
        )
    drafts = plan.get("replacement_drafts") or {}
    cat = plan.get("replica_catalog")
    slot_label = target_slot or drafts.get("target_slot_id", "")
    entry = (drafts.get("slots") or {}).get(slot_label) or next(iter((drafts.get("slots") or {}).values()), {})
    src = entry.get("source", "?")
    return _replica_outputs(
        f"已用 AI（{src}）为「{slot_label}」生成替换图｜提示词：{(replace_prompt or '')[:48]}",
        format_replica_catalog(cat),
        catalog_refs_gallery_html(cat, selected_slot_id=target_slot, selected_image_path=selected_image or None),
        draft_assets_gallery_html(drafts),
        assets_gallery_html(plan.get("assets") or {}),
        replica_frames_html(plan),
        f"替换预览 · {src}",
        "确认新人设后点「③ 生成替换关键帧」；换别人请改选框并重新走提示词门禁",
        slot_dropdown_update(cat, target_slot),
        _plan_script_text(plan),
        slot_gallery_update(cat, target_slot),
        selected_image or "",
        True,
        True,
    )


def step_approve_assets(project_line, char_prompt, product_prompt, char_front, char_34, product_img):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return step_extract_catalog(project_line)
    plan = orch.store.load_plan(project_id)
    if not (plan.get("replacement_drafts") or {}).get("images"):
        return step_draft_assets(project_line, char_prompt, product_prompt, char_front, False, False, "")
    try:
        plan = orch.approve_replacement_assets(project_id)
    except Exception as e:
        cat = plan.get("replica_catalog")
        return _replica_outputs(
            f"失败：{e}",
            format_replica_catalog(cat),
            catalog_refs_gallery_html(cat),
            draft_assets_gallery_html(plan.get("replacement_drafts")),
            assets_gallery_html(plan.get("assets") or {}),
            storyboard_gallery_html(plan.get("storyboard") or []),
            "（等待）",
            "请先生成预览",
            slot_dropdown_update(cat),
            _plan_script_text(plan),
            slot_gallery_update(cat),
        )
    cat = plan.get("replica_catalog")
    return _replica_outputs(
        "替换资产已确认保留（之后可随时改提示词重新生成）",
        format_replica_catalog(cat),
        catalog_refs_gallery_html(cat),
        draft_assets_gallery_html(plan.get("replacement_drafts")),
        assets_gallery_html(plan.get("assets") or {}),
        storyboard_gallery_html(plan.get("storyboard") or []),
        "（可点 ④ 生成替换关键帧）",
        "已确认 → 点「④ 生成替换关键帧」，然后到成片一键出片",
        slot_dropdown_update(cat),
        _plan_script_text(plan),
        slot_gallery_update(cat),
        "",
        True,
        True,
    )


def step_ai_whiten_catalog(project_line):
    return step_extract_catalog(project_line, ai_whiten=True)


def step_build_keyframes(project_line, target_slot, replace_prompt, upload_img, prompt_ready=False, prompt_reviewed=False, selected_image=""):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return step_extract_catalog(project_line)
    plan = orch.store.load_plan(project_id)
    cat = plan.get("replica_catalog")
    drafts = plan.get("replacement_drafts") or {}
    if not (drafts.get("images") or drafts.get("slots")):
        return _replica_outputs(
            "请先生成替换资产（选框 → AI提示词审阅 → 确认生成）",
            format_replica_catalog(cat),
            catalog_refs_gallery_html(cat, selected_slot_id=target_slot, selected_image_path=selected_image or None),
            draft_assets_gallery_html(drafts),
            assets_gallery_html(plan.get("assets") or {}),
            replica_frames_html(plan),
            "（等待）",
            "先生成替换资产再生成关键帧",
            slot_dropdown_update(cat, target_slot),
            _plan_script_text(plan),
            slot_gallery_update(cat, target_slot),
            selected_image or "",
            bool(prompt_ready),
            bool(prompt_reviewed),
        )
    try:
        plan = orch.build_replica_keyframes(project_id)
    except Exception as e:
        plan = orch.store.load_plan(project_id)
        cat = plan.get("replica_catalog")
        return _replica_outputs(
            f"失败：{e}",
            format_replica_catalog(cat),
            catalog_refs_gallery_html(cat, selected_slot_id=target_slot, selected_image_path=selected_image or None),
            draft_assets_gallery_html(plan.get("replacement_drafts")),
            assets_gallery_html(plan.get("assets") or {}),
            replica_frames_html(plan),
            f"失败：{e}",
            "请检查是否已生成替换资产",
            slot_dropdown_update(cat, target_slot),
            _plan_script_text(plan),
            slot_gallery_update(cat, target_slot),
            selected_image or "",
            bool(prompt_ready),
            bool(prompt_reviewed),
        )
    cat = plan.get("replica_catalog")
    try:
        frames_html = replica_frames_html(plan)
    except Exception as e:
        frames_html = f'<p style="color:#c66">预览渲染失败：{e}</p>'
    replaced = plan.get("replaced_keyframes") or []
    n_ai = sum(1 for x in replaced if x.get("gen_source") in ("minimax", "agnes", "ai"))
    n_keep = sum(1 for x in replaced if x.get("gen_source") == "unchanged")
    slots_done = list(((plan.get("assets") or {}).get("slot_replacements") or {}).keys())
    script_block = _plan_script_text(plan)
    timeline = replaced_keyframes_timeline_text(replaced)
    if timeline and "生成替换关键帧后" not in timeline:
        script_block = f"{script_block}\n\n{timeline}"
    return _replica_outputs(
        f"剧情段关键帧全部完成：共 {len(replaced)} 段（5–10s）· AI {n_ai} · 回退原片 {n_keep}"
        f"（已选槽：{', '.join(slots_done) or '无'}）",
        format_replica_catalog(cat),
        catalog_refs_gallery_html(cat, selected_slot_id=target_slot, selected_image_path=selected_image or None),
        draft_assets_gallery_html(plan.get("replacement_drafts")),
        assets_gallery_html(plan.get("assets") or {}),
        frames_html,
        f"共 {len(replaced)} 个剧情段关键帧（覆盖全片）",
        "每段一张替换关键帧；匹配已选资产的镜头会换人/换品，其余复刻原构图。可去成片生成视频",
        slot_dropdown_update(cat, target_slot),
        script_block,
        slot_gallery_update(cat, target_slot),
        selected_image or "",
        bool(prompt_ready),
        bool(prompt_reviewed),
    )


def step_gen_replica_script(project_line):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return "请先完成 ① 解析", "（等待解析）"
    try:
        plan = orch.generate_script_step(project_id)
    except Exception as e:
        return f"失败：{e}", "（生成失败）"
    n = len((plan.get("script") or {}).get("beats") or [])
    text = _plan_script_text(plan)
    timeline = replaced_keyframes_timeline_text(plan.get("replaced_keyframes"))
    if timeline and "生成替换关键帧后" not in timeline:
        text = f"{text}\n\n{timeline}"
    return f"复刻脚本已生成（{n} 个节拍，含时间轴+口播）", text


def step_next_to_replica(project_line, *_):
    """① 页「下一步」= 提取原片资产目录。"""
    return step_extract_catalog(project_line)


def step_generate_script(project_line):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return "请先在 ① 完成解析或保存选题", "", "（等待生成）", "等待中"
    plan = orch.generate_script_step(project_id)
    plain = script_to_plaintext(plan["script"])
    return (
        "脚本已根据选题生成",
        plain,
        format_script_preview(plan["script"]),
        "确认脚本后，请到 ③ 资产 上传素材并生成",
    )


def step_confirm_script(project_line, script_text):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return "请先生成脚本", script_text, "（等待）", "等待中"
    try:
        plan = orch.update_script_from_text(project_id, script_text)
        plain = script_to_plaintext(plan["script"])
        return "脚本已确认", plain, format_script_preview(plan["script"]), "请到 ③ 资产 点「生成资产」"
    except Exception as e:
        return f"失败：{e}", script_text, "（失败）", "请修改后重试"



def step_assets(project_line, char_front, char_34, product_img):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return "请先完成脚本", '<p style="color:#888">（等待生成）</p>', "等待中"
    uploads = {}
    if p := file_path(char_front):
        uploads["character_front"] = p
    if p := file_path(char_34):
        uploads["character_three_quarter"] = p
    if p := file_path(product_img):
        uploads["product"] = p
    plan = orch.build_assets(project_id, uploads)
    n = len(plan["assets"].get("images", []))
    return f"已生成 {n} 张资产图", assets_gallery_html(plan["assets"]), "请到 ④ 分镜 生成分镜"


def step_storyboard(project_line):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return "请先完成资产", '<p style="color:#888">（等待生成）</p>', "", "等待中"
    plan = orch.build_storyboard(project_id)
    sb = plan["storyboard"]
    return (
        f"已生成 {len(sb)} 个分镜",
        storyboard_gallery_html(sb),
        format_storyboard_preview(sb),
        "请到 ⑤ 成片 生成视频",
    )


def step_video(project_line, dry_run):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return "请先完成分镜/替换关键帧", None, '<p style="color:#888">（等待生成）</p>', "", "", "等待中"
    try:
        plan = orch.store.load_plan(project_id)
        if plan.get("mode") == "A":
            if not plan.get("steps", {}).get("storyboard"):
                try:
                    if not plan.get("steps", {}).get("assets_approved"):
                        if not (plan.get("replacement_drafts") or {}).get("images"):
                            return (
                                "A 模式：请先在 ② 完成资产替换（提取→预览→确认→关键帧）",
                                None,
                                '<p style="color:#888">（未生成）</p>',
                                "",
                                "",
                                "请到 ② 替换资产",
                            )
                        orch.approve_replacement_assets(project_id)
                    orch.build_replica_keyframes(project_id)
                except Exception as e:
                    return f"失败：{e}", None, '<p style="color:#888">（未生成）</p>', "", "", "请完成 ② 替换资产流程"
        if not dry_run and not _has_video_api():
            return "未配置 AGNES_API_KEY（成片默认用 Agnes）", None, '<p style="color:#888">（未生成）</p>', "", "", "请配置密钥或勾选试跑"
        plan = orch.generate_videos(project_id, dry_run=dry_run)
        master = (plan.get("output") or {}).get("master_path")
        video_out = playable_video_path(master) if master else None
        note = (plan.get("output") or {}).get("note", "完成")
        player = video_player_from_path(video_out, label="成片（网页内播放）")
        return note, video_out, player, "", format_qc_preview((plan.get("output") or {}).get("qc", {})), "完成"
    except Exception as e:
        return f"成片失败：{e}", None, '<p style="color:#c66">（失败）</p>', "", "", "请查看状态栏错误"


def step_rerun(project_line, beat_idx):
    project_id = _pid(project_line)
    if project_id == "尚未创建":
        return "请先完成分镜", None, '<p style="color:#888">（未生成）</p>', "", ""
    try:
        plan = orch.rerun_beat(project_id, int(beat_idx))
        master = (plan.get("output") or {}).get("master_path")
        video_out = playable_video_path(master) if master else None
        return (
            f"Beat {int(beat_idx)} 已重生成",
            video_out,
            video_player_from_path(video_out, label="成片（网页内播放）"),
            "",
            format_qc_preview((plan.get("output") or {}).get("qc", {})),
        )
    except Exception as e:
        return f"失败：{e}", None, '<p style="color:#888">（失败）</p>', "", ""


def ping_minimax():
    try:
        from src.studio_pipeline.agnes_client import get_video_client

        info = get_video_client().ping()
        return (
            f"Agnes 已连接 {info.get('base_url')} "
            f"model={info.get('model', '')} id={info.get('video_id') or info.get('task_id')}"
        )
    except Exception as e:
        return f"Agnes 检测失败：{e}"


def build_ui():
    api = _video_provider_label()
    with gr.Blocks(title="爆款短视频") as demo:
        gr.Textbox(
            value=(
                f"爆款短视频生产平台 | {UI_VERSION} | {api}\n"
                "A 复刻：①上传解析 → ②替换资产 → ③预览 → 成片\n"
                "B 创作：①选题 → ②脚本 → ③资产 → ④分镜 → 成片"
            ),
            show_label=False,
            interactive=False,
            lines=3,
            max_lines=3,
        )

        project_line = gr.Textbox(value="项目：尚未创建", label="当前项目", interactive=False, lines=1)
        next_hint = gr.Textbox(value="从 ① 上传解析 开始", label="下一步提示", interactive=False, lines=2)

        with gr.Tabs():
            with gr.Tab("① 上传解析"):
                gr.Textbox(
                    value="上传视频并解析，结果直接显示在本页下方。",
                    show_label=False,
                    interactive=False,
                    lines=1,
                )
                mode = gr.Radio(
                    ["A 爆款复刻（换人物/商品）", "B 脚本创作（手填选题）"],
                    value="A 爆款复刻（换人物/商品）",
                    label="模式",
                )
                with gr.Group(visible=True) as panel_a:
                    ref_video = gr.File(label="参考爆款视频（必填）", file_types=VIDEO_EXTS, file_count="single")
                with gr.Group(visible=False) as panel_b:
                    with gr.Row():
                        product = gr.Textbox(label="产品/品类", placeholder="洗衣机、防晒喷雾…")
                        topic = gr.Textbox(label="卖点/主题", placeholder="推荐洗衣机…")
                    with gr.Row():
                        audience = gr.Dropdown(
                            ["学生党", "打工人", "宝妈", "护肤小白", "数码爱好者", "通用用户"],
                            value="通用用户",
                            label="人群",
                        )
                        style = gr.Dropdown(
                            ["痛点钩子", "反差对比", "结果先行", "避雷测评", "清单种草", "剧情植入"],
                            value="痛点钩子",
                            label="风格",
                        )
                    user_script = gr.Textbox(label="你的手稿（可选）", lines=4)
                btn_parse = gr.Button("开始解析", variant="primary", size="lg")
                parse_status = gr.Textbox(label="状态", value="", interactive=False, lines=2)

                gr.Textbox(
                    value="── 解析结果（解析后自动显示）──",
                    show_label=False,
                    interactive=False,
                    lines=1,
                )
                ref_video_file = gr.File(label="参考视频下载（点此下载）", interactive=False)
                ref_video_player = gr.HTML(label="参考视频预览")
                gr.Textbox(value="原片关键帧拼图", show_label=False, interactive=False, lines=1, max_lines=1)
                keyframe_montage = gr.HTML(show_label=False)
                gr.Textbox(value="原片单帧（点击展开）", show_label=False, interactive=False, lines=1, max_lines=1)
                keyframe_gallery = gr.HTML(show_label=False)
                keyframe_zip = gr.File(label="下载全部关键帧 ZIP", interactive=False)
                dissect_preview = gr.Textbox(
                    label="内容拆解",
                    value="（解析后显示）",
                    interactive=False,
                    lines=12,
                )
                btn_to_replica = gr.Button("② 生成原片资产并进入替换", variant="secondary", size="lg")

            with gr.Tab("② 写脚本", visible=False) as tab_script:
                gr.Textbox(
                    value="B 模式：根据选题生成口播稿，确认后到 ③ 资产。",
                    show_label=False,
                    interactive=False,
                    lines=1,
                )
                script_status = gr.Textbox(label="状态", value="", interactive=False, lines=2)
                btn_gen_script = gr.Button("生成口播稿", variant="primary")
                script_preview = gr.Textbox(
                    label="脚本结构预览",
                    value="（生成后显示）",
                    interactive=False,
                    lines=8,
                )
                script_editor = gr.Textbox(label="口播稿（可直接修改）", lines=12)
                btn_confirm = gr.Button("确认脚本", variant="secondary")

            with gr.Tab("② 替换资产") as tab_replica:
                gr.Textbox(
                    value="① 点选角色/产品整框（或框内单张）→ ② AI优化提示词 → ③ 人工审阅勾选 → ④ 确认生成新资产 → ⑤ 生成关键帧",
                    show_label=False,
                    interactive=False,
                    lines=2,
                )
                with gr.Row():
                    btn_extract = gr.Button("① AI提取原片资产（Agnes分人+白底）", variant="primary")
                    btn_ai_whiten = gr.Button("重新AI提取", variant="secondary")
                catalog_desc = gr.Textbox(
                    label="原片资产描述（按人物/产品分槽）",
                    value="（解析后自动提取）",
                    interactive=False,
                    lines=6,
                )
                catalog_refs = gr.HTML(show_label=False)
                replace_target_slot = gr.Radio(
                    label="选择角色/产品框（点选 = 替换该框全部图）",
                    choices=[],
                    value=None,
                )
                slot_pick_gallery = gr.Gallery(
                    label="框内图片（点选单张，可选）",
                    columns=4,
                    height=200,
                    object_fit="contain",
                    interactive=True,
                )
                selected_image_path = gr.State("")
                prompt_ai_ready = gr.State(False)
                replace_prompt = gr.Textbox(
                    label="替换提示词（AI优化后请人工审阅，可再改）",
                    placeholder="可先写草稿，再点「AI优化提示词」；或直接让 AI 生成",
                    lines=3,
                )
                with gr.Row():
                    btn_ai_prompt = gr.Button("② AI优化提示词", variant="secondary")
                    prompt_reviewed = gr.Checkbox(
                        label="我已审阅并确认上方提示词",
                        value=False,
                    )
                replace_upload = gr.File(
                    label="替换图（可选上传，有上传图可跳过提示词门禁）",
                    file_types=["image"],
                    file_count="single",
                )
                with gr.Row():
                    btn_draft = gr.Button("③ 确认生成我的替换资产", variant="primary", size="lg")
                    btn_build_frames = gr.Button("④ 按剧情段生成全部替换关键帧", variant="primary", size="lg")
                    btn_gen_script_inline = gr.Button("一键生成复刻脚本", variant="secondary")
                replica_status = gr.Textbox(label="状态", value="", interactive=False, lines=2)
                draft_gallery = gr.HTML(show_label=False)
                approved_assets = gr.HTML(visible=False)

            with gr.Tab("③ 资产", visible=False) as tab_assets:
                with gr.Row():
                    char_front = gr.File(label="正脸图（可选）", file_types=["image"], file_count="single")
                    char_34 = gr.File(label="侧脸图（可选）", file_types=["image"], file_count="single")
                    product_img = gr.File(label="产品图（可选）", file_types=["image"], file_count="single")
                btn_assets = gr.Button("生成资产", variant="primary", size="lg")
                asset_status = gr.Textbox(label="状态", value="", interactive=False, lines=2)
                asset_gallery = gr.HTML(show_label=False)

            with gr.Tab("③ 关键帧预览") as tab_frames:
                with gr.Row():
                    btn_gen_replica_script = gr.Button("一键生成复刻脚本", variant="secondary")
                replica_script = gr.Textbox(
                    label="复刻脚本（时间轴 + 口播，与每张关键帧对应）",
                    value="（解析后自动生成，或点上方按钮重新生成）",
                    interactive=True,
                    lines=10,
                )
                frames_status = gr.Textbox(
                    label="状态",
                    value="（在 ② 替换资产 生成后显示）",
                    interactive=False,
                    lines=2,
                )
                gr.Textbox(
                    value="每张关键帧 = ① 解析抽出的原片帧 + 替换效果；左侧原帧、右侧替换后",
                    show_label=False,
                    interactive=False,
                    lines=1,
                )
                replica_frames = gr.HTML(show_label=False)

            with gr.Tab("④ 分镜", visible=False) as tab_story:
                btn_story = gr.Button("生成分镜关键帧", variant="primary", size="lg")
                story_status = gr.Textbox(label="状态", value="", interactive=False, lines=2)
                story_gallery = gr.HTML(show_label=False)
                story_md = gr.Textbox(label="分镜详情", value="", interactive=False, lines=10)

            with gr.Tab("成片"):
                dry_run = gr.Checkbox(label="试跑模式（跳过 Agnes，仅切原片）")
                with gr.Row():
                    btn_ping = gr.Button("检测 Agnes 视频")
                    btn_video = gr.Button("一键生成成片（Agnes）", variant="primary", size="lg")
                video_status = gr.Textbox(label="状态", value="", interactive=False, lines=2)
                out_video_player = gr.HTML(label="成片预览（网页内播放）")
                out_thumb = gr.HTML(visible=False)
                out_file = gr.File(label="下载成片 MP4", interactive=False)
                qc_md = gr.Textbox(label="质检报告", value="", interactive=False, lines=8)
                beat_idx = gr.Number(label="重生成第几段", value=1, precision=0)
                btn_rerun = gr.Button("重生成该段（Agnes）")

        parse_inputs = [mode, ref_video, product, topic, audience, style, user_script]

        mode.change(
            _toggle_mode,
            mode,
            [
                panel_a,
                panel_b,
                btn_parse,
                tab_script,
                tab_replica,
                tab_assets,
                tab_frames,
                tab_story,
            ],
        )

        btn_parse.click(
            step_parse,
            parse_inputs,
            [
                project_line,
                parse_status,
                next_hint,
                ref_video_file,
                ref_video_player,
                keyframe_montage,
                keyframe_gallery,
                keyframe_zip,
                dissect_preview,
            ],
        )
        replica_inputs = [
            project_line,
            replace_target_slot,
            replace_prompt,
            replace_upload,
            prompt_ai_ready,
            prompt_reviewed,
            selected_image_path,
        ]
        replica_outputs = [
            replica_status,
            catalog_desc,
            catalog_refs,
            draft_gallery,
            approved_assets,
            replica_frames,
            frames_status,
            next_hint,
            replace_target_slot,
            replica_script,
            slot_pick_gallery,
            selected_image_path,
            prompt_ai_ready,
            prompt_reviewed,
            replace_prompt,
        ]

        btn_to_replica.click(step_next_to_replica, replica_inputs, replica_outputs)
        btn_extract.click(lambda p: step_extract_catalog(p, ai_whiten=True), [project_line], replica_outputs)
        btn_ai_whiten.click(step_ai_whiten_catalog, [project_line], replica_outputs)
        replace_target_slot.change(
            step_select_slot,
            [project_line, replace_target_slot],
            [catalog_refs, slot_pick_gallery, selected_image_path, prompt_ai_ready, prompt_reviewed, replica_status],
        )
        slot_pick_gallery.select(
            step_select_slot_image,
            [project_line, replace_target_slot],
            [catalog_refs, selected_image_path, prompt_ai_ready, prompt_reviewed, replica_status],
        )
        btn_ai_prompt.click(
            step_ai_prompt,
            [project_line, replace_target_slot, replace_prompt],
            [replica_status, replace_prompt, prompt_ai_ready, prompt_reviewed],
        )
        btn_draft.click(step_draft_assets, replica_inputs, replica_outputs)
        btn_build_frames.click(step_build_keyframes, replica_inputs, replica_outputs)
        btn_gen_replica_script.click(
            step_gen_replica_script,
            [project_line],
            [frames_status, replica_script],
        )
        btn_gen_script_inline.click(
            step_gen_replica_script,
            [project_line],
            [frames_status, replica_script],
        )
        btn_gen_script.click(step_generate_script, [project_line], [script_status, script_editor, script_preview, next_hint])
        btn_confirm.click(
            step_confirm_script,
            [project_line, script_editor],
            [script_status, script_editor, script_preview, next_hint],
        )
        btn_assets.click(step_assets, [project_line, char_front, char_34, product_img], [asset_status, asset_gallery, next_hint])
        btn_story.click(step_storyboard, [project_line], [story_status, story_gallery, story_md, next_hint])
        btn_video.click(step_video, [project_line, dry_run], [video_status, out_file, out_video_player, out_thumb, qc_md, next_hint])
        btn_rerun.click(step_rerun, [project_line, beat_idx], [video_status, out_file, out_video_player, out_thumb, qc_md])
        btn_ping.click(ping_minimax, outputs=[video_status])

    return demo


demo = build_ui()

if __name__ == "__main__":
    os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
    os.environ.setdefault("GRADIO_HEARTBEAT_INTERVAL", "45")
    data_root = (ROOT / "data").resolve()
    kw = {
        "server_name": "0.0.0.0",
        "server_port": int(os.environ.get("PORT", 7860)),
        "allowed_paths": [str(data_root), str(ROOT.resolve())],
        "show_error": True,
        "max_threads": 40,
    }
    if int(gr.__version__.split(".", 1)[0]) >= 6:
        kw["theme"] = gr.themes.Soft()
    demo.queue(max_size=12, default_concurrency_limit=1, status_update_rate=2).launch(**kw)
