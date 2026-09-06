from __future__ import annotations

import os
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size: int = 22):
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _has_minimax() -> bool:
    return bool(os.environ.get("MINIMAX_API_KEY", "").strip())


CHAR_VIEW_PROMPTS: dict[str, str] = {
    "front": "正对镜头，正面半身肖像，直视镜头，肩膀对称",
    "three_quarter": "四分之三侧面，脸转向一侧，露出侧脸与肩部线条，非正面",
    "side": "完全侧面轮廓，鼻子朝向画面边缘，纯侧脸半身",
}


def generate_character_view(
    hint: str,
    view: str,
    out_path: str | Path,
    *,
    subject_ref: str | None = None,
    fallback_ref: str | None = None,
) -> tuple[Path, str]:
    """按视角生成人物白底图；侧面生成时用正面图作 subject_ref 保持同一人。"""
    angle = CHAR_VIEW_PROMPTS.get(view, CHAR_VIEW_PROMPTS["front"])
    prompt = f"纯白背景人物摄影，{hint}，{angle}，柔和棚拍光，高清，无文字水印"
    label = {"front": "正面", "three_quarter": "侧面", "side": "纯侧"}.get(view, view)
    return generate_asset_image(
        prompt,
        out_path,
        aspect_ratio="9:16",
        subject_ref=subject_ref,
        fallback_ref=fallback_ref or subject_ref,
        tag=label,
    )


def generate_replacement_character(
    user_prompt: str,
    out_path: str | Path,
    *,
    slot_label: str = "",
    upload_ref: str | None = None,
) -> tuple[Path, str]:
    """按用户提示词生成「替换人物」白底资产。

    重要：换人时不要把原片人物当 subject_ref，否则 AI 会锁住原脸，等于没换。
    - 有上传图 → 以上传图为参考生成
    - 无上传 → 纯文生图（Agnes），完全按提示词新人设
    """
    hint = (user_prompt or "").strip()
    if not hint:
        raise ValueError("请填写替换提示词，例如：男生，帅气 / 年轻女博主长发白T")
    prompt = (
        f"纯白背景人物设定摄影，{hint}，"
        f"半身或全身站立肖像，直视镜头，柔和棚拍光，高清，无文字水印，无场景杂物。"
        f"这是短视频换人素材，用于替换原片角色「{slot_label or '出镜人物'}」。"
    )
    path, source = generate_asset_image(
        prompt,
        out_path,
        aspect_ratio="9:16",
        subject_ref=upload_ref,  # 仅上传图可作参考；原片裁剪禁止传入
        fallback_ref=None,
        tag="替换人物",
        allow_fallback=False,
    )
    if source == "fallback":
        raise RuntimeError("Agnes/MiniMax 生图失败，未生成替换人物（拒绝用原片糊弄）")
    return path, source


def generate_replacement_product(
    user_prompt: str,
    out_path: str | Path,
    *,
    slot_label: str = "",
    upload_ref: str | None = None,
) -> tuple[Path, str]:
    hint = (user_prompt or "").strip()
    if not hint:
        raise ValueError("请填写产品替换提示词，例如：绿色泵头洗洁精瓶")
    prompt = (
        f"纯白背景商品摄影，{hint}，居中摆放，柔和棚拍光，高清产品图，无文字水印。"
        f"用于替换原片产品「{slot_label or '主推产品'}」。"
    )
    path, source = generate_asset_image(
        prompt,
        out_path,
        aspect_ratio="1:1",
        subject_ref=upload_ref,
        fallback_ref=None,
        tag="替换产品",
        allow_fallback=False,
    )
    if source == "fallback":
        raise RuntimeError("Agnes/MiniMax 生图失败，未生成替换产品")
    return path, source


def generate_product_shot(
    hint: str,
    out_path: str | Path,
    *,
    fallback_ref: str | None = None,
) -> tuple[Path, str]:
    prompt = f"纯白背景商品摄影，{hint}，居中摆放，柔和棚拍光，高清产品图，无文字水印"
    return generate_asset_image(
        prompt,
        out_path,
        aspect_ratio="1:1",
        subject_ref=None,
        fallback_ref=fallback_ref,
        tag="产品",
    )


