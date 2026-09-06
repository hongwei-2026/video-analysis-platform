"""Agnes AI 视频生成（agnes-video-v2.0）。"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE = "https://apihub.agnes-ai.com"


def _env(name: str, default: str = "") -> str:
    """读取环境变量并去掉 Windows CRLF 残留的 \\r。"""
    return (os.environ.get(name, default) or default).replace("\r", "").replace("\n", "").strip()


POLL_INTERVAL = float(_env("AGNES_POLL_INTERVAL", "8") or "8")
POLL_TIMEOUT = int(_env("AGNES_POLL_TIMEOUT", "900") or "900")
MIN_CREATE_INTERVAL = float(_env("AGNES_MIN_CREATE_INTERVAL", "61") or "61")
DEFAULT_MODEL = _env("AGNES_VIDEO_MODEL", "agnes-video-v2.0") or "agnes-video-v2.0"

_last_create_ts = 0.0


def _frames_for_duration(duration_sec: float, fps: int = 24) -> int:
    """num_frames 须 ≤441 且为 8n+1。"""
    target = int(round(max(3.0, float(duration_sec)) * fps))
    n = max(10, round((target - 1) / 8))  # 至少约 81 帧 (~3.4s)
    frames = 8 * n + 1
    return int(min(441, frames))


class AgnesVideoClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = (api_key or _env("AGNES_API_KEY")).strip()
        if not self.api_key:
            raise ValueError("未配置 AGNES_API_KEY")
        self.base_url = (base_url or _env("AGNES_BASE_URL", DEFAULT_BASE)).strip().rstrip("/")
        self.model = _env("AGNES_VIDEO_MODEL", "agnes-video-v2.0") or "agnes-video-v2.0"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _wait_rate_limit(self) -> None:
        global _last_create_ts
        gap = MIN_CREATE_INTERVAL - (time.time() - _last_create_ts)
        if gap > 0:
            time.sleep(gap)

    @staticmethod
    def _image_data_uri(path: str) -> str:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        suffix = p.suffix.lower().lstrip(".")
        mime = "png" if suffix == "png" else "jpeg"
        return f"data:image/{mime};base64,{data}"

    def create_task(
        self,
        *,
        prompt: str,
        duration: int = 5,
        ratio: str = "9:16",
        resolution: str = "720P",
        first_frame: str | None = None,
        last_frame: str | None = None,
        reference_video: str | None = None,
        reference_image: str | None = None,
    ) -> dict[str, Any]:
        """创建异步视频任务，返回含 video_id/task_id 的响应。"""
        del resolution, reference_video  # Agnes v2.0 用 width/height/num_frames
        fps = 24
        frames = _frames_for_duration(duration, fps)
        if ratio in ("9:16", "9/16"):
            width, height = 768, 1152
        elif ratio in ("1:1", "1/1"):
            width, height = 768, 768
        else:
            width, height = 1152, 768

        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": (prompt or "natural cinematic motion, vertical short video")[:1500],
            "width": width,
            "height": height,
            "num_frames": frames,
            "frame_rate": fps,
            "negative_prompt": (
                "blurry, low quality, distorted face, watermark, text artifacts, "
                "English subtitles, Korean text, Japanese text, Latin alphabet captions, "
                "mixed-language speech, gibberish text, duplicate people, original actor remaining"
            ),
        }

        img_path = first_frame or reference_image
        if last_frame and img_path and Path(last_frame).exists() and Path(img_path).exists():
            payload["extra_body"] = {
                "image": [self._image_data_uri(img_path), self._image_data_uri(last_frame)],
                "mode": "keyframes",
            }
        elif img_path and Path(img_path).exists():
            payload["image"] = self._image_data_uri(img_path)
            payload["mode"] = "ti2vid"

        self._wait_rate_limit()
        global _last_create_ts
        with httpx.Client(timeout=180) as client:
            resp = client.post(f"{self.base_url}/v1/videos", headers=self._headers(), json=payload)
            if resp.status_code == 429:
                # 再等一轮限流后重试一次
                time.sleep(MIN_CREATE_INTERVAL)
                resp = client.post(f"{self.base_url}/v1/videos", headers=self._headers(), json=payload)
            if resp.is_error:
                raise RuntimeError(f"Agnes 创建失败 {resp.status_code}: {resp.text[:400]}")
            data = resp.json()
        _last_create_ts = time.time()
        if not data.get("video_id") and not data.get("task_id") and not data.get("id"):
            raise RuntimeError(f"Agnes 未返回 video_id: {data}")
        return data

    def query_video(self, video_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=60) as client:
            resp = client.get(
                f"{self.base_url}/agnesapi",
                headers=self._headers(),
                params={"video_id": video_id, "model_name": self.model},
            )
            if resp.is_error:
                raise RuntimeError(f"Agnes 查询失败 {resp.status_code}: {resp.text[:300]}")
            return resp.json()

    def wait_video(self, video_id: str) -> dict[str, Any]:
        deadline = time.time() + POLL_TIMEOUT
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.query_video(video_id)
            status = str(last.get("status") or "").lower()
            if status in ("completed", "succeeded", "success"):
                return last
            if status in ("failed", "error", "cancelled"):
                err = last.get("error") or last
                raise RuntimeError(f"Agnes 任务失败: {err}")
            time.sleep(POLL_INTERVAL)
        raise TimeoutError(f"Agnes 超时 video_id={video_id} last={last.get('status')}")

    @staticmethod
    def _extract_url(task: dict[str, Any]) -> str:
        url = task.get("url") or (task.get("metadata") or {}).get("url") or task.get("remixed_from_video_id")
        if isinstance(url, str) and url.startswith("http"):
            return url
        raise RuntimeError(f"Agnes 完成但无视频 URL: {list(task.keys())}")

    def download_video(self, url: str, out_path: str | Path) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            out.write_bytes(resp.content)
        return out

    def ping(self) -> dict[str, Any]:
        created = self.create_task(prompt="竖屏测试：一杯咖啡放在木桌上，柔和日光", duration=4, ratio="9:16")
        return {
            "provider": "agnes",
            "base_url": self.base_url,
            "model": self.model,
            "video_id": created.get("video_id"),
            "task_id": created.get("task_id") or created.get("id"),
            "status": created.get("status", "queued"),
        }

    def generate_beat_clip(self, beat: dict[str, Any], out_path: str | Path) -> dict[str, Any]:
        """按分镜生成一段视频；强调同一剧情连续，强制中文口播/字幕。"""
        identity = (beat.get("identity_lock") or "").strip()
        continuity = (beat.get("continuity_from") or "").strip()
        visual = (
            beat.get("visual")
            or (beat.get("first_frame") or {}).get("prompt")
            or ""
        ).strip()
        spoken = (beat.get("spoken") or beat.get("spoken_or_subtitle") or "").strip()
        motion = (beat.get("motion_prompt") or "").strip()
        role = (beat.get("role") or "").strip()

        parts: list[str] = [
            "竖屏 9:16 中文短视频带货续拍（不是新开一条片）。",
            "语言硬性要求：人物说话必须是中文普通话；画面字幕必须是简体中文。",
            "禁止英文、日文、韩文、拼音字幕；禁止中英混杂口播；禁止乱码或无意义字母。",
            "若有口型/说话，整段只用同一种中文，不要中途换语言。",
            "保持同一批已替换人物、服装、场景光线连续；禁止重新自我介绍。",
            "若已换人：原角色绝不能再出现，禁止原角色与替换角色同时出镜。",
            "动作自然连贯，不要突变。",
        ]
        if identity:
            parts.append(f"身份锁定：{identity[:260]}")
        if continuity:
            parts.append(f"上一段结尾：{continuity[:200]}。请从该时刻继续，不要另起炉灶。")
        if role:
            parts.append(f"本段剧情角色：{role}")
        if visual:
            parts.append(f"本段画面必须呈现：{visual[:300]}")
        if spoken and "沿用原片" not in spoken:
            parts.append(f"本段中文口播/字幕原文（必须按中文呈现，勿翻译成外文）：「{spoken[:260]}」")
        else:
            parts.append("本段若出现字幕，仅用简体中文短句，与画面动作一致。")
        if motion:
            parts.append(f"运镜：{motion[:220]}")
        else:
            parts.append("运镜：保持原片节奏，轻微自然移动，不要甩镜重置。")

        prompt = "\n".join(parts)[:1500]
        duration = int(beat.get("duration_sec", 5))
        duration = int(max(4, min(15, duration)))

        first = None
        last = None
        if beat.get("first_frame") and isinstance(beat["first_frame"], dict):
            first = beat["first_frame"].get("path")
        if beat.get("last_frame") and isinstance(beat["last_frame"], dict):
            last = beat["last_frame"].get("path")

        created = self.create_task(
            prompt=prompt,
            duration=duration,
            ratio="9:16",
            first_frame=first,
            last_frame=last,
        )
        video_id = created.get("video_id") or created.get("id")
        task = self.wait_video(str(video_id))
        url = self._extract_url(task)
        self.download_video(url, out_path)
        return {
            "task_id": created.get("task_id") or created.get("id"),
            "video_id": video_id,
            "path": str(out_path),
            "status": "succeeded",
            "provider": "agnes",
            "base_url": self.base_url,
            "url": url,
        }


def get_video_client():
    """按 VIDEO_PROVIDER / 可用密钥选择视频后端。默认优先 Agnes。"""
    provider = _env("VIDEO_PROVIDER").lower() or "agnes"
    agnes_key = _env("AGNES_API_KEY")
    mm_key = _env("MINIMAX_API_KEY")

    if provider in ("agnes", "agens", ""):
        if not agnes_key:
            raise ValueError("VIDEO_PROVIDER=agnes 但未配置 AGNES_API_KEY")
        return AgnesVideoClient(agnes_key)
    if provider in ("minimax", "hailuo"):
        from src.studio_pipeline.minimax_client import MiniMaxVideoClient

        return MiniMaxVideoClient(mm_key)
    if provider in ("jimeng", "volc", "volcengine"):
        from src.studio_pipeline.jimeng_client import JimengVideoClient, _has_jimeng_keys

        if not _has_jimeng_keys():
            raise ValueError("VIDEO_PROVIDER=jimeng 但未配置 VOLC_ACCESSKEY/VOLC_SECRETKEY")
        return JimengVideoClient()

    # 自动：有 Agnes 优先
    if agnes_key:
        return AgnesVideoClient(agnes_key)
    if mm_key:
        from src.studio_pipeline.minimax_client import MiniMaxVideoClient

        return MiniMaxVideoClient(mm_key)
    raise ValueError("未配置 AGNES_API_KEY 或 MINIMAX_API_KEY")


def has_video_api() -> bool:
    from src.studio_pipeline.jimeng_client import _has_jimeng_keys

    return bool(_env("AGNES_API_KEY") or _env("MINIMAX_API_KEY") or _has_jimeng_keys())


class AgnesImageClient:
    """Agnes 文生图 / 图生图（agnes-image-2.1-flash）。"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = (api_key or _env("AGNES_API_KEY")).strip()
        if not self.api_key:
            raise ValueError("未配置 AGNES_API_KEY")
        self.base_url = (base_url or _env("AGNES_BASE_URL", DEFAULT_BASE)).strip().rstrip("/")
        self.model = _env("AGNES_IMAGE_MODEL", "agnes-image-2.1-flash") or "agnes-image-2.1-flash"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _data_uri(path: str | Path) -> str:
        p = Path(path)
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        suffix = p.suffix.lower().lstrip(".")
        mime = "png" if suffix == "png" else "jpeg"
        return f"data:image/{mime};base64,{data}"

    @staticmethod
    def _size_for_ratio(aspect_ratio: str) -> str:
        ar = (aspect_ratio or "9:16").replace("/", ":")
        if ar in ("9:16", "3:4"):
            return "768x1024"
        if ar in ("1:1",):
            return "1024x1024"
        return "1024x768"

    def generate_image(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "9:16",
        subject_ref: str | None = None,
        extra_refs: list[str] | None = None,
        size: str | None = None,
    ) -> bytes:
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": (prompt or "high quality product photo")[:1500],
            "size": size or self._size_for_ratio(aspect_ratio),
        }
        extra: dict[str, Any] = {"response_format": "b64_json"}
        images: list[str] = []
        if subject_ref and Path(subject_ref).exists():
            images.append(self._data_uri(subject_ref))
        for ref in extra_refs or []:
            if ref and Path(ref).exists():
                images.append(self._data_uri(ref))
        if images:
            extra["image"] = images
        else:
            payload["return_base64"] = True
            extra["response_format"] = "b64_json"
        payload["extra_body"] = extra

        with httpx.Client(timeout=180) as client:
            resp = client.post(
                f"{self.base_url}/v1/images/generations",
                headers=self._headers(),
                json=payload,
            )
            if resp.is_error:
                # 兼容：image 放顶层再试一次
                if images and resp.status_code in (400, 422):
                    payload2 = {
                        "model": self.model,
                        "prompt": payload["prompt"],
                        "size": payload["size"],
                        "image": images,
                        "extra_body": {"response_format": "b64_json"},
                    }
                    resp = client.post(
                        f"{self.base_url}/v1/images/generations",
                        headers=self._headers(),
                        json=payload2,
                    )
                if resp.is_error:
                    raise RuntimeError(f"Agnes 生图失败 {resp.status_code}: {resp.text[:400]}")
            data = resp.json()

        items = data.get("data") or data.get("images") or []
        if not items:
            raise RuntimeError(f"Agnes 生图无结果: {str(data)[:300]}")
        item = items[0] if isinstance(items[0], dict) else {"b64_json": items[0]}
        b64 = item.get("b64_json") or item.get("b64") or item.get("base64")
        if b64:
            if "," in str(b64) and str(b64).startswith("data:"):
                b64 = str(b64).split(",", 1)[1]
            return base64.b64decode(b64)
        url = item.get("url")
        if url:
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                r = client.get(url)
                r.raise_for_status()
                return r.content
        raise RuntimeError(f"Agnes 生图无 b64/url: {item}")

    def generate_and_save(
        self,
        prompt: str,
        out_path: str | Path,
        *,
        aspect_ratio: str = "9:16",
        subject_ref: str | None = None,
        extra_refs: list[str] | None = None,
    ) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        blob = self.generate_image(
            prompt,
            aspect_ratio=aspect_ratio,
            subject_ref=subject_ref,
            extra_refs=extra_refs,
        )
        out.write_bytes(blob)
        return out

    def extract_subject_white_bg(
        self,
        source_image: str | Path,
        out_path: str | Path,
        *,
        kind: str = "character",
        hint: str = "",
    ) -> Path:
        """从图中抠出人物/产品到纯白底资产图。"""
        if kind == "product":
            prompt = (
                "Extract ONLY the product bottle/package onto a pure white background. "
                "Centered product photography. NO human face, NO half-body portrait, NO people. "
                "Hands may be cropped away. Clean studio product shot. "
                f"{hint}"
            )
            ar = "1:1"
        else:
            prompt = (
                "Extract ONLY the single specified person onto a pure white background. "
                "Half-body portrait, keep that person's face, hair, clothes and age. "
                "If multiple people are in the photo, pick only the one matching the hint. "
                "No other people, no product bottle as main subject, no hand-only crop. "
                f"{hint}"
            )
            ar = "9:16"
        return self.generate_and_save(prompt, out_path, aspect_ratio=ar, subject_ref=str(source_image))
