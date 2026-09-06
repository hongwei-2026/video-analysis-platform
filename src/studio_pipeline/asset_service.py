from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from src.studio_pipeline.image_gen import (
    box_norm_to_pixels,
    compose_replacement_frame,
    generate_character_view,
    generate_product_shot,
    generate_replacement_character,
    generate_replacement_keyframe,
    generate_replacement_product,
    render_character_angle,
    render_storyboard_frame,
)
from src.studio_pipeline.frame_extract import (
    active_slots_for_beat,
    box_for_slot_on_frame,
    pick_slots_for_keyframe,
)
from src.studio_pipeline.llm_service import plan_assets, plan_storyboard
from src.studio_pipeline.project_store import ProjectStore
from src.studio_pipeline.video_frames import extract_frame_at, slice_video_clip


class AssetService:
    def __init__(self, store: ProjectStore):
        self.store = store

    def build_assets(
        self,
        project_id: str,
        script: dict[str, Any],
        uploads: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        uploads = uploads or {}
        asset_plan = plan_assets(script)
        assets_dir = self.store.assets_dir(project_id)
        images: list[dict[str, Any]] = []

        char = asset_plan.get("character_sheet", {})
        persona = char.get("persona", script.get("characters", [{}])[0].get("appearance", "年轻主播"))
        for angle in char.get("angles", [
            {"id": "front", "label": "正脸", "prompt": f"{persona}，正面半身，9:16竖屏，柔和自然光"},
            {"id": "three_quarter", "label": "3/4侧", "prompt": f"{persona}，3/4侧面半身，9:16"},
            {"id": "full", "label": "全身", "prompt": f"{persona}，全身站立，9:16"},
        ]):
            aid = f"char_{angle['id']}"
            out = assets_dir / f"{aid}.png"
            upload_key = f"character_{angle['id']}"
            if uploads.get(upload_key) and Path(uploads[upload_key]).exists():
                shutil.copy2(uploads[upload_key], out)
                source = "upload"
            else:
                render_character_angle(angle.get("prompt", persona), out, label=angle.get("label", ""))
                source = "ai"
            images.append(
                {
                    "id": aid,
                    "path": str(out),
                    "prompt": angle.get("prompt", ""),
                    "role": f"character_{angle['id']}",
                    "source": source,
                }
            )

        product_prompt = asset_plan.get("product", {}).get(
            "prompt",
            script.get("products", [{}])[0].get("name_guess", script.get("meta", {}).get("one_line_summary", "产品")),
        )
        product_path = assets_dir / "product.png"
        if uploads.get("product") and Path(uploads["product"]).exists():
            shutil.copy2(uploads["product"], product_path)
            p_source = "upload"
        else:
            render_storyboard_frame(f"产品展示：{product_prompt}", product_path, tag="产品")
            p_source = "ai"
        images.append(
            {
                "id": "product",
                "path": str(product_path),
                "prompt": product_prompt,
                "role": "product",
                "source": p_source,
            }
        )

        assets = {
            "plan": asset_plan,
            "character_ref": images[0]["path"] if images else None,
            "images": images,
            "scene_style": asset_plan.get("scene_style", {}).get("prompt", "明亮种草风，9:16"),
        }
        return assets

    def build_replica_catalog(
        self,
        dissect: dict[str, Any] | None,
        keyframes: list[dict] | None,
        assets_dir: str | Path,
        *,
        generate_images: bool = True,
    ) -> dict[str, Any]:
        """优先 VL+Agnes AI 分人提取；失败再回退颜色聚类。"""
        import os

        from src.studio_pipeline.frame_extract import extract_multi_view_assets

        assets_dir = Path(assets_dir)
        use_ai = bool(os.environ.get("AGNES_API_KEY", "").strip()) or os.environ.get(
            "REPLICA_ASSET_AI", "1"
        ).strip() not in ("0", "false", "no")

        extracted: dict[str, Any] = {}
        if use_ai:
            try:
                from src.studio_pipeline.asset_ai import build_asset_slots_with_ai

                extracted = build_asset_slots_with_ai(
                    keyframes, dissect, assets_dir, whiten_with_agnes=generate_images
                )
            except Exception as e:
                extracted = {"slots": [], "gen_note": f"AI提取异常：{e}", "error": str(e)}

        if not (extracted.get("slots") or []):
            extracted = extract_multi_view_assets(keyframes, dissect, assets_dir)
            extracted["gen_note"] = (extracted.get("gen_note") or "") + "｜已回退颜色聚类"

        slots: list[dict[str, Any]] = list(extracted.get("slots") or [])
        gen_note = extracted.get("gen_note", "")

        # Agnes 已在 AI 路径做白底；仅当槽内还没有 agnes 图时再补一张「该槽专属」正面
        if generate_images and slots and os.environ.get("AGNES_API_KEY", "").strip():
            for slot in slots:
                if slot.get("type") != "character":
                    continue
                if any(img.get("source") == "agnes" for img in (slot.get("images") or [])):
                    continue
                if not slot.get("images"):
                    continue
                ref = slot["images"][0].get("crop_path") or slot["images"][0].get("path")
                out = assets_dir / f"ai_{slot['id']}_front.png"
                hint = slot.get("appearance") or slot.get("description") or slot.get("label") or ""
                _, src_name = generate_character_view(
                    f"{hint}，半身正面，纯白背景，只要这一个人",
                    "front",
                    out,
                    subject_ref=ref,
                    fallback_ref=ref,
                )
                slot["images"].append(
                    {
                        "path": str(out.resolve()),
                        "label": f"{slot['label']}·AI正面",
                        "source": src_name,
                    }
                )
            gen_note += "；已确认 Agnes/AI 白底资产"

        items = [
            {
                "id": s["id"],
                "label": s["label"],
                "description": s.get("description", ""),
                "images": s.get("images", []),
                "type": s.get("type"),
                "box_norm": s.get("box_norm"),
            }
            for s in slots
        ]

        return {
            "slots": slots,
            "extracted": extracted,
            "items": items,
            "gen_note": gen_note,
            "gen_calls": 0,
        }

    def draft_replacement_for_slot(
        self,
        project_id: str,
        catalog: dict[str, Any],
        target_slot_id: str,
        prompt: str = "",
        uploads: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        """仅为选中的一个资产槽用 AI 生成替换图（必须真正换人/换品）。"""
        uploads = uploads or {}
        assets_dir = self.store.assets_dir(project_id)
        slot = next((s for s in catalog.get("slots", []) if s.get("id") == target_slot_id), None)
        if not slot:
            raise ValueError(f"请先提取资产，并选择有效槽位（当前：{target_slot_id or '未选'}）")

        hint = (prompt or "").strip()
        out = assets_dir / f"draft_{target_slot_id}.png"
        slot_type = slot.get("type", "character")
        upload = uploads.get("image")
        upload_ok = bool(upload and Path(upload).exists())

        if upload_ok and not hint:
            # 仅上传：直接用上传图
            shutil.copy2(upload, out)
            source = "upload"
        elif slot_type == "product":
            if not hint and not upload_ok:
                raise ValueError("请填写产品替换提示词，或上传产品图")
            if upload_ok and not hint:
                shutil.copy2(upload, out)
                source = "upload"
            else:
                _, source = generate_replacement_product(
                    hint or slot.get("description", ""),
                    out,
                    slot_label=slot.get("label", ""),
                    upload_ref=upload if upload_ok else None,
                )
        else:
            if not hint and not upload_ok:
                raise ValueError("请填写人物替换提示词（例：男生，帅气），或上传替换人物图")
            if upload_ok and not hint:
                shutil.copy2(upload, out)
                source = "upload"
            else:
                # 关键：不传原片裁剪作参考，否则 AI 会锁原脸，看起来像没换
                _, source = generate_replacement_character(
                    hint,
                    out,
                    slot_label=slot.get("label", ""),
                    upload_ref=upload if upload_ok else None,
                )

        if source not in ("agnes", "minimax", "upload"):
            raise RuntimeError(f"替换资产未走 AI（source={source}），请检查 AGNES_API_KEY")

        entry = {
            "slot_id": target_slot_id,
            "path": str(out.resolve()),
            "prompt": hint,
            "label": f"替换·{slot['label']}",
            "source": source,
            "status": "draft",
            "type": slot_type,
            "box_norm": slot.get("box_norm"),
            "ai_replaced": source in ("agnes", "minimax"),
        }
        return entry

    def suggest_replacement_prompt(
        self,
        catalog: dict[str, Any],
        target_slot_id: str,
        user_hint: str = "",
    ) -> str:
        """AI 为选中槽位生成/优化替换提示词。"""
        from src.studio_pipeline.llm_service import generate_text

        slot = next((s for s in catalog.get("slots", []) if s.get("id") == target_slot_id), None)
        if not slot:
            raise ValueError("请先选择要替换的资产槽")
        st = slot.get("type", "character")
        label = slot.get("label", "")
        desc = slot.get("description", "")
        hint = (user_hint or "").strip()
        if st == "product":
            if hint:
                user = (
                    f"原片产品槽：{label}\n原描述：{desc}\n用户草稿：{hint}\n"
                    "请把草稿优化成可用于文生图的产品替换提示词（中文，1–3 句），"
                    "写清外观/颜色/材质/包装，适合纯白背景商品图。只输出提示词本身。"
                )
            else:
                user = (
                    f"原片产品槽：{label}\n描述：{desc}\n"
                    "请写一条可用于文生图的产品替换提示词（中文，1–3 句），"
                    "描述外观/颜色/材质/包装，适合纯白背景商品图。只输出提示词本身。"
                )
        else:
            if hint:
                user = (
                    f"原片人物槽：{label}\n原描述：{desc}\n用户草稿：{hint}\n"
                    "请把草稿优化成可用于文生图的人物替换提示词（中文，1–3 句），"
                    "包含性别年龄发型衣着气质，适合纯白背景半身肖像。只输出提示词本身。"
                )
            else:
                user = (
                    f"原片人物槽：{label}\n描述：{desc}\n"
                    "用户想把这个人换成另一个人。请写一条可用于文生图的人物替换提示词（中文，1–3 句），"
                    "包含性别年龄发型衣着气质，适合纯白背景半身肖像。只输出提示词本身，不要解释。"
                )
        text = generate_text(
            "你是短视频换人/换品提示词助手。只输出可直接用于生图的提示词。",
            user,
            max_new_tokens=180,
        )
        text = (text or "").strip().strip('"').strip("'")
        for prefix in ("提示词：", "提示词:", "Prompt:", "prompt:", "优化后：", "优化后:"):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
        if len(text) < 4:
            text = hint or (
                "年轻帅气男生，短发，白T恤，自然微笑"
                if st != "product"
                else "简约白瓶黄盖洗洁精，居中产品图"
            )
        return text[:320]

    def draft_replacement_assets(
        self,
        project_id: str,
        catalog: dict[str, Any],
        target_slot_id: str = "",
        prompt: str = "",
        product_prompt: str = "",
        uploads: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        """兼容：单槽替换；product_prompt/旧参数忽略。"""
        uploads = uploads or {}
        up = {}
        if uploads.get("character_front") or uploads.get("image"):
            up["image"] = uploads.get("image") or uploads.get("character_front")
        if not target_slot_id:
            # 默认第一个 character 槽
            for s in catalog.get("slots", []):
                if s.get("type") == "character":
                    target_slot_id = s["id"]
                    break
            if not target_slot_id and catalog.get("slots"):
                target_slot_id = catalog["slots"][0]["id"]
        entry = self.draft_replacement_for_slot(project_id, catalog, target_slot_id, prompt, up)
        return {
            "approved": False,
            "target_slot_id": target_slot_id,
            "prompt": prompt,
            "slots": {target_slot_id: entry},
            "images": [entry],
        }

    def approved_from_drafts(self, project_id: str, drafts: dict[str, Any]) -> dict[str, Any]:
        assets_dir = self.store.assets_dir(project_id)
        slot_map: dict[str, dict[str, Any]] = dict(drafts.get("slots") or {})
        if not slot_map and drafts.get("images"):
            for img in drafts["images"]:
                sid = img.get("slot_id") or img.get("id", "char_0")
                slot_map[sid] = img

        slot_replacements: dict[str, str] = {}
        images: list[dict[str, Any]] = []
        char_ref = None
        for sid, img in slot_map.items():
            src = Path(img["path"])
            if not src.exists():
                continue
            dst = assets_dir / f"approved_{sid}.png"
            shutil.copy2(src, dst)
            p = str(dst.resolve())
            slot_replacements[sid] = p
            approved = {**img, "path": p, "status": "approved"}
            images.append(approved)
            if img.get("type") == "character" and char_ref is None:
                char_ref = p

        return {
            "slot_replacements": slot_replacements,
            "character_ref": char_ref,
            "images": images,
            "scene_style": "沿用原片光线与场景",
            "approved": True,
        }

    def build_replica_assets(
        self,
        project_id: str,
        script: dict[str, Any],
        uploads: dict[str, str | None] | None = None,
        replacement_notes: str = "",
        dissect: dict[str, Any] | None = None,
        keyframes: list[dict] | None = None,
    ) -> dict[str, Any]:
        """A 模式：从关键帧提取原片资产，再上传或 AI 生成替换资产。"""
        from src.studio_pipeline.frame_extract import extract_reference_assets

        uploads = uploads or {}
        assets_dir = self.store.assets_dir(project_id)
        extracted = extract_reference_assets(keyframes, assets_dir)

        meta = (dissect or {}).get("meta") or {}
        chars = (dissect or {}).get("characters") or []
        products = (dissect or {}).get("products") or []

        char_hint = (
            replacement_notes
            or (chars[0].get("appearance") if chars else "")
            or meta.get("one_line_summary", "")
            or "竖屏短视频出镜主播，自然光"
        )
        product_hint = (
            (products[0].get("name_guess") if products else "")
            or meta.get("topic", "")
            or "种草产品"
        )
        if replacement_notes:
            char_hint = replacement_notes
            product_hint = replacement_notes

        images: list[dict[str, Any]] = []
        if extracted.get("ref_character"):
            images.append(
                {
                    "id": "ref_char",
                    "path": extracted["ref_character"],
                    "role": "ref_character",
                    "label": "原片人物（自动提取）",
                    "source": "extracted",
                }
            )
        if extracted.get("ref_product"):
            images.append(
                {
                    "id": "ref_prod",
                    "path": extracted["ref_product"],
                    "role": "ref_product",
                    "label": "原片产品（自动提取）",
                    "source": "extracted",
                }
            )

        char_out = assets_dir / "char_front.png"
        if uploads.get("character_front") and Path(uploads["character_front"]).exists():
            shutil.copy2(uploads["character_front"], char_out)
            char_source = "upload"
        else:
            render_character_angle(
                f"{char_hint}，正面半身，9:16竖屏，柔和自然光，高清",
                char_out,
                label="替换人物",
            )
            char_source = "ai"
        images.append(
            {
                "id": "char_front",
                "path": str(char_out),
                "role": "character_front",
                "label": "替换人物",
                "source": char_source,
            }
        )

        if uploads.get("character_three_quarter") and Path(uploads["character_three_quarter"]).exists():
            p34 = assets_dir / "char_three_quarter.png"
            shutil.copy2(uploads["character_three_quarter"], p34)
            images.append(
                {
                    "id": "char_34",
                    "path": str(p34),
                    "role": "character_three_quarter",
                    "label": "替换人物侧脸",
                    "source": "upload",
                }
            )

        product_out = assets_dir / "product.png"
        if uploads.get("product") and Path(uploads["product"]).exists():
            shutil.copy2(uploads["product"], product_out)
            prod_source = "upload"
        else:
            render_storyboard_frame(
                f"产品展示特写：{product_hint}，白底或生活场景，9:16",
                product_out,
                tag="替换产品",
            )
            prod_source = "ai"
        images.append(
            {
                "id": "product",
                "path": str(product_out),
                "role": "product",
                "label": "替换产品",
                "source": prod_source,
            }
        )

        return {
            "extracted": extracted,
            "plan": {"replacement_notes": replacement_notes},
            "character_ref": str(char_out),
            "images": images,
            "scene_style": "沿用原片光线与场景",
        }


class StoryboardService:
    def __init__(self, store: ProjectStore):
        self.store = store

    @staticmethod
    def _nearest_beat(beats: list[dict], t_sec: float) -> dict | None:
        if not beats:
            return None
        for b in beats:
            try:
                t0 = float(b.get("t_start_sec", 0))
                t1 = float(b.get("t_end_sec", t0 + 5))
            except (TypeError, ValueError):
                continue
            if t0 <= t_sec <= t1:
                return b
        best: dict | None = None
        best_d = float("inf")
        for b in beats:
            try:
                t0 = float(b.get("t_start_sec", 0))
                t1 = float(b.get("t_end_sec", t0 + 5))
            except (TypeError, ValueError):
                continue
            center = (t0 + t1) / 2
            d = abs(center - t_sec)
            if d < best_d:
                best_d = d
                best = b
        return best

    @staticmethod
    def _nearest_replaced(replaced: list[dict], t_sec: float) -> dict | None:
        if not replaced:
            return None
        best = replaced[0]
        best_d = float("inf")
        for item in replaced:
            try:
                d = abs(float(item.get("t_sec", 0)) - t_sec)
            except (TypeError, ValueError):
                continue
            if d < best_d:
                best_d = d
                best = item
        return best

    def build_replaced_keyframes(
        self,
        project_id: str,
        keyframes: list[dict],
        assets: dict[str, Any],
        dissect: dict | None,
        catalog: dict[str, Any] | None,
        draft_prompts: dict[str, str] | None = None,
        *,
        reference_video: str | None = None,
    ) -> list[dict[str, Any]]:
        """按 5–10s 剧情段全量替换关键帧（一段一张，覆盖整片）。"""
        from src.studio_pipeline.timeline import pick_source_for_beat

        beats = list((dissect or {}).get("beats") or [])
        if not beats and not keyframes:
            raise ValueError("没有原片关键帧/剧情段，请重新解析视频")

        # 无剧情段时：把密集体抽帧压缩成伪段（不应常发生，解析后已 normalize）
        if not beats:
            beats = []
            for i, kf in enumerate(keyframes):
                t = float(kf.get("t_sec", i * 5))
                beats.append(
                    {
                        "idx": i + 1,
                        "t_start_sec": t,
                        "t_end_sec": t + 5,
                        "duration_sec": 5,
                        "keyframe_t_sec": t,
                        "role": f"第{i + 1}段",
                        "spoken": "",
                        "visual": "",
                    }
                )

        frames_dir = self.store.frames_dir(project_id)
        slot_refs: dict[str, str] = dict(assets.get("slot_replacements") or {})
        catalog_slots = list((catalog or {}).get("slots") or [])
        slot_by_id = {s["id"]: s for s in catalog_slots}
        prompts = draft_prompts or {}
        result: list[dict[str, Any]] = []

        for beat in beats:
            idx = int(beat.get("idx") or (len(result) + 1))
            t0 = float(beat.get("t_start_sec", (idx - 1) * 5))
            t1 = float(beat.get("t_end_sec", t0 + 5))
            role = beat.get("role", "")
            spoken = beat.get("spoken_or_subtitle") or beat.get("spoken", "")
            visual = beat.get("visual", "")

            src_info = pick_source_for_beat(
                beat,
                keyframes,
                video_path=reference_video,
                out_image=str(frames_dir / f"story_src_{idx:02d}.jpg"),
            )
            src = src_info["path"]
            t_sec = float(src_info["t_sec"])

            out_path = frames_dir / f"story_{idx:02d}_replaced.png"
            tag = f"第{idx}段 {t0:.0f}-{t1:.0f}s · 代表帧{t_sec:.1f}s"

            from PIL import Image

            with Image.open(src) as im:
                w, h = im.size

            approved_ids = set(slot_refs.keys())
            active = pick_slots_for_keyframe(
                src,
                t_sec,
                catalog_slots,
                beat,
                dissect,
                approved_ids=approved_ids,
            )
            c_ref = p_ref = None
            c_box = p_box = None
            c_prompt = p_prompt = ""
            remove_label = ""
            remove_appearance = ""
            for sid in active:
                ref = slot_refs.get(sid)
                if not ref:
                    continue
                sm = slot_by_id.get(sid, {})
                px = box_for_slot_on_frame(sm, src, t_sec, w, h)
                if sm.get("type") == "character":
                    c_ref, c_box = ref, px
                    c_prompt = prompts.get(sid) or sm.get("description", "")
                    remove_label = str(sm.get("label") or sid)
                    remove_appearance = str(sm.get("description") or sm.get("appearance") or "")
                elif sm.get("type") == "product":
                    p_ref, p_box = ref, px
                    p_prompt = prompts.get(sid) or sm.get("description", "")

            # 剧情段：每一段都必须产出替换关键帧（无匹配资产则 AI 复刻原构图）
            _, gen_src = generate_replacement_keyframe(
                visual=visual,
                role=role,
                spoken=spoken,
                char_ref=c_ref,
                char_prompt=c_prompt,
                product_prompt=p_prompt,
                out_path=out_path,
                source_frame=src,
                char_box=c_box,
                product_ref=p_ref,
                product_box=p_box,
                tag=tag,
                force_ai=True,
                remove_label=remove_label,
                remove_appearance=remove_appearance,
            )
            result.append(
                {
                    "idx": idx,
                    "kf_index": idx - 1,
                    "t_sec": t_sec,
                    "source_keyframe": src,
                    "path": str(out_path.resolve()),
                    "beat_idx": idx,
                    "t_start_sec": t0,
                    "t_end_sec": t1,
                    "role": role,
                    "spoken": spoken,
                    "visual": visual,
                    "duration_sec": beat.get("duration_sec") or int(round(t1 - t0)),
                    "gen_source": gen_src,
                    "story_segment": True,
                }
            )
        if not result:
            raise ValueError("未能生成替换关键帧")
        return result

    @staticmethod
    def _nearest_keyframe(keyframes: list[dict], t_sec: float) -> str | None:
        if not keyframes:
            return None
        best = keyframes[0]
        best_d = float("inf")
        for k in keyframes:
            try:
                d = abs(float(k.get("t_sec", 0)) - t_sec)
            except (TypeError, ValueError):
                d = float("inf")
            if d < best_d:
                best_d = d
                best = k
        p = best.get("path")
        return p if p and Path(p).exists() else None

    def build_storyboard(
        self,
        project_id: str,
        script: dict[str, Any],
        assets: dict[str, Any],
        mode: str,
        dissect: dict | None = None,
        reference_video: str | None = None,
        keyframes: list[dict] | None = None,
        replacement_notes: str = "",
        catalog: dict[str, Any] | None = None,
        replaced_keyframes: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        sb_plan: dict[str, Any] = {}
        if mode == "A":
            beats_in = (dissect or {}).get("beats") or script.get("beats") or []
        else:
            sb_plan = plan_storyboard(script, mode, dissect)
            beats_in = sb_plan.get("beats") or script.get("beats", [])
        if not beats_in:
            raise ValueError("没有可用分镜节拍，请重新解析视频")
        frames_dir = self.store.frames_dir(project_id)
        clips_dir = self.store.clips_dir(project_id)
        char_ref = assets.get("character_ref")
        slot_refs: dict[str, str] = dict(assets.get("slot_replacements") or {})
        catalog_slots = list((catalog or {}).get("slots") or [])
        slot_by_id = {s["id"]: s for s in catalog_slots}
        storyboard: list[dict[str, Any]] = []
        use_replica = mode == "A" and keyframes

        for i, beat in enumerate(beats_in, start=1):
            idx = beat.get("idx", i)
            duration = int(max(4, min(15, beat.get("duration_sec", 5))))
            spoken = beat.get("spoken") or beat.get("spoken_or_subtitle", "")
            gen_mode = beat.get("gen_mode", "i2va")
            use_ref = bool(beat.get("use_reference_video")) and reference_video

            first_prompt = beat.get("first_frame_prompt") or beat.get("visual", "竖屏短视频画面")
            last_prompt = beat.get("last_frame_prompt", "")
            first_path = frames_dir / f"beat_{idx:02d}_first.png"
            visual = str(beat.get("visual") or first_prompt or "")
            from src.studio_pipeline.timeline import motion_prompt_from_beat

            motion = motion_prompt_from_beat(beat)

            if use_replica:
                import shutil

                t0 = float(beat.get("t_start_sec", (idx - 1) * 5))
                composed = False
                if replaced_keyframes:
                    # 优先按 beat_idx 精确对齐剧情段关键帧
                    rk = None
                    for item in replaced_keyframes:
                        if int(item.get("beat_idx") or 0) == int(idx):
                            rk = item
                            break
                    if rk is None:
                        rk = self._nearest_replaced(replaced_keyframes, t0)
                    if rk and Path(rk["path"]).exists():
                        shutil.copy2(rk["path"], first_path)
                        gen_mode = "i2va"
                        composed = True
                if not composed:
                    ref_kf = self._nearest_keyframe(keyframes or [], t0)
                    if ref_kf:
                        from PIL import Image

                        with Image.open(ref_kf) as im:
                            w, h = im.size
                        active = active_slots_for_beat(beat, catalog_slots, dissect) if catalog_slots else []
                        c_ref = p_ref = None
                        c_box = p_box = None
                        for sid in active:
                            ref = slot_refs.get(sid)
                            if not ref:
                                continue
                            sm = slot_by_id.get(sid, {})
                            box_n = sm.get("box_norm")
                            px = box_norm_to_pixels(box_n, w, h) if box_n else None
                            if sm.get("type") == "character":
                                c_ref, c_box = ref, px
                            elif sm.get("type") == "product":
                                p_ref, p_box = ref, px
                        if not active and char_ref:
                            c_ref = char_ref
                        compose_replacement_frame(
                            ref_kf,
                            first_path,
                            char_ref=c_ref,
                            product_ref=p_ref,
                            char_box=c_box,
                            product_box=p_box,
                            tag=f"Beat{idx}",
                        )
                        gen_mode = "i2va"
                    else:
                        render_storyboard_frame(first_prompt, first_path, tag=f"Beat{idx}·首帧", ref_image=char_ref)
            else:
                render_storyboard_frame(first_prompt, first_path, tag=f"Beat{idx}·首帧", ref_image=char_ref)
            last_path = None
            if last_prompt or gen_mode == "i2va_fl":
                last_path = frames_dir / f"beat_{idx:02d}_last.png"
                render_storyboard_frame(
                    last_prompt or first_prompt + "，表情/构图略有变化",
                    last_path,
                    tag=f"Beat{idx}·尾帧",
                    ref_image=char_ref,
                )
                gen_mode = "i2va_fl"

            ref_clip = None
            if use_ref and reference_video:
                t0 = beat.get("t_start_sec", (idx - 1) * 5)
                t1 = beat.get("t_end_sec", t0 + duration)
                ref_clip = str(clips_dir / f"ref_beat_{idx:02d}.mp4")
                try:
                    slice_video_clip(reference_video, ref_clip, t0, min(t1, t0 + 15))
                except Exception:
                    ref_clip = None
                    gen_mode = "i2va"

            storyboard.append(
                {
                    "idx": idx,
                    "role": beat.get("role", ""),
                    "duration_sec": duration,
                    "t_start_sec": float(beat.get("t_start_sec", (idx - 1) * 5)),
                    "t_end_sec": float(beat.get("t_end_sec", (idx - 1) * 5 + duration)),
                    "motion_prompt": motion,
                    "spoken": spoken,
                    "visual": visual,
                    "camera": beat.get("camera", ""),
                    "gen_mode": "r2va" if ref_clip else gen_mode,
                    "first_frame": {
                        "path": str(first_path),
                        "prompt": first_prompt,
                        "role": "first_frame",
                        "source": "ai",
                    },
                    "last_frame": (
                        {
                            "path": str(last_path),
                            "prompt": last_prompt or first_prompt,
                            "role": "last_frame",
                            "source": "ai",
                        }
                        if last_path
                        else None
                    ),
                    "reference_video_clip": ref_clip,
                    "reference_image_path": char_ref,
                    "status": "planned",
                }
            )
        return storyboard