def compose_white_bg(ref_image: str | None, out_path: str | Path, *, size: tuple[int, int] = (768, 1024)) -> Path:
    """无 API 时：把裁剪图居中贴到白底（比裸裁剪更像资产图）。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    w, h = size
    canvas = Image.new("RGB", (w, h), (255, 255, 255))
    if ref_image and Path(ref_image).exists():
        try:
            ref = Image.open(ref_image).convert("RGB")
            ref.thumbnail((int(w * 0.88), int(h * 0.88)), Image.Resampling.LANCZOS)
            x = (w - ref.width) // 2
            y = (h - ref.height) // 2
            canvas.paste(ref, (x, y))
        except Exception:
            pass
    canvas.save(out, quality=92)
    return out


def generate_asset_image(
    prompt: str,
    out_path: str | Path,
    *,
    aspect_ratio: str = "9:16",
    subject_ref: str | None = None,
    extra_refs: list[str] | None = None,
    fallback_ref: str | None = None,
    tag: str = "",
    allow_fallback: bool = True,
) -> tuple[Path, str]:
    """生成资产图。优先 Agnes，其次 MiniMax；allow_fallback=False 时失败直接抛错。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    # 1) Agnes 图生图 / 文生图
    if os.environ.get("AGNES_API_KEY", "").replace("\r", "").strip():
        try:
            from src.studio_pipeline.agnes_client import AgnesImageClient

            AgnesImageClient().generate_and_save(
                prompt,
                out,
                aspect_ratio=aspect_ratio,
                subject_ref=subject_ref if (subject_ref and Path(subject_ref).exists()) else None,
                extra_refs=[p for p in (extra_refs or []) if p and Path(p).exists()],
            )
            if out.exists() and out.stat().st_size > 2000:
                return out, "agnes"
            errors.append("Agnes 返回空文件")
        except Exception as e:
            errors.append(f"Agnes: {e}")

    # 2) MiniMax 备用
    if _has_minimax():
        try:
            from src.studio_pipeline.minimax_client import MiniMaxImageClient

            MiniMaxImageClient().generate_and_save(
                prompt,
                out,
                aspect_ratio=aspect_ratio,
                subject_ref=subject_ref if (subject_ref and Path(subject_ref).exists()) else None,
            )
            if out.exists() and out.stat().st_size > 2000:
                return out, "minimax"
            errors.append("MiniMax 返回空文件")
        except Exception as e:
            errors.append(f"MiniMax: {e}")

    if not allow_fallback:
        raise RuntimeError("AI 生图失败：" + "；".join(errors) or "无可用密钥")

    # 3) 本地白底兜底（禁止对 Path 调 ImageDraw）
    compose_white_bg(fallback_ref or subject_ref, out)
    if tag and out.exists():
        try:
            img = Image.open(out).convert("RGB")
            draw = ImageDraw.Draw(img)
            draw.rectangle([(12, 12), (img.width - 12, 48)], fill=(40, 40, 40))
            draw.text((20, 18), tag[:28], fill=(255, 220, 120), font=_font(16))
            img.save(out, quality=92)
        except Exception:
            pass
    return out, "fallback"


