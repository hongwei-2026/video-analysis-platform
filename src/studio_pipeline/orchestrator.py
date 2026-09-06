from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.studio_pipeline.asset_service import AssetService, StoryboardService
from src.studio_pipeline.llm_service import generate_script, meta_from_dissect, dissect_to_script, pretty_json, script_from_plaintext
from src.studio_pipeline.agnes_client import get_video_client
from src.studio_pipeline.project_store import ProjectStore
from src.studio_pipeline.qc_service import run_qc
from src.studio_pipeline.timeline import normalize_replica_timeline
from src.studio_pipeline.video_frames import concat_clips, ensure_web_mp4, slice_video_clip, video_duration_sec
from src.studio_pipeline.model_loader import load_vl


class StudioOrchestrator:
    def __init__(self, projects_root: str | Path | None = None):
        root = projects_root or os.environ.get("STUDIO_PROJECTS_DIR", "data/studio_projects")
        self.store = ProjectStore(root)
        self.assets = AssetService(self.store)
        self.storyboard = StoryboardService(self.store)

    def start_project(
        self,
        *,
        mode: str,
        product: str,
        topic: str,
        audience: str,
        style: str,
        video_path: str | None = None,
        user_script: str = "",
    ) -> dict[str, Any]:
        project_id = self.store.new_id()
        plan = {
            "project_id": project_id,
            "mode": mode,
            "script": {},
            "dissect": None,
            "keyframes": [],
            "reference_video": video_path,
            "meta": {
                "product": product,
                "topic": topic,
                "audience": audience,
                "style": style,
                "user_script": user_script or "",
            },
            "assets": {},
            "storyboard": [],
            "clips": [],
            "output": {},
            "steps": {"parsed": False, "scripted": False, "assets": False, "storyboard": False, "video": False},
        }
        self.store.save_plan(plan)
        return plan

    def parse_reference_video(self, project_id: str) -> dict[str, Any]:
        from src.studio_pipeline.dissect_service import (
            build_dissect_system,
            enrich_dissect_narrative,
            expand_dissect_details,
            make_keyframe_montage,
            merge_dissect,
        )
        from src.studio_pipeline.video_frames import extract_keyframes, pack_keyframes_zip
        from src.video_platform.dissector import VideoDissector
        from src.video_platform.prompts import DISSECT_USER
        from src.video_platform.utils import extract_json

        plan = self.store.load_plan(project_id)
        video_path = plan.get("reference_video")
        if not video_path or not Path(video_path).exists():
            raise ValueError("请先上传参考视频")

        frames_dir = self.store.frames_dir(project_id)
        keyframes = extract_keyframes(video_path, frames_dir, num_frames=24)
        plan["keyframes"] = keyframes
        plan["keyframes_zip"] = pack_keyframes_zip(keyframes, frames_dir / "keyframes.zip")
        montage_path = frames_dir / "montage.jpg"
        montage = make_keyframe_montage(keyframes, montage_path)
        plan["keyframes_montage"] = str(montage_path.resolve()) if montage else None

        # 复制并转成浏览器可播 mp4（解决代理下 NaN/黑屏）
        import shutil

        from src.studio_pipeline.video_frames import ensure_web_mp4

        raw_copy = self.store.project_dir(project_id) / "reference_raw.mp4"
        display_video = self.store.project_dir(project_id) / "reference.mp4"
        shutil.copy2(video_path, raw_copy)
        try:
            ensure_web_mp4(raw_copy, display_video)
        except Exception:
            shutil.copy2(raw_copy, display_video)
        plan["reference_video_display"] = str(display_video.resolve())
        plan["reference_video_download"] = str(display_video.resolve())

        dissect: dict[str, Any] | None = None
        vl_error = ""
        try:
            engine = load_vl()
            frame_paths = [Path(k["path"]) for k in keyframes if Path(k["path"]).exists()]

            # ① 关键帧深度拆解（主路径）
            messages = [
                {"role": "system", "content": [{"type": "text", "text": build_dissect_system()}]},
                {
                    "role": "user",
                    "content": [
                        *[{"type": "image", "image": str(p.resolve())} for p in frame_paths],
                        {
                            "type": "text",
                            "text": DISSECT_USER
                            + f"\n（共 {len(frame_paths)} 张关键帧，按时间顺序。请输出至少 8 个互不重复的 beats，口播尽量完整。）",
                        },
                    ],
                },
            ]
            raw = engine.chat(messages, max_new_tokens=4096)
            try:
                dissect = extract_json(raw)
            except Exception:
                dissect = {"parse_error": True, "raw_text": raw}

            # ② 原生视频拆解补充
            if len(dissect.get("beats") or []) < 6:
                try:
                    video_dissect = VideoDissector(engine, num_frames=48, max_new_tokens=4096).dissect(
                        video_path
                    )
                    dissect = merge_dissect(dissect, video_dissect)
                except Exception:
                    pass

            # ②b 内容过简时文本模型补全 beat 细节
            if dissect and not dissect.get("error"):
                dissect = expand_dissect_details(dissect)

            # ③ 文本模型深度扩写（Agnes 默认跳过，省 token）
            from src.studio_pipeline.agnes_llm import use_agnes_llm

            enrich_on = os.environ.get("ENRICH_DISSECT", "").strip().lower() in ("1", "true", "yes")
            if dissect and not dissect.get("error") and (enrich_on or not use_agnes_llm()):
                dissect["_narrative"] = enrich_dissect_narrative(dissect)

            dissect["_source_video"] = video_path
            dissect["_num_frames"] = len(keyframes)
        except Exception as e:
            vl_error = str(e)
            dissect = {
                "error": vl_error,
                "hint": "已抽取关键帧，但 AI 内容分析未完成",
                "meta": {"one_line_summary": "待重新解析", "estimated_duration_sec": "?"},
            }

        plan["dissect"] = dissect
        plan["steps"]["parsed"] = True
        plan["parse_note"] = vl_error or "解析完成"
        if dissect and not dissect.get("error"):
            plan["meta"].update(meta_from_dissect(dissect))
        if plan.get("mode") == "A":
            plan = self._ensure_replica_timeline(plan)
            plan["script"] = dissect_to_script(plan.get("dissect") or {})
            plan["steps"]["scripted"] = True
            if not (plan.get("dissect") or {}).get("error"):
                from src.studio_pipeline.frame_extract import extract_reference_assets

                plan["extracted_assets"] = extract_reference_assets(
                    plan.get("keyframes"), self.store.assets_dir(project_id)
                )
                plan["replica_catalog"] = self.assets.build_replica_catalog(
                    plan.get("dissect"),
                    plan.get("keyframes"),
                    self.store.assets_dir(project_id),
                    generate_images=False,
                )
        self.store.save_plan(plan)
        return plan

    def _ensure_replica_timeline(self, plan: dict[str, Any]) -> dict[str, Any]:
        """按原片真实时长校正/重建节拍，避免模板垃圾脚本与残缺成片。"""
        ref = plan.get("reference_video")
        dur = 0.0
        if ref and Path(ref).exists():
            try:
                dur = video_duration_sec(str(ref))
            except Exception:
                dur = 0.0
        if dur < 1:
            try:
                dur = float((plan.get("meta") or {}).get("estimated_duration_sec") or 0)
            except (TypeError, ValueError):
                dur = 0.0
        if dur < 1:
            dur = 30.0
        plan["reference_duration_sec"] = round(dur, 2)
        dissect = normalize_replica_timeline(plan.get("dissect"), dur, plan.get("keyframes"))
        plan["dissect"] = dissect
        meta = plan.setdefault("meta", {})
        meta["estimated_duration_sec"] = int(round(dur))
        if dissect.get("_beats_rebuilt"):
            plan["parse_note"] = (
                (plan.get("parse_note") or "")
                + f"｜时间轴已按原片 {dur:.1f}s 重建为 {len(dissect.get('beats') or [])} 段"
            ).strip("｜")
        return plan

    def generate_script_step(self, project_id: str) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        meta = plan.get("meta", {})
        dissect = plan.get("dissect")
        mode = plan.get("mode", "B")

        if mode == "A":
            plan = self._ensure_replica_timeline(plan)
            script = dissect_to_script(plan.get("dissect") or {})
        else:
            video_ctx = ""
            if dissect and not dissect.get("error"):
                video_ctx = json.dumps(
                    {
                        "hook": dissect.get("hook"),
                        "beats": dissect.get("beats", [])[:8],
                        "script_skeleton": dissect.get("script_skeleton"),
                    },
                    ensure_ascii=False,
                )
            script = generate_script(
                product=meta.get("product", ""),
                topic=meta.get("topic", ""),
                audience=meta.get("audience", "通用用户"),
                style=meta.get("style", "痛点钩子"),
                video_context=video_ctx,
                user_script=meta.get("user_script", ""),
            )
        plan["script"] = script
        plan["steps"]["scripted"] = True
        self.store.save_plan(plan)
        return plan

    def create_project(
        self,
        *,
        mode: str,
        product: str,
        topic: str,
        audience: str,
        style: str,
        video_path: str | None = None,
        user_script: str = "",
        dissect: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """兼容旧调用：创建项目并一步完成拆解+脚本。"""
        plan = self.start_project(
            mode=mode,
            product=product,
            topic=topic,
            audience=audience,
            style=style,
            video_path=video_path,
            user_script=user_script,
        )
        pid = plan["project_id"]
        if video_path and dissect is None:
            plan = self.parse_reference_video(pid)
        elif dissect is not None:
            plan["dissect"] = dissect
            if not dissect.get("error"):
                plan["meta"].update(meta_from_dissect(dissect))
            plan["steps"]["parsed"] = True
            self.store.save_plan(plan)
        plan = self.generate_script_step(pid)
        return plan

    def update_script_from_text(self, project_id: str, script_text: str) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        meta = plan.get("meta", {})
        script = script_from_plaintext(
            script_text,
            product=meta.get("product", ""),
            topic=meta.get("topic", ""),
            audience=meta.get("audience", "通用用户"),
            style=meta.get("style", "痛点钩子"),
        )
        plan["script"] = script
        self.store.save_plan(plan)
        return plan

    def ensure_replica_catalog(self, project_id: str, *, generate_images: bool = True) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        plan["replica_catalog"] = self.assets.build_replica_catalog(
            plan.get("dissect"),
            plan.get("keyframes"),
            self.store.assets_dir(project_id),
            generate_images=generate_images,
        )
        self.store.save_plan(plan)
        return plan

    def suggest_replacement_prompt(
        self, project_id: str, target_slot_id: str, user_hint: str = ""
    ) -> str:
        plan = self.store.load_plan(project_id)
        catalog = plan.get("replica_catalog") or {}
        if not catalog.get("slots"):
            plan = self.ensure_replica_catalog(project_id, generate_images=True)
            catalog = plan.get("replica_catalog") or {}
        return self.assets.suggest_replacement_prompt(catalog, target_slot_id, user_hint=user_hint)

    def draft_replacement_assets(
        self,
        project_id: str,
        target_slot_id: str = "",
        prompt: str = "",
        uploads: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        if not plan.get("replica_catalog"):
            plan = self.ensure_replica_catalog(project_id)
        new_draft = self.assets.draft_replacement_assets(
            project_id,
            plan["replica_catalog"],
            target_slot_id=target_slot_id,
            prompt=prompt,
            uploads=uploads,
        )
        old = plan.get("replacement_drafts") or {}
        merged_slots = dict(old.get("slots") or {})
        merged_slots.update(new_draft.get("slots") or {})
        plan["replacement_drafts"] = {
            **new_draft,
            "slots": merged_slots,
            "images": list(merged_slots.values()),
            "prompts": {
                **(old.get("prompts") or {}),
                target_slot_id or new_draft.get("target_slot_id", ""): prompt,
            },
        }
        plan["steps"]["assets_drafted"] = True
        plan["steps"]["assets_approved"] = False
        self.store.save_plan(plan)
        return plan

    def approve_replacement_assets(self, project_id: str) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        drafts = plan.get("replacement_drafts")
        if not drafts or not (drafts.get("images") or drafts.get("slots")):
            raise ValueError("请先生成替换资产预览")
        plan["assets"] = self.assets.approved_from_drafts(project_id, drafts)
        drafts["approved"] = True
        plan["replacement_drafts"] = drafts
        plan["steps"]["assets_approved"] = True
        plan["steps"]["assets"] = True
        self.store.save_plan(plan)
        return plan

    def build_replica_keyframes(self, project_id: str) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        if not plan.get("steps", {}).get("assets_approved"):
            drafts = plan.get("replacement_drafts") or {}
            if not drafts.get("images"):
                raise ValueError("请先生成替换资产（点「生成我的替换资产」）")
            plan = self.approve_replacement_assets(project_id)
        assets = plan.get("assets") or {}
        if not assets.get("slot_replacements") and not assets.get("character_ref"):
            raise ValueError("缺少替换资产，请重新生成")
        plan = self._ensure_replica_timeline(plan)
        plan["script"] = dissect_to_script(plan.get("dissect") or {})
        plan["steps"]["scripted"] = True
        script = plan.get("script") or {}
        notes = " ".join(
            filter(
                None,
                [
                    str((plan.get("replacement_drafts") or {}).get("prompts", "")),
                    (plan.get("replacement_drafts") or {}).get("char_prompt"),
                    (plan.get("replacement_drafts") or {}).get("product_prompt"),
                ],
            )
        )
        plan["replaced_keyframes"] = self.storyboard.build_replaced_keyframes(
            project_id,
            plan.get("keyframes") or [],
            assets,
            plan.get("dissect"),
            plan.get("replica_catalog"),
            draft_prompts=(plan.get("replacement_drafts") or {}).get("prompts"),
            reference_video=plan.get("reference_video"),
        )
        plan["storyboard"] = self.storyboard.build_storyboard(
            project_id,
            script,
            plan.get("assets", {}),
            "A",
            plan.get("dissect"),
            plan.get("reference_video"),
            plan.get("keyframes"),
            notes,
            catalog=plan.get("replica_catalog"),
            replaced_keyframes=plan.get("replaced_keyframes"),
        )
        plan["steps"]["storyboard"] = True
        self.store.save_plan(plan)
        return plan

    def build_replica_assets(
        self,
        project_id: str,
        uploads: dict[str, str | None] | None = None,
        replacement_notes: str = "",
        *,
        target_slot_id: str = "",
        prompt: str = "",
    ) -> dict[str, Any]:
        """兼容旧调用：草稿 → 确认 → 关键帧 一气呵成。"""
        p = prompt or replacement_notes
        plan = self.draft_replacement_assets(project_id, target_slot_id, p, uploads)
        plan = self.approve_replacement_assets(project_id)
        return self.build_replica_keyframes(project_id)

    def build_assets(
        self,
        project_id: str,
        uploads: dict[str, str | None] | None = None,
    ) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        plan["assets"] = self.assets.build_assets(project_id, plan["script"], uploads)
        plan["steps"]["assets"] = True
        self.store.save_plan(plan)
        return plan

    def build_storyboard(self, project_id: str) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        plan["storyboard"] = self.storyboard.build_storyboard(
            project_id,
            plan["script"],
            plan.get("assets", {}),
            plan.get("mode", "B"),
            plan.get("dissect"),
            plan.get("reference_video"),
            plan.get("keyframes"),
            (plan.get("meta") or {}).get("replacement_notes", ""),
        )
        self.store.save_plan(plan)
        return plan

    def _identity_lock_from_plan(self, plan: dict[str, Any]) -> str:
        """跨分段锁定人物/产品身份，并禁止原角色再出现。"""
        parts: list[str] = []
        forbidden: list[str] = []
        assets = plan.get("assets") or {}
        catalog = plan.get("replica_catalog") or {}
        slot_by_id = {s.get("id"): s for s in (catalog.get("slots") or [])}
        drafts = plan.get("replacement_drafts") or {}

        for sid, path in (assets.get("slot_replacements") or {}).items():
            sm = slot_by_id.get(sid) or {}
            label = sm.get("label") or sid
            old = sm.get("description") or sm.get("appearance") or ""
            new_p = ""
            entry = (drafts.get("slots") or {}).get(sid)
            if isinstance(entry, dict):
                new_p = entry.get("prompt") or ""
            for img in assets.get("images") or []:
                if img.get("slot_id") == sid and img.get("prompt"):
                    new_p = new_p or img.get("prompt")
            if sm.get("type") == "character":
                parts.append(f"USE only replacement for {label}: {new_p or 'approved asset'}"[:140])
                if old:
                    forbidden.append(f"{label} original look ({old[:70]})")
                else:
                    forbidden.append(f"original {label} face/outfit")
            elif label or new_p:
                parts.append(f"{label}: {new_p}"[:120])

        for img in assets.get("images") or []:
            label = img.get("label") or img.get("slot_id") or ""
            prompt = img.get("prompt") or ""
            if label or prompt:
                parts.append(f"{label}: {prompt}"[:120])

        if forbidden:
            parts.append(
                "FORBIDDEN — these original people must NEVER appear: " + "; ".join(forbidden)[:220]
            )
            parts.append("Do not show both original and replacement. One identity only per replaced role.")

        text = "；".join(x for x in parts if x and str(x).strip())
        return text[:450] or "Keep the same main character(s) and product identity across all shots."

    def generate_videos(self, project_id: str, dry_run: bool = False) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        clips_dir = self.store.clips_dir(project_id)
        # 成片默认 Agnes；仅当显式 VIDEO_PROVIDER=minimax/jimeng 才换后端
        os.environ.setdefault("VIDEO_PROVIDER", "agnes")
        mode = plan.get("mode", "B")
        reference = plan.get("reference_video")
        if mode == "A":
            plan = self._ensure_replica_timeline(plan)
            # 分镜若仍是旧的残缺节拍，按校正后的 dissect 重建
            if not plan.get("storyboard") or len(plan.get("storyboard") or []) < max(
                2, len((plan.get("dissect") or {}).get("beats") or []) // 2
            ):
                if plan.get("steps", {}).get("assets_approved") or plan.get("assets"):
                    try:
                        plan = self.build_replica_keyframes(project_id)
                    except Exception:
                        pass

        client = None
        if not dry_run:
            try:
                client = get_video_client()
            except Exception as e:
                plan.setdefault("output", {})["note"] = f"Agnes 视频后端初始化失败：{e}"
                self.store.save_plan(plan)
                return plan

        clip_paths: list[str] = []
        n_ai = 0
        n_fallback = 0
        storyboard = list(plan.get("storyboard") or [])
        replaced = list(plan.get("replaced_keyframes") or [])
        keyframes = list(plan.get("keyframes") or [])
        if mode == "A" and not storyboard and (plan.get("dissect") or {}).get("beats"):
            from src.studio_pipeline.timeline import motion_prompt_from_beat

            storyboard = []
            for b in (plan.get("dissect") or {}).get("beats") or []:
                nb = {
                    "idx": b.get("idx"),
                    "t_start_sec": b.get("t_start_sec"),
                    "t_end_sec": b.get("t_end_sec"),
                    "duration_sec": b.get("duration_sec", 5),
                    "visual": b.get("visual", ""),
                    "spoken": b.get("spoken") or b.get("spoken_or_subtitle", ""),
                    "role": b.get("role", ""),
                    "camera": b.get("camera", ""),
                    "motion_prompt": motion_prompt_from_beat(b),
                    "status": "planned",
                }
                storyboard.append(nb)
            plan["storyboard"] = storyboard

        provider_name = type(client).__name__.replace("VideoClient", "").lower() if client else "none"
        identity_lock = self._identity_lock_from_plan(plan)
        prev_end_frame: str | None = None
        prev_summary = ""

        def _still_for_beat(beat_obj: dict) -> str | None:
            bi = int(beat_obj.get("idx") or 0)
            bt0 = float(beat_obj.get("t_start_sec", (bi - 1) * 5))
            for item in replaced:
                if int(item.get("beat_idx") or 0) == bi and item.get("path") and Path(item["path"]).exists():
                    return str(item["path"])
            if replaced:
                nearest = self.storyboard._nearest_replaced(replaced, bt0)
                if nearest and Path(nearest["path"]).exists():
                    return str(nearest["path"])
            kf = self.storyboard._nearest_keyframe(keyframes, bt0)
            return str(kf) if kf else None

        for i, beat in enumerate(plan.get("storyboard", [])):
            idx = int(beat.get("idx") or 0)
            out = clips_dir / f"beat_{idx:02d}.mp4"
            t0 = float(beat.get("t_start_sec", (idx - 1) * 5))
            t1 = float(beat.get("t_end_sec", t0 + float(beat.get("duration_sec") or 5)))
            beat["t_start_sec"] = round(t0, 2)
            beat["t_end_sec"] = round(t1, 2)
            beat["identity_lock"] = identity_lock
            if prev_summary:
                beat["continuity_from"] = prev_summary

            # 首帧：优先上一段末帧（剧情连续），否则替换关键帧 / 原关键帧
            if prev_end_frame and Path(prev_end_frame).exists():
                beat["first_frame"] = {
                    "path": prev_end_frame,
                    "prompt": beat.get("visual") or "",
                    "role": "first_frame",
                    "source": "prev_clip_end",
                }
            else:
                ff = beat.get("first_frame") if isinstance(beat.get("first_frame"), dict) else {}
                if not (ff or {}).get("path") or not Path(str((ff or {}).get("path"))).exists():
                    frame_path = _still_for_beat(beat)
                    if frame_path:
                        beat["first_frame"] = {
                            "path": frame_path,
                            "prompt": beat.get("visual") or (ff or {}).get("prompt") or "",
                            "role": "first_frame",
                            "source": "auto",
                        }

            # 尾帧：下一段剧情目标静帧 → Agnes keyframes，桥接下一段剧情点
            if i + 1 < len(plan.get("storyboard") or []):
                next_still = _still_for_beat(plan["storyboard"][i + 1])
                if next_still and Path(next_still).exists():
                    # 避免首尾同一张图导致几乎静止
                    first_p = (beat.get("first_frame") or {}).get("path")
                    if not first_p or Path(str(first_p)).resolve() != Path(next_still).resolve():
                        beat["last_frame"] = {
                            "path": next_still,
                            "prompt": plan["storyboard"][i + 1].get("visual") or beat.get("visual") or "",
                            "role": "last_frame",
                            "source": "next_beat_still",
                        }

            used = False
            if client is not None:
                try:
                    result = client.generate_beat_clip(beat, out)
                    beat["clip_path"] = result["path"]
                    beat["task_id"] = result.get("task_id") or result.get("video_id")
                    beat["status"] = "succeeded"
                    beat["error"] = None
                    beat["source"] = result.get("provider") or provider_name or "agnes"
                    clip_paths.append(result["path"])
                    n_ai += 1
                    used = True
                    # 抽出本段末帧，作为下一段首帧，保证人物/场景连续
                    try:
                        from src.studio_pipeline.video_frames import extract_frame_at

                        clip_dur = video_duration_sec(str(out))
                        end_path = clips_dir / f"beat_{idx:02d}_end.jpg"
                        extract_frame_at(str(out), str(end_path), max(0.0, clip_dur - 0.15))
                        if end_path.exists() and end_path.stat().st_size > 500:
                            prev_end_frame = str(end_path.resolve())
                    except Exception:
                        pass
                    prev_summary = " | ".join(
                        x for x in [(beat.get("spoken") or "")[:80], (beat.get("visual") or "")[:100]] if x
                    )
                except Exception as e:  # noqa: BLE001
                    beat["error"] = f"Agnes失败：{e}"
                    beat["status"] = "failed"

            if not used:
                if mode == "A" and reference and Path(reference).exists():
                    try:
                        slice_video_clip(
                            reference,
                            str(out),
                            t0,
                            t1,
                            keep_audio=True,
                            max_duration=None,
                        )
                        beat["clip_path"] = str(out)
                        beat["status"] = "fallback_original"
                        beat["source"] = "original_slice"
                        if not beat.get("error"):
                            beat["error"] = "使用原片切片（未走 Agnes 或 Agnes 失败）"
                        clip_paths.append(str(out))
                        n_fallback += 1
                        used = True
                        try:
                            from src.studio_pipeline.video_frames import extract_frame_at

                            clip_dur = video_duration_sec(str(out))
                            end_path = clips_dir / f"beat_{idx:02d}_end.jpg"
                            extract_frame_at(str(out), str(end_path), max(0.0, clip_dur - 0.15))
                            if end_path.exists():
                                prev_end_frame = str(end_path.resolve())
                        except Exception:
                            pass
                        prev_summary = f"原片切片 {t0:.1f}-{t1:.1f}s"
                    except Exception as e2:  # noqa: BLE001
                        beat["status"] = "failed"
                        beat["error"] = f"{beat.get('error') or ''}｜原片切片失败：{e2}".strip("｜")
                elif not used:
                    beat["status"] = beat.get("status") or "failed"
                    beat["error"] = beat.get("error") or "未配置 Agnes，且无原片可切"

        if clip_paths:
            master = self.store.output_dir(project_id) / "master.mp4"
            concat_clips(clip_paths, master)
            try:
                web = ensure_web_mp4(master, self.store.output_dir(project_id) / "master_web.mp4")
                plan["output"]["master_path"] = str(web.resolve())
                plan["output"]["master_raw"] = str(master.resolve())
            except Exception:
                plan["output"]["master_path"] = str(master.resolve())
            try:
                out_dur = video_duration_sec(plan["output"]["master_path"])
            except Exception:
                out_dur = 0.0
            ref_dur = float(plan.get("reference_duration_sec") or 0)
            plan["output"]["duration_sec"] = round(out_dur, 2)
            plan["output"]["ai_clips"] = n_ai
            plan["output"]["fallback_clips"] = n_fallback
            note = (
                f"成片 {out_dur:.1f}s｜Agnes AI {n_ai} 段 + 原片补齐 {n_fallback} 段"
                f"｜{plan['output']['master_path']}"
            )
            if mode == "A" and ref_dur > 1 and out_dur + 1.5 < ref_dur * 0.85:
                note = f"⚠ 成片偏短（{out_dur:.1f}s / 原片 {ref_dur:.1f}s）｜{note}"
            plan["output"]["note"] = note
        else:
            errs = [str(b.get("error")) for b in plan.get("storyboard", []) if b.get("error")]
            plan["output"]["note"] = "未生成任何片段（请检查 Agnes 密钥与分镜首帧）" + (
                f"：{errs[0]}" if errs else ""
            )
            plan["output"]["master_path"] = None

        plan["clips"] = [
            {
                "idx": b.get("idx"),
                "path": b.get("clip_path"),
                "status": b.get("status"),
                "source": b.get("source"),
                "error": b.get("error"),
            }
            for b in plan.get("storyboard", [])
        ]
        plan["output"]["qc"] = run_qc(plan)
        self.store.save_plan(plan)
        return plan

    def rerun_beat(self, project_id: str, beat_idx: int) -> dict[str, Any]:
        plan = self.store.load_plan(project_id)
        try:
            client = get_video_client()
        except Exception as e:
            raise ValueError(f"未配置可用视频 API：{e}") from e

        clips_dir = self.store.clips_dir(project_id)
        reference = plan.get("reference_video")
        for beat in plan.get("storyboard", []):
            if beat.get("idx") != beat_idx:
                continue
            out = clips_dir / f"beat_{beat_idx:02d}.mp4"
            try:
                result = client.generate_beat_clip(beat, out)
                beat["clip_path"] = result["path"]
                beat["task_id"] = result.get("task_id") or result.get("video_id")
                beat["status"] = "succeeded"
                beat["source"] = result.get("provider") or "agnes"
                beat["error"] = None
            except Exception as e:
                if plan.get("mode") == "A" and reference and Path(reference).exists():
                    t0 = float(beat.get("t_start_sec", (beat_idx - 1) * 5))
                    t1 = float(beat.get("t_end_sec", t0 + float(beat.get("duration_sec") or 5)))
                    slice_video_clip(reference, str(out), t0, t1, keep_audio=True, max_duration=None)
                    beat["clip_path"] = str(out)
                    beat["status"] = "fallback_original"
                    beat["source"] = "original_slice"
                    beat["error"] = str(e)
                else:
                    raise
            break

        # 按 idx 顺序拼接全部已有片段，避免漏段
        ordered = sorted(
            [b for b in plan["storyboard"] if b.get("clip_path")],
            key=lambda b: int(b.get("idx") or 0),
        )
        succeeded = [b["clip_path"] for b in ordered]
        if succeeded:
            master = self.store.output_dir(project_id) / "master.mp4"
            concat_clips(succeeded, master)
            try:
                web = ensure_web_mp4(master, self.store.output_dir(project_id) / "master_web.mp4")
                plan["output"]["master_path"] = str(web.resolve())
            except Exception:
                plan["output"]["master_path"] = str(master.resolve())
        plan["output"]["qc"] = run_qc(plan)
        self.store.save_plan(plan)
        return plan
    def get_plan_json(self, project_id: str) -> str:
        return pretty_json(self.store.load_plan(project_id))

    def list_frame_gallery(self, project_id: str) -> list[str]:
        plan = self.store.load_plan(project_id)
        paths: list[str] = []
        for img in (plan.get("assets") or {}).get("images", []):
            if img.get("path"):
                paths.append(img["path"])
        for beat in plan.get("storyboard", []):
            if beat.get("first_frame", {}).get("path"):
                paths.append(beat["first_frame"]["path"])
            if beat.get("last_frame", {}).get("path"):
                paths.append(beat["last_frame"]["path"])
        return [p for p in paths if Path(p).exists()]
