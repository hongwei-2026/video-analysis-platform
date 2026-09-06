from __future__ import annotations

import base64
import html
import io
import json
import re
from pathlib import Path
from typing import Any

import gradio as gr
from PIL import Image


def md_to_html(text: str | None) -> str:
    """轻量 Markdown → HTML，避免 Gradio Markdown 组件在代理环境下崩溃。"""
    if not text:
        return "<p></p>"
    lines = text.splitlines()
    out: list[str] = []
    in_table = False
    for line in lines:
        s = line.strip()
        if not s:
            if in_table:
                out.append("</table>")
                in_table = False
            out.append("<br>")
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [html.escape(c.strip()) for c in s.strip("|").split("|")]
            if all(set(c) <= {"-", ":"} for c in cells):
                continue
            if not in_table:
                out.append('<table style="border-collapse:collapse;width:100%">')
                in_table = True
                tag = "th"
            else:
                tag = "td"
            row = "".join(
                f'<{tag} style="border:1px solid #444;padding:4px 8px">{c}</{tag}>' for c in cells
            )
            out.append(f"<tr>{row}</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if s.startswith("### "):
            out.append(f"<h3>{html.escape(s[4:])}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{html.escape(s[3:])}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{html.escape(s[2:])}</h1>")
        elif s.startswith("- "):
            body = html.escape(s[2:])
            body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
            out.append(f"<li>{body}</li>")
        else:
            body = html.escape(s)
            body = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body)
            body = re.sub(r"`(.+?)`", r"<code>\1</code>", body)
            out.append(f"<p>{body}</p>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def _safe(obj: Any, default: str = "") -> str:
    if obj is None:
        return default
    return str(obj).strip() or default


def format_script_preview(script: dict | str) -> str:
    if isinstance(script, str):
        try:
            script = json.loads(script)
        except Exception:
            return "脚本 JSON 格式无效，请检查后再确认。"

    meta = script.get("meta", {})
    hook = script.get("hook", {})
    beats = script.get("beats", [])
    skel = script.get("script_skeleton", {})

    lines = [
        f"# {_safe(meta.get('one_line_summary'), '短视频脚本')}",
        "",
        f"| 预估时长 | 风格 | 平台 |",
        f"| --- | --- | --- |",
        f"| {_safe(meta.get('estimated_duration_sec'), '?')}s | {_safe(meta.get('genre'))} | {_safe(meta.get('platform_style'))} |",
        "",
        "## 开场钩子",
        f"- **类型**：{_safe(hook.get('type'))}",
        f"- **口播**：{_safe(hook.get('first_3s_script'))}",
        f"- **画面**：{_safe(hook.get('visual_hook'))}",
        "",
        "## 分镜节拍",
    ]

    for b in beats:
        idx = b.get("idx", "?")
        role = _safe(b.get("role"))
        t0 = b.get("t_start_sec", "")
        t1 = b.get("t_end_sec", "")
        lines += [
            f"### Beat {idx} · {role} `{t0}-{t1}s`",
            f"- **画面**：{_safe(b.get('visual'))}",
            f"- **口播**：{_safe(b.get('spoken_or_subtitle') or b.get('spoken'))}",
            f"- **镜头**：{_safe(b.get('camera'))}",
            "",
        ]

    lines += [
        "## 完整口播",
        _safe(skel.get("spoken_script_full"), "（待生成）"),
        "",
        f"**CTA**：{_safe(skel.get('cta'))}",
    ]
    return "\n".join(lines)


def format_storyboard_preview(storyboard: list | str) -> str:
    if isinstance(storyboard, str):
        try:
            storyboard = json.loads(storyboard)
        except Exception:
            return "分镜数据无效"

    if not storyboard:
        return "尚未生成分镜，请先在「分镜预览」步骤点击生成。"

    lines = ["# 分镜时间轴", ""]
    for b in storyboard:
        lines += [
            f"## Beat {b.get('idx')} · {_safe(b.get('role'))} · {b.get('duration_sec', '?')}s",
            f"- **模式**：`{b.get('gen_mode', 'i2va')}`",
            f"- **运镜**：{_safe(b.get('motion_prompt'))}",
            f"- **口播**：{_safe(b.get('spoken'))}",
            f"- **首帧**：{(b.get('first_frame') or {}).get('prompt', '')}",
        ]
        if b.get("last_frame"):
            lines.append(f"- **尾帧**：{b['last_frame'].get('prompt', '')}")
        lines.append("")
    return "\n".join(lines)


def format_qc_preview(qc: dict | str) -> str:
    if isinstance(qc, str):
        try:
            qc = json.loads(qc)
        except Exception:
            return qc or "暂无质检报告"

    if not qc:
        return "暂无质检报告"

    score = qc.get("score", 0)
    passed = qc.get("passed", False)
    icon = "✅" if passed else "⚠️"
    lines = [
        f"# {icon} 质检得分 **{score}**",
        "",
        qc.get("summary", ""),
        "",
    ]
    issues = qc.get("issues", [])
    if not issues:
        lines.append("未发现明显问题。")
    else:
        lines.append("## 问题清单")
        for it in issues:
            lvl = it.get("level", "info")
            lines.append(f"- **[{lvl}] Beat {it.get('beat')}**：{it.get('msg')}")
    return "\n".join(lines)


def _resize_jpeg_data_uri(
    path: str | None,
    max_width: int = 480,
    max_height: int = 480,
    quality: int = 72,
) -> str | None:
    """压缩为 JPEG data URI，按宽高上限等比缩放。"""
    if not path or not Path(path).exists():
        return None
    try:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        scale = min(max_width / w, max_height / h, 1.0)
        if scale < 1.0:
            nw = max(1, int(w * scale))
            nh = max(1, int(h * scale))
            img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


def _data_uri_from_path(path: str, max_width: int, max_height: int, quality: int = 72) -> str | None:
    return _resize_jpeg_data_uri(path, max_width, max_height, quality)


_PREVIEW_CSS = ""  # 不用 <style> 块，避免代理下 HTML 过大


def _zoom_item(
    uid: str,
    thumb_uri: str,
    full_uri: str,
    alt: str,
    thumb_style: str,
    cap: str = "",
) -> str:
    safe_alt = html.escape(alt)
    cap_html = (
        f'<div style="font-size:10px;color:#aaa;margin-top:4px;line-height:1.2">{html.escape(cap)}</div>'
        if cap
        else ""
    )
    full_style = (
        "max-width:min(96vw,640px);max-height:65vh;object-fit:contain;border-radius:8px;"
        "margin:8px auto;display:block;background:#111"
    )
    return (
        f'<details id="{uid}" style="display:inline-block;vertical-align:top;text-align:center;margin:2px">'
        f'<summary style="list-style:none;cursor:zoom-in">'
        f'<img src="{thumb_uri}" alt="{safe_alt}" style="{thumb_style}"/>'
        "</summary>"
        f'<img src="{full_uri}" alt="{safe_alt}" style="{full_style}"/>'
        f"{cap_html}"
        "</details>"
    )


def _lb_id(seed: str) -> str:
    return "vp" + format(abs(hash(seed)) & 0xFFFFFFFF, "x")


def img_html(
    path: str | None,
    alt: str = "",
    max_width: int = 200,
    max_height: int = 320,
    zoom_width: int = 720,
    zoom_height: int = 1280,
    hint: str = "点击放大，再点关闭",
) -> str:
    thumb_uri = _data_uri_from_path(path, max_width, max_height)
    if not thumb_uri:
        return '<p style="color:#888;margin:8px 0">暂无图片</p>'
    full_uri = _data_uri_from_path(path, zoom_width, zoom_height, quality=85) or thumb_uri
    uid = _lb_id(str(path) + alt)
    thumb_style = (
        f"width:{max_width}px;height:{max_height}px;object-fit:contain;border-radius:8px;"
        "display:block;margin:0 auto;background:#111"
    )
    return (
        '<div style="text-align:center">'
        + _zoom_item(uid, thumb_uri, full_uri, alt or "图片", thumb_style)
        + f'<div style="font-size:11px;color:#666;margin-top:6px">{html.escape(hint)}</div>'
        + "</div>"
    )


def gallery_html(
    items: list[tuple[str, str]],
    cols: int = 5,
    thumb_width: int = 72,
    thumb_height: int = 128,
    max_items: int = 6,
) -> str:
    if not items:
        return '<p style="color:#888;margin:8px 0">暂无图片</p>'
    total = len(items)
    items = items[:max_items]
    cells: list[str] = []
    for i, (path, cap) in enumerate(items):
        thumb_uri = _resize_jpeg_data_uri(
            path, max_width=thumb_width, max_height=thumb_height, quality=58
        )
        if not thumb_uri:
            continue
        full_uri = _resize_jpeg_data_uri(path, max_width=480, max_height=854, quality=72) or thumb_uri
        uid = _lb_id(f"{path}-{i}")
        thumb_style = (
            f"width:{thumb_width}px;height:{thumb_height}px;object-fit:contain;border-radius:4px;"
            "display:block;background:#111"
        )
        cells.append(_zoom_item(uid, thumb_uri, full_uri, cap, thumb_style, cap))
    if not cells:
        return '<p style="color:#888;margin:8px 0">暂无图片</p>'
    more = ""
    if total > max_items:
        more = (
            f'<div style="width:100%;font-size:11px;color:#888;margin-top:6px">'
            f"共 {total} 帧，展示 {len(cells)} 张代表帧；完整帧请下载 ZIP</div>"
        )
    return (
        '<div style="display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-start">'
        + "".join(cells)
        + more
        + '<div style="width:100%;font-size:11px;color:#666;margin-top:4px">点击缩略图展开大图</div>'
        + "</div>"
    )


def keyframe_montage_html(plan: dict | None) -> str:
    if not plan:
        return '<p style="color:#888;margin:8px 0">暂无拼图</p>'
    mp = plan.get("keyframes_montage")
    if mp and Path(mp).exists():
        return img_html(mp, "关键帧拼图", max_width=900, max_height=380, zoom_width=1400, zoom_height=900)
    from src.studio_pipeline.dissect_service import make_keyframe_montage

    img = make_keyframe_montage(plan.get("keyframes"))
    if img is None:
        return '<p style="color:#888;margin:8px 0">暂无拼图</p>'
    try:
        buf = io.BytesIO()
        w, h = img.size
        scale = min(900 / w, 380 / h, 1.0)
        if scale < 1.0:
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        img.convert("RGB").save(buf, format="JPEG", quality=75, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        thumb_uri = f"data:image/jpeg;base64,{b64}"
        full_uri = thumb_uri
        uid = _lb_id("montage-inline")
        thumb_style = "max-width:900px;max-height:380px;width:auto;height:auto;object-fit:contain;border-radius:8px"
        return (
            '<div style="text-align:center;overflow-x:auto">'
            + _zoom_item(uid, thumb_uri, full_uri, "关键帧拼图", thumb_style)
            + '<div style="font-size:11px;color:#666;margin-top:6px">点击拼图展开大图</div>'
            + "</div>"
        )
    except Exception:
        return '<p style="color:#888;margin:8px 0">拼图生成失败</p>'


def keyframe_gallery_html(plan: dict | None) -> str:
    if not plan:
        return '<p style="color:#888;margin:8px 0">暂无关键帧</p>'
    items: list[tuple[str, str]] = []
    for i, k in enumerate(plan.get("keyframes") or []):
        p = k.get("path") if isinstance(k, dict) else k
        if not p or not Path(p).exists():
            continue
        t = k.get("t_sec", "") if isinstance(k, dict) else ""
        items.append((p, f"第{i + 1}帧 {t}s"))
    return gallery_html(items, cols=5, thumb_width=90, thumb_height=160)


def video_cover_html(plan: dict | None) -> str:
    if not plan:
        return '<p style="color:#888;margin:8px 0">暂无视频预览</p>'
    # 运行时再解析：文件后部定义了 base64 播放器
    try:
        html_player = video_player_html(plan, label="参考视频（点击播放）")
        if "暂无视频" not in html_player and "请先解析" not in html_player:
            return html_player
    except Exception:
        pass
    kfs = plan.get("keyframes") or []
    if kfs:
        p0 = kfs[0].get("path") if isinstance(kfs[0], dict) else kfs[0]
        if p0 and Path(p0).exists():
            return img_html(p0, "参考视频首帧", max_width=180, max_height=320)
    return '<p style="color:#888;margin:8px 0">暂无视频预览</p>'


def assets_gallery_html(assets: dict) -> str:
    items: list[tuple[str, str]] = []
    for img in assets.get("images", []):
        path = img.get("path")
        if path and Path(path).exists():
            cap = img.get("label") or img.get("role") or "资产"
            if img.get("status") == "draft":
                cap += " · 预览"
            elif img.get("status") == "approved":
                cap += " · 已确认"
            items.append((path, cap))
    return gallery_html(items, cols=4, thumb_width=100, thumb_height=140)


def format_replica_catalog(catalog: dict | None) -> str:
    slots = (catalog or {}).get("slots") or []
    if not slots and not (catalog or {}).get("items"):
        return "（请先完成 ① 解析，再点「① 从关键帧提取原片资产」）"
    lines: list[str] = []
    note = catalog.get("gen_note")
    if note:
        lines.append(f"【提取说明】{note}")
        lines.append("")
    lines.append("【分槽资产】点选下方角色/产品框（或框内单张），再 AI 优化提示词并确认生成")
    lines.append("")
    for slot in slots or (catalog or {}).get("items", []):
        sid = slot.get("id", "")
        lines.append(f"■ {slot.get('label', '资产')}（{sid}）")
        lines.append(slot.get("description", "（无描述）"))
        kf = [img for img in (slot.get("images") or []) if img.get("source") in ("keyframe", None)]
        if kf:
            lines.append(f"  已从 {len(kf)} 个不同关键帧提取")
        lines.append("")
    return "\n".join(lines).strip()


def catalog_refs_gallery_html(
    catalog: dict | None,
    selected_slot_id: str | None = None,
    selected_image_path: str | None = None,
) -> str:
    """原片资产分槽展示；高亮当前选中的角色框 / 单张图。"""
    slots = (catalog or {}).get("slots") or []
    if not slots:
        items: list[tuple[str, str]] = []
        for item in (catalog or {}).get("items", []):
            for img in item.get("images") or []:
                p = img.get("path")
                if p and Path(p).exists():
                    cap = img.get("label") or item.get("label", "资产")
                    items.append((p, cap))
        if not items:
            return '<p style="color:#888;margin:8px 0">（请先点「① AI提取原片资产」）</p>'
        return gallery_html(items, cols=3, thumb_width=110, thumb_height=150, max_items=12)

    sections: list[str] = []
    sel_slot = (selected_slot_id or "").strip()
    sel_img = str(Path(selected_image_path).resolve()) if selected_image_path else ""
    for slot in slots:
        sid = str(slot.get("id") or "")
        active = sid == sel_slot
        border = "2px solid #6af" if active else "1px solid #333"
        bg = "rgba(80,140,255,0.12)" if active else "rgba(255,255,255,0.03)"
        badge = " · 已选整框" if active and not sel_img else (" · 已选" if active else "")
        thumbs: list[str] = []
        for i, img in enumerate((slot.get("images") or [])[:8]):
            p = img.get("path")
            if not p or not Path(p).exists():
                continue
            thumb_uri = _resize_jpeg_data_uri(p, max_width=100, max_height=130, quality=58)
            if not thumb_uri:
                continue
            resolved = str(Path(p).resolve())
            img_on = active and sel_img and resolved == sel_img
            ring = "2px solid #fc6" if img_on else ("2px solid #6af" if active else "1px solid #444")
            cap = img.get("label") or slot.get("label", "资产")
            if img.get("t_sec") is not None:
                cap = f"{cap} · {img['t_sec']}s"
            thumbs.append(
                f'<div style="display:inline-block;text-align:center;margin:2px;'
                f'border:{ring};border-radius:6px;padding:2px;background:#111">'
                f'<img src="{thumb_uri}" alt="{html.escape(cap)}" '
                f'style="width:100px;height:130px;object-fit:contain;display:block"/>'
                f'<div style="font-size:10px;color:#aaa;max-width:100px">{html.escape(cap)}</div>'
                f"</div>"
            )
        if not thumbs:
            continue
        sections.append(
            f'<div style="margin:10px 0;padding:10px;border:{border};border-radius:10px;background:{bg}">'
            f'<div style="margin-bottom:6px"><b style="color:#8cf">{html.escape(str(slot.get("label") or sid))}</b>'
            f' <span style="color:#888;font-size:12px">({html.escape(sid)}){badge}</span>'
            f'<div style="color:#666;font-size:11px;margin-top:2px">在下方「选择角色/产品框」点选整框，'
            f"或在「框内图片」点选单张</div></div>"
            f'<div style="display:flex;flex-wrap:wrap;gap:4px">{"".join(thumbs)}</div></div>'
        )
    if not sections:
        return '<p style="color:#888;margin:8px 0">（提取失败或无关键帧，请重试）</p>'
    return '<div style="margin-top:4px">' + "".join(sections) + "</div>"


def slot_dropdown_update(catalog: dict | None, selected: str | None = None):
    slots = (catalog or {}).get("slots") or []
    if not slots:
        return gr.update(choices=[], value=None)
    choices = [(f"{s.get('label', s['id'])} ({s['id']})", s["id"]) for s in slots]
    value = selected if selected and any(s["id"] == selected for s in slots) else slots[0]["id"]
    return gr.update(choices=choices, value=value)


def slot_gallery_update(catalog: dict | None, slot_id: str | None = None):
    """当前槽位图片 → Gradio Gallery 列表 [(path, caption), ...]。"""
    slots = (catalog or {}).get("slots") or []
    if not slots:
        return gr.update(value=None)
    slot = None
    if slot_id:
        slot = next((s for s in slots if s.get("id") == slot_id), None)
    if slot is None:
        slot = slots[0]
    items: list[tuple[str, str]] = []
    for img in slot.get("images") or []:
        p = img.get("path")
        if not p or not Path(p).exists():
            continue
        cap = img.get("label") or slot.get("label", "资产")
        if img.get("t_sec") is not None:
            cap = f"{cap} · {img['t_sec']}s"
        items.append((p, cap))
    return gr.update(value=items or None)


def draft_assets_gallery_html(drafts: dict | None) -> str:
    if not drafts or not drafts.get("images"):
        return '<p style="color:#888;margin:8px 0">（尚未生成预览：选槽 → 填提示词或点「AI生成提示词」→ 点「② Agnes生成」）</p>'
    items = []
    for img in drafts.get("images") or []:
        p = img.get("path")
        if not p:
            continue
        src = img.get("source", "")
        badge = {"agnes": "Agnes", "minimax": "MiniMax", "upload": "上传"}.get(src, src or "?")
        cap = f"{img.get('label', '替换')} · {badge}"
        if img.get("prompt"):
            cap += f"｜{str(img['prompt'])[:24]}"
        items.append({**img, "label": cap})
    return assets_gallery_html({"images": items})


def replaced_keyframes_timeline_text(replaced: list[dict] | None) -> str:
    if not replaced:
        return "（生成替换关键帧后，此处显示每 5–10 秒剧情段对应的关键帧）"
    lines = [
        "══ 剧情段关键帧 ↔ 脚本 ══",
        f"共 {len(replaced)} 段（每段约 5–10 秒，覆盖全片，已全部生成替换帧）",
        "",
    ]
    for item in replaced:
        idx = item.get("idx", "?")
        t = item.get("t_sec", "?")
        beat_idx = item.get("beat_idx", "?")
        t0, t1 = item.get("t_start_sec", ""), item.get("t_end_sec", "")
        role = item.get("role", "")
        gen = item.get("gen_source", "")
        lines.append(f"第{beat_idx}段 [{t0}-{t1}s] · 代表帧 {t}s · {role} · {gen}")
        if item.get("spoken"):
            lines.append(f"  口播：{item['spoken']}")
        if item.get("visual"):
            lines.append(f"  画面：{item['visual']}")
        lines.append("")
    return "\n".join(lines).strip()


def _img_cell(path: str | None, label: str, w: int = 120, h: int = 170) -> str:
    if not path or not Path(path).exists():
        return f'<div style="color:#666;font-size:12px">{label}<br>（无）</div>'
    arr = _img_to_numpy(path)
    if arr is None:
        return f'<div style="color:#666;font-size:12px">{label}</div>'
    import base64
    from io import BytesIO

    from PIL import Image

    img = Image.fromarray(arr)
    img.thumbnail((w, h))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return (
        f'<div style="text-align:center"><div style="font-size:11px;color:#aaa;margin-bottom:4px">{html.escape(label)}</div>'
        f'<img src="data:image/jpeg;base64,{b64}" style="max-width:{w}px;max-height:{h}px;border-radius:6px;border:1px solid #444"/></div>'
    )


def replaced_keyframes_gallery_html(replaced: list[dict] | None) -> str:
    if not replaced:
        return '<p style="color:#888;margin:8px 0">（请先在 ② 生成替换关键帧）</p>'
    blocks: list[str] = []
    for item in replaced:
        idx = item.get("idx", "?")
        t = item.get("t_sec", "?")
        beat_idx = item.get("beat_idx", "?")
        t0, t1 = item.get("t_start_sec", ""), item.get("t_end_sec", "")
        role = html.escape(str(item.get("role", "")))
        spoken = html.escape(str(item.get("spoken", "") or "（无口播）")[:80])
        visual = html.escape(str(item.get("visual", "") or "（无画面描述）")[:80])
        src = item.get("source_keyframe")
        dst = item.get("path")
        gen_src = item.get("gen_source", "")
        gen_label = {
            "agnes": "Agnes生成",
            "minimax": "AI生成",
            "compose": "区域合成",
            "unchanged": "原片保留",
        }.get(gen_src, gen_src or "")
        blocks.append(
            f'<div style="border:1px solid #3a3a4a;border-radius:10px;padding:12px;margin:10px 0;background:#1a1a22">'
            f'<div style="font-weight:600;color:#9cf;margin-bottom:6px">第{beat_idx}段 [{t0}-{t1}s]'
            f' <span style="color:#888;font-weight:400">代表帧 {t}s · {role}</span>'
            f'{" · " + gen_label if gen_label else ""}</div>'
            f'<div style="font-size:12px;color:#bbb;margin-bottom:8px">口播：{spoken}</div>'
            f'<div style="font-size:12px;color:#bbb;margin-bottom:10px">画面：{visual}</div>'
            f'<div style="display:flex;gap:16px;flex-wrap:wrap">'
            f'{_img_cell(src, "原片代表帧")}{_img_cell(dst, "替换关键帧")}'
            f"</div></div>"
        )
    return (
        f'<p style="color:#9cf;font-size:13px;margin:4px 0 8px">共 {len(replaced)} 个剧情段关键帧'
        f'（按 5–10 秒排列，已全部替换）</p>'
        f'<div style="max-height:720px;overflow-y:auto">{"".join(blocks)}</div>'
    )

def replica_frames_html(plan: dict | None) -> str:
    replaced = (plan or {}).get("replaced_keyframes")
    if replaced:
        return replaced_keyframes_gallery_html(replaced)
    return storyboard_gallery_html((plan or {}).get("storyboard") or [])


def storyboard_gallery_html(storyboard: list[dict]) -> str:
    items: list[tuple[str, str]] = []
    for b in storyboard or []:
        idx = b.get("idx", "?")
        ff = b.get("first_frame") or {}
        lf = b.get("last_frame") or {}
        if ff.get("path"):
            items.append((ff["path"], f"Beat{idx} 首帧"))
        if lf.get("path"):
            items.append((lf["path"], f"Beat{idx} 尾帧"))
    return gallery_html(items, cols=4, thumb_width=100, thumb_height=140, max_items=12)



def script_to_plaintext(script: dict | str) -> str:
    if isinstance(script, str):
        return script
    lines: list[str] = []
    hook = script.get("hook", {})
    if hook.get("first_3s_script"):
        lines.append(f"【开场钩子】{hook['first_3s_script']}")
    if hook.get("visual_hook"):
        lines.append(f"（画面：{hook['visual_hook']}）")
    for b in script.get("beats", []):
        lines.append("")
        lines.append(f"--- 第{b.get('idx', '?')}段 · {b.get('role', '')} ---")
        if b.get("visual"):
            lines.append(f"画面：{b['visual']}")
        if b.get("spoken_or_subtitle"):
            lines.append(f"口播：{b['spoken_or_subtitle']}")
    skel = script.get("script_skeleton", {})
    if skel.get("spoken_script_full"):
        lines.append("")
        lines.append("【完整口播】")
        lines.append(skel["spoken_script_full"])
    if skel.get("cta"):
        lines.append("")
        lines.append(f"【结尾引导】{skel['cta']}")
    return "\n".join(lines).strip() or "（脚本为空）"


def _gallery_from_paths(paths: list[str], captions: list[str] | None = None) -> list:
    """Gallery 用 numpy 内嵌，避免代理 /file/ 请求失败。"""
    out: list = []
    for i, p in enumerate(paths):
        arr = _img_to_numpy(p)
        if arr is None:
            continue
        cap = (captions[i] if captions and i < len(captions) else "") or f"图{i + 1}"
        out.append((arr, cap))
    return out


def strip_markdown(text: str) -> str:
    """去掉 Markdown 标记，输出纯文本。"""
    if not text:
        return ""
    t = text
    t = re.sub(r"^#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"\*(.+?)\*", r"\1", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = re.sub(r"^[-*]\s+", "· ", t, flags=re.M)
    return t.strip()


def format_dissect_preview(dissect: dict | None) -> str:
    if not dissect:
        return "（尚未解析视频）"
    if dissect.get("error"):
        hint = dissect.get("hint", "")
        return (
            f"【AI 分析未完成】\n"
            f"原因：{dissect.get('error')}\n"
            f"{hint}\n"
            f"关键帧拼图仍可查看。"
        )

    parts: list[str] = []
    narrative = strip_markdown(dissect.get("_narrative", ""))
    if narrative and len(narrative) >= 200:
        parts += [
            "════════ 深度解析报告（主编导阅读区）════════",
            "",
            narrative,
            "",
        ]
    elif narrative:
        parts += [
            "════════ 深度解析报告 ════════",
            "",
            narrative,
            "",
            "（报告偏短，建议重新解析或等待模型加载完成后重试）",
            "",
        ]

    if parts:
        parts += ["════════ 结构化拆解 ════════", ""]

    meta = dissect.get("meta") or {}
    hook = dissect.get("hook") or {}
    skel = dissect.get("script_skeleton") or {}
    notes = dissect.get("replication_notes") or {}

    lines = parts + [
        "════════ 视频拆解报告 ════════",
        "",
        f"【摘要】{meta.get('one_line_summary', '')}",
        f"【时长】约 {meta.get('estimated_duration_sec', '?')} 秒",
        f"【平台】{meta.get('platform_style', '')}  【类型】{meta.get('genre', '')}",
        f"【画幅】{meta.get('aspect_ratio', '')}",
        f"【评分】钩子 {meta.get('overall_hook_score', '?')} / 留存 {meta.get('overall_retention_score', '?')} / 转化 {meta.get('overall_conversion_score', '?')}",
        "",
        "── 开场钩子 ──",
        f"类型：{hook.get('type', '')}",
        f"前3秒口播：{hook.get('first_3s_script', '')}",
        f"画面：{hook.get('visual_hook', '')}",
        f"音效：{hook.get('audio_hook', '')}",
        "",
        "── 分镜时间轴 ──",
    ]

    for b in dissect.get("beats") or []:
        idx = b.get("idx", "?")
        t0, t1 = b.get("t_start_sec", ""), b.get("t_end_sec", "")
        role = b.get("role", "")
        lines.append(f"\n第{idx}段 [{t0}-{t1}s] · {role}")
        if b.get("visual"):
            lines.append(f"  画面：{b['visual']}")
        if b.get("spoken_or_subtitle"):
            lines.append(f"  口播：{b['spoken_or_subtitle']}")
        if b.get("camera"):
            lines.append(f"  镜头：{b['camera']}")
        if b.get("emotion"):
            lines.append(f"  情绪：{b['emotion']}")
        if not b.get("visual") and not b.get("spoken_or_subtitle"):
            lines.append("  （本段描述缺失，请重新解析）")

    products = dissect.get("products") or []
    if products:
        lines += ["", "── 产品信息 ──"]
        for pr in products:
            lines.append(f"· {pr.get('name_guess', '')}（约 {pr.get('first_appear_sec', '?')}s 首次露出）")
            for sp in pr.get("selling_points") or []:
                lines.append(f"    卖点：{sp}")
            for m in pr.get("appear_moments") or []:
                lines.append(f"    露出：{m}")

    chars = dissect.get("characters") or []
    if chars:
        lines += ["", "── 人物 ──"]
        for c in chars:
            lines.append(f"· {c.get('role', '')}：{c.get('appearance', '')}")

    if skel.get("structure_pattern"):
        lines += ["", f"【结构】{skel['structure_pattern']}"]
    if skel.get("spoken_script_full"):
        lines += ["", "── 完整口播稿 ──", skel["spoken_script_full"]]
    if skel.get("cta"):
        lines += ["", f"【结尾引导】{skel['cta']}"]

    if notes.get("must_keep"):
        lines += ["", "── 复刻必保留 ──", *[f"· {x}" for x in notes["must_keep"]]]
    if notes.get("can_replace"):
        lines += ["", "── 可替换 ──", *[f"· {x}" for x in notes["can_replace"]]]
    if notes.get("shooting_checklist"):
        lines += ["", "── 拍摄清单 ──", *[f"· {x}" for x in notes["shooting_checklist"]]]

    return strip_markdown("\n".join(lines))


def _img_to_numpy(path: str | None):
    import numpy as np
    from PIL import Image

    if not path or not Path(path).exists():
        return None
    try:
        return np.array(Image.open(path).convert("RGB"), dtype=np.uint8)
    except Exception:
        return None


def keyframe_montage_numpy(plan: dict | None):
    if not plan:
        return None
    arr = _img_to_numpy(plan.get("keyframes_montage"))
    if arr is not None:
        return arr
    from src.studio_pipeline.dissect_service import make_keyframe_montage

    img = make_keyframe_montage(plan.get("keyframes"))
    if img is None:
        return None
    import numpy as np

    return np.array(img.convert("RGB"), dtype=np.uint8)


def keyframe_gallery_numpy(plan: dict | None) -> list:
    if not plan:
        return []
    out: list = []
    for i, k in enumerate(plan.get("keyframes") or []):
        p = k.get("path") if isinstance(k, dict) else k
        arr = _img_to_numpy(p)
        if arr is not None:
            t = k.get("t_sec", "") if isinstance(k, dict) else ""
            out.append((arr, f"第{i + 1}帧 {t}s"))
    return out


def video_cover_numpy(plan: dict | None):
    if not plan:
        return None
    kfs = plan.get("keyframes") or []
    if kfs:
        arr = _img_to_numpy(kfs[0].get("path"))
        if arr is not None:
            return arr
    vp = video_display_path(plan)
    if not vp:
        return None
    try:
        from src.studio_pipeline.video_frames import extract_frame_at
        from PIL import Image
        import numpy as np

        thumb = Path(vp).with_suffix(".cover.jpg")
        extract_frame_at(vp, str(thumb), 0.5)
        if thumb.exists():
            return np.array(Image.open(thumb).convert("RGB"), dtype=np.uint8)
    except Exception:
        pass
    return None


def video_display_path(plan: dict | None) -> str | None:
    if not plan:
        return None
    for key in ("reference_video_download", "reference_video_display", "reference_video"):
        p = plan.get(key)
        if p and Path(p).exists():
            return str(Path(p).resolve())
    return None


def playable_video_path(path: str | None) -> str | None:
    """确保返回浏览器可播 mp4；必要时现场转码。"""
    if not path or not Path(path).exists():
        return None
    src = Path(path)
    web = src if src.name.endswith("_web.mp4") else src.with_name(src.stem + "_web.mp4")
    if web.exists() and web.stat().st_size > 2000:
        return str(web.resolve())
    try:
        from src.studio_pipeline.video_frames import ensure_web_mp4

        return str(ensure_web_mp4(src, web).resolve())
    except Exception:
        return str(src.resolve())


def video_player_html(plan: dict | None, *, label: str = "视频") -> str:
    vp = playable_video_path(video_display_path(plan))
    return video_player_from_path(vp, label=label)


def video_player_from_path(path: str | None, *, label: str = "成片预览") -> str:
    """用 data URL 内嵌播放，绕过代理 /file= 导致的 NaN/黑屏。"""
    vp = playable_video_path(path)
    if not vp:
        return f'<p style="color:#888;margin:8px 0">（{html.escape(label)}：暂无视频，请先解析或生成成片）</p>'
    p = Path(vp)
    size_mb = p.stat().st_size / (1024 * 1024)
    # 过大时提示下载，仍尝试给短预览
    if size_mb > 28:
        return (
            f'<div style="margin:8px 0"><div style="color:#aaa;font-size:12px;margin-bottom:6px">'
            f'{html.escape(label)}（{size_mb:.1f}MB，请用下方「下载」按钮）</div>'
            f'<p style="color:#c96">文件较大，请点「下载 MP4」到本地播放</p></div>'
        )
    try:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    except Exception as e:
        return f'<p style="color:#c66">视频读取失败：{html.escape(str(e))}</p>'
    return (
        f'<div style="margin:8px 0">'
        f'<div style="color:#9cf;font-size:12px;margin-bottom:6px">{html.escape(label)} · {size_mb:.1f}MB · 可直接播放</div>'
        f'<video controls playsinline preload="metadata" '
        f'style="width:100%;max-width:420px;max-height:640px;border-radius:8px;background:#000" '
        f'src="data:video/mp4;base64,{b64}"></video></div>'
    )


def keyframe_montage_path(plan: dict | None) -> str | None:
    if not plan:
        return None
    mp = plan.get("keyframes_montage")
    if mp and Path(mp).exists():
        return str(Path(mp).resolve())
    return None


def keyframe_file_list(plan: dict | None) -> list[str]:
    if not plan:
        return []
    out: list[str] = []
    for k in plan.get("keyframes") or []:
        p = k.get("path") if isinstance(k, dict) else k
        if p and Path(p).exists():
            out.append(str(Path(p).resolve()))
    return out


def keyframe_zip_path(plan: dict | None) -> str | None:
    if not plan:
        return None
    zp = plan.get("keyframes_zip")
    return zp if zp and Path(zp).exists() else None


def file_path(upload) -> str | None:
    """统一解析 Gradio File / 路径输入。"""
    if upload is None:
        return None
    if isinstance(upload, str):
        return upload if Path(upload).exists() else None
    path = getattr(upload, "name", None) or str(upload)
    return path if path and Path(path).exists() else None


def video_thumbnail(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    thumb = Path(path).with_name(Path(path).stem + "_thumb.jpg")
    if thumb.exists():
        return str(thumb)
    try:
        from src.studio_pipeline.video_frames import extract_frame_at

        extract_frame_at(path, str(thumb), 0.5)
        return str(thumb) if thumb.exists() else None
    except Exception:
        return None