def _base_canvas(tag: str = "", ratio: tuple[int, int] = (720, 1280)) -> Image.Image:
    w, h = ratio
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(30 + 40 * t)
        g = int(35 + 50 * t)
        b = int(60 + 80 * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    if tag:
        draw.rectangle([(20, 20), (w - 20, 90)], fill=(0, 0, 0, 128))
        draw.text((36, 36), tag, fill=(255, 220, 120), font=_font(28))
    return img


def _paste_ref(canvas: Image.Image, ref_image: str | None, box: tuple[int, int, int, int]):
    if not ref_image or not Path(ref_image).exists():
        return
    try:
        ref = Image.open(ref_image).convert("RGB")
        ref.thumbnail((box[2] - box[0], box[3] - box[1]))
        x = box[0] + (box[2] - box[0] - ref.width) // 2
        y = box[1] + (box[3] - box[1] - ref.height) // 2
        canvas.paste(ref, (x, y))
    except Exception:
        pass


def _paste_scaled(canvas: Image.Image, ref_image: str | None, box: tuple[int, int, int, int]):
    if not ref_image or not Path(ref_image).exists():
        return
    try:
        ref = Image.open(ref_image).convert("RGBA")
        bw, bh = box[2] - box[0], box[3] - box[1]
        ref.thumbnail((bw, bh), Image.Resampling.LANCZOS)
        x = box[0] + (bw - ref.width) // 2
        y = box[1] + (bh - ref.height) // 2
        canvas.paste(ref, (x, y), ref if ref.mode == "RGBA" else None)
    except Exception:
        pass


def _feather_mask(size: tuple[int, int], margin: float = 0.08) -> Image.Image:
    from PIL import ImageFilter

    w, h = size
    m = max(3, int(min(w, h) * margin))
    fade = Image.new("L", (w, h), 0)
    inner = Image.new("L", (max(1, w - 2 * m), max(1, h - 2 * m)), 255)
    fade.paste(inner, (m, m))
    return fade.filter(ImageFilter.GaussianBlur(radius=max(3, m // 2)))


def _knockout_white(ref: Image.Image, threshold: int = 245) -> Image.Image:
    """把白底资产抠成透明，避免整块白底贴图。"""
    rgba = ref.convert("RGBA")
    pixels = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if r >= threshold and g >= threshold and b >= threshold:
                pixels[x, y] = (r, g, b, 0)
            elif r > 230 and g > 230 and b > 230:
                # 近白半透明
                fade = int(255 * (threshold - min(r, g, b)) / max(1, threshold - 230))
                pixels[x, y] = (r, g, b, max(0, min(255, fade)))
    return rgba


def _paste_cover_region(
    canvas: Image.Image,
    ref_image: str | None,
    box: tuple[int, int, int, int],
    *,
    feather: bool = True,
    knockout_white: bool = True,
    fit: str = "cover",
) -> None:
    """把替换图贴进目标区域：去白底 + 等比铺满 + 边缘羽化。"""
    if not ref_image or not Path(ref_image).exists():
        return
    try:
        ref = Image.open(ref_image).convert("RGBA")
        if knockout_white:
            ref = _knockout_white(ref)
        x0, y0, x1, y1 = box
        bw, bh = max(1, x1 - x0), max(1, y1 - y0)
        if fit == "contain":
            ref.thumbnail((bw, bh), Image.Resampling.LANCZOS)
            px = x0 + (bw - ref.width) // 2
            py = y0 + (bh - ref.height) // 2
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            layer.paste(ref, (px, py), ref)
            if feather:
                # 只在目标框内羽化
                mask = Image.new("L", canvas.size, 0)
                local = _feather_mask(ref.size, margin=0.1)
                mask.paste(local, (px, py))
                canvas.alpha_composite(Image.composite(layer, Image.new("RGBA", canvas.size, (0, 0, 0, 0)), mask))
            else:
                canvas.alpha_composite(layer)
            return

        # cover：等比放大后裁切铺满
        scale = max(bw / max(1, ref.width), bh / max(1, ref.height))
        nw, nh = max(1, int(ref.width * scale)), max(1, int(ref.height * scale))
        ref = ref.resize((nw, nh), Image.Resampling.LANCZOS)
        left = max(0, (nw - bw) // 2)
        top = max(0, (nh - bh) // 2)
        ref = ref.crop((left, top, left + bw, top + bh))
        mask = _feather_mask((bw, bh)) if feather else ref.split()[-1]
        if feather:
            alpha = ref.split()[-1]
            mask = Image.composite(mask, Image.new("L", (bw, bh), 0), alpha)
            ref.putalpha(mask)
        canvas.paste(ref, (x0, y0), ref)
    except Exception:
        pass


def compose_replacement_frame(
    ref_path: str,
    out_path: str | Path,
    *,
    char_ref: str | None = None,
    product_ref: str | None = None,
    char_box: tuple[int, int, int, int] | None = None,
    product_box: tuple[int, int, int, int] | None = None,
    tag: str = "",
) -> Path:
    """在原关键帧上做区域替换：始终以原图为底，绝不另画一张。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    base = Image.open(ref_path).convert("RGBA")
    w, h = base.size
    if char_ref:
        # 默认只换上半身/人脸区，避免整块盖住手持产品与下半身场景
        box = char_box or (int(w * 0.12), int(h * 0.04), int(w * 0.88), int(h * 0.62))
        _paste_cover_region(base, char_ref, box, knockout_white=True, fit="contain")
    if product_ref:
        # 产品贴在前景手持/台面区，contain 保持瓶身比例
        box = product_box or (int(w * 0.48), int(h * 0.38), int(w * 0.96), int(h * 0.90))
        _paste_cover_region(base, product_ref, box, knockout_white=True, fit="contain")
    composed = base.convert("RGB")
    if tag:
        draw = ImageDraw.Draw(composed)
        draw.rectangle([(12, h - 52), (w - 12, h - 12)], fill=(0, 0, 0))
        draw.text((20, h - 44), tag[:36], fill=(255, 220, 120), font=_font(18))
    composed.save(out_path, quality=92)
    return out_path


def generate_replacement_keyframe(
    *,
    visual: str = "",
    role: str = "",
    spoken: str = "",
    char_ref: str | None = None,
    char_prompt: str = "",
    product_prompt: str = "",
    out_path: str | Path,
    source_frame: str | None = None,
    char_box: tuple[int, int, int, int] | None = None,
    product_ref: str | None = None,
    product_box: tuple[int, int, int, int] | None = None,
    tag: str = "",
    force_ai: bool = False,
    remove_label: str = "",
    remove_appearance: str = "",
) -> tuple[Path, str]:
    """按所选替换资产 AI 生成关键帧：在原场景里换人，禁止原角色与新人并存。"""
    import shutil

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not source_frame or not Path(source_frame).exists():
        raise ValueError("缺少原片关键帧")

    if not char_ref and not product_ref and not force_ai:
        shutil.copy2(source_frame, out_path)
        return out_path, "unchanged"

    mode = os.environ.get("REPLICA_KEYFRAME_MODE", "ai").lower()

    if mode == "compose" and (char_ref or product_ref):
        compose_replacement_frame(
            source_frame,
            out_path,
            char_ref=char_ref,
            product_ref=product_ref,
            char_box=char_box,
            product_box=product_box,
            tag=tag,
        )
        return out_path, "compose"

    scene = visual or ""
    if not scene or any(k in scene for k in ("请根据", "请在", "画面要素", "字幕要素", "人物动作", "沿用原片", "复刻原片")):
        scene = "保持与原片该帧相同的机位、景别、背景陈设与人物站位"
    spoken_bit = ""
    if spoken and not any(k in spoken for k in ("请在", "字幕要点", "口播或", "沿用原片")):
        spoken_bit = f"画面字幕语义：{spoken[:40]}。"

    who = remove_label or "原片目标人物"
    look = remove_appearance or "原片中被替换的那个人"
    new_look = char_prompt or "参考图中的新人"

    bits = [
        "这是原片关键帧的人物替换编辑，不是新开一条视频。",
        scene,
        spoken_bit,
        "高清竖屏 9:16，真实摄影，保持原场景与构图。",
        "画面若有字幕必须是简体中文；禁止英文字幕、外文乱码。",
    ]
    if char_ref:
        bits.extend(
            [
                f"必须把原片中的「{who}」（外貌：{look[:80]}）彻底替换为新人「{new_look[:100]}」。",
                "原片被替换的那个人不能再出现；禁止原脸+新脸同时出现；禁止复制出两个相同的人。",
                "若画面有其他未替换角色，可保留，但人数不得无故增加。",
                "图1=原片场景（要改的画面）；图2=新人身份参考（白底人设）。按图2换掉图1里的目标人物。",
            ]
        )
    elif force_ai:
        bits.append("严格复刻原片该帧构图与人物，仅清晰化，不要换人换景。")
    if product_ref:
        bits.append(
            f"产品外观按产品参考/描述：{product_prompt or '种草产品'}，保留原片中产品位置与手持关系。"
        )
    prompt = "。".join(b for b in bits if b)

    if _has_minimax() or os.environ.get("AGNES_API_KEY", "").strip():
        try:
            if char_ref and Path(char_ref).exists():
                # 场景作主图，新人作身份参考 —— 避免只生成新人自拍而原角色仍留在别的帧
                path, src_name = generate_asset_image(
                    prompt,
                    out_path,
                    aspect_ratio="9:16",
                    subject_ref=source_frame,
                    extra_refs=[char_ref],
                    fallback_ref=None,
                    allow_fallback=False,
                )
                return path, src_name
            path, src_name = generate_asset_image(
                prompt,
                out_path,
                aspect_ratio="9:16",
                subject_ref=source_frame if force_ai else None,
                fallback_ref=source_frame,
            )
            return path, src_name
        except Exception:
            pass

    shutil.copy2(source_frame, out_path)
    return out_path, "unchanged"


def box_norm_to_pixels(box_norm: tuple[float, float, float, float], w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box_norm
    return int(w * x0), int(h * y0), int(w * x1), int(h * y1)


def render_storyboard_frame(
    prompt: str,
    out_path: str | Path,
    *,
    tag: str = "",
    ref_image: str | None = None,
) -> Path:
    out_path = Path(out_path)
    p, _ = generate_asset_image(
        f"纯白背景，{prompt}，高清商品/场景摄影",
        out_path,
        aspect_ratio="9:16",
        subject_ref=None,
        fallback_ref=ref_image,
        tag=tag or "场景",
    )
    return p


def render_character_angle(
    prompt: str,
    out_path: str | Path,
    *,
    label: str = "",
    ref_image: str | None = None,
    view: str = "front",
) -> Path:
    out_path = Path(out_path)
    p, _ = generate_character_view(
        prompt,
        view,
        out_path,
        subject_ref=ref_image if view != "front" else ref_image,
        fallback_ref=ref_image,
    )
    return p
