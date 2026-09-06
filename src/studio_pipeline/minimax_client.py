from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any

import httpx

REGION_BASES = (
    "https://api.minimaxi.com",  # 国内
    "https://api.minimax.io",  # 国际
)
POLL_INTERVAL = float(os.environ.get("MINIMAX_POLL_INTERVAL", "10"))
POLL_TIMEOUT = int(os.environ.get("MINIMAX_POLL_TIMEOUT", "900"))


def resolve_base_url() -> str:
    env = os.environ.get("MINIMAX_BASE_URL", "").strip().rstrip("/")
    if env:
        return env
    # 默认国内节点（国内 Key 更常见）
    return REGION_BASES[0]


class MiniMaxVideoClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = (api_key or os.environ.get("MINIMAX_API_KEY", "")).strip()
        if not self.api_key:
            raise ValueError("未配置 MINIMAX_API_KEY")
        self.base_url = (base_url or resolve_base_url()).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        bases = [self.base_url]
        for b in REGION_BASES:
            if b not in bases:
                bases.append(b)

        with httpx.Client(timeout=120) as client:
            for base in bases:
                url = f"{base}{path}"
                resp = client.post(url, headers=self._headers(), json=payload)
                if resp.status_code == 401:
                    errors.append(f"{base}: 401 未授权")
                    continue
                if resp.is_error:
                    detail = resp.text[:300]
                    raise RuntimeError(f"MiniMax 请求失败 {resp.status_code}: {detail}")
                self.base_url = base
                return resp.json()

        raise RuntimeError(
            "MiniMax API Key 认证失败（401）。请确认：\n"
            "1) Key 有效且为按量付费 API Key；\n"
            "2) 国内 Key 用 MINIMAX_BASE_URL=https://api.minimaxi.com；\n"
            "3) 国际 Key 用 MINIMAX_BASE_URL=https://api.minimax.io\n"
            + "; ".join(errors)
        )

    def _get(self, path: str) -> dict[str, Any]:
        with httpx.Client(timeout=60) as client:
            resp = client.get(f"{self.base_url}{path}", headers=self._headers())
            if resp.is_error:
                raise RuntimeError(f"MiniMax 查询失败 {resp.status_code}: {resp.text[:300]}")
            return resp.json()

    @staticmethod
    def _image_url(path: str) -> str:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        suffix = p.suffix.lower().lstrip(".")
        mime = "png" if suffix == "png" else "jpeg"
        return f"data:image/{mime};base64,{data}"

    @staticmethod
    def _video_url(path: str) -> str:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:video/mp4;base64,{data}"

    def ping(self) -> dict[str, Any]:
        """轻量连通性检测：提交 4s 文生视频任务并返回 task_id。"""
        task_id = self.create_task(
            prompt="竖屏测试：一杯咖啡放在木桌上，柔和日光",
            duration=4,
            ratio="9:16",
            resolution="768P",
        )
        data = self.query_task(task_id)
        return {
            "base_url": self.base_url,
            "task_id": task_id,
            "status": (data.get("task") or {}).get("status", "unknown"),
        }

    def create_task(
        self,
        *,
        prompt: str,
        duration: int = 5,
        ratio: str = "9:16",
        resolution: str = "768P",
        first_frame: str | None = None,
        last_frame: str | None = None,
        reference_video: str | None = None,
        reference_image: str | None = None,
    ) -> str:
        duration = int(max(4, min(15, duration)))
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]

        if reference_video or reference_image:
            if first_frame or last_frame:
                raise ValueError("reference 模式不能与首尾帧混用")
            if reference_image:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": self._image_url(reference_image)},
                        "role": "reference_image",
                    }
                )
            if reference_video:
                content.append(
                    {
                        "type": "video_url",
                        "video_url": {"url": self._video_url(reference_video)},
                        "role": "reference_video",
                    }
                )
            payload_ratio = "9:16" if ratio == "adaptive" else ratio
        else:
            if first_frame:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": self._image_url(first_frame)},
                        "role": "first_frame",
                    }
                )
            if last_frame:
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": self._image_url(last_frame)},
                        "role": "last_frame",
                    }
                )
            payload_ratio = "adaptive" if first_frame else ratio

        payload = {
            "model": "MiniMax-H3",
            "content": content,
            "resolution": resolution,
            "duration": duration,
            "ratio": payload_ratio,
        }
        data = self._post("/v2/video_generation", payload)
        task_id = data.get("task_id")
        if not task_id:
            raise RuntimeError(f"MiniMax 未返回 task_id: {data}")
        return task_id

    def query_task(self, task_id: str) -> dict[str, Any]:
        return self._get(f"/v2/query/video_generation/{task_id}")

    def wait_task(self, task_id: str) -> dict[str, Any]:
        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            data = self.query_task(task_id)
            task = data.get("task", {})
            status = task.get("status")
            if status == "succeeded":
                return task
            if status in ("failed", "cancelled"):
                err = task.get("error", {})
                raise RuntimeError(err.get("message") or f"任务失败: {status}")
            time.sleep(POLL_INTERVAL)
        raise TimeoutError(f"等待任务超时: {task_id}")

    def download_video(self, url: str, out_path: str | Path) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            out.write_bytes(resp.content)
        return out

    def generate_beat_clip(self, beat: dict[str, Any], out_path: str | Path) -> dict[str, Any]:
        gen_mode = beat.get("gen_mode", "i2va")
        prompt = beat.get("motion_prompt", "")
        if beat.get("spoken"):
            prompt = f"{prompt}\n口播内容：{beat['spoken']}"
        duration = int(beat.get("duration_sec", 5))

        kwargs: dict[str, Any] = {"prompt": prompt, "duration": duration, "ratio": "9:16"}
        if gen_mode == "r2va" and beat.get("reference_video_clip"):
            kwargs["reference_video"] = beat["reference_video_clip"]
            if beat.get("reference_image_path"):
                kwargs["reference_image"] = beat["reference_image_path"]
        elif gen_mode == "i2va_fl" and beat.get("last_frame"):
            kwargs["first_frame"] = beat["first_frame"]["path"]
            kwargs["last_frame"] = beat["last_frame"]["path"]
        elif gen_mode in ("i2va", "i2va_fl") and beat.get("first_frame"):
            kwargs["first_frame"] = beat["first_frame"]["path"]
        else:
            kwargs["ratio"] = "9:16"

        task_id = self.create_task(**kwargs)
        task = self.wait_task(task_id)
        url = (task.get("content") or {}).get("url")
        if not url:
            raise RuntimeError("任务成功但无视频 URL")
        self.download_video(url, out_path)
        return {"task_id": task_id, "path": str(out_path), "status": "succeeded", "base_url": self.base_url}


class MiniMaxImageClient(MiniMaxVideoClient):
    """MiniMax image-01 文生图 / 人物参考图生图。"""

    def generate_image(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "9:16",
        subject_ref: str | None = None,
        n: int = 1,
    ) -> list[bytes]:
        payload: dict[str, Any] = {
            "model": "image-01",
            "prompt": prompt[:1500],
            "aspect_ratio": aspect_ratio,
            "n": max(1, min(9, int(n))),
            "response_format": "base64",
            "prompt_optimizer": False,
            "aigc_watermark": False,
        }
        if subject_ref and Path(subject_ref).exists():
            payload["subject_reference"] = [
                {"type": "character", "image_file": self._image_url(subject_ref)}
            ]
        data = self._post("/v1/image_generation", payload)
        base = data.get("base_resp") or {}
        if base.get("status_code", 0) != 0:
            raise RuntimeError(base.get("status_msg") or f"生图失败: {data}")
        obj = data.get("data") or {}
        blobs: list[bytes] = []
        for b64 in obj.get("image_base64") or []:
            blobs.append(base64.b64decode(b64))
        if not blobs:
            urls = obj.get("image_urls") or []
            if not urls:
                raise RuntimeError(f"生图无返回: {data}")
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                for url in urls:
                    resp = client.get(url)
                    resp.raise_for_status()
                    blobs.append(resp.content)
        return blobs

    def generate_and_save(
        self,
        prompt: str,
        out_path: str | Path,
        *,
        aspect_ratio: str = "9:16",
        subject_ref: str | None = None,
    ) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        blobs = self.generate_image(prompt, aspect_ratio=aspect_ratio, subject_ref=subject_ref, n=1)
        out.write_bytes(blobs[0])
        return out
