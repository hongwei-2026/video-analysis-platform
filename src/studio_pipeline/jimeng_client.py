"""即梦 AI 视频生成（火山引擎 visual API，jimeng_ti2v_v30_pro）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from src.studio_pipeline.agnes_client import _env

HOST = "visual.volcengineapi.com"
SERVICE = "cv"
REGION = "cn-north-1"
REQ_KEY = "jimeng_ti2v_v30_pro"
API_VERSION = "2022-08-31"


def _has_jimeng_keys() -> bool:
    return bool(_env("VOLC_ACCESSKEY") and _env("VOLC_SECRETKEY"))


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _hash_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _canonical_query(params: dict[str, str]) -> str:
    return "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items()))


def _volc_request(action: str, body: dict[str, Any]) -> dict[str, Any]:
    ak = _env("VOLC_ACCESSKEY")
    sk = _env("VOLC_SECRETKEY")
    if not ak or not sk:
        raise ValueError("未配置 VOLC_ACCESSKEY / VOLC_SECRETKEY")

    now = datetime.now(timezone.utc)
    date_stamp = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")

    query = {"Action": action, "Version": API_VERSION}
    canonical_query = _canonical_query(query)
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    payload_hash = _hash_hex(payload)

    canonical_headers = (
        f"content-type:application/json\n"
        f"host:{HOST}\n"
        f"x-content-sha256:{payload_hash}\n"
        f"x-date:{amz_date}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        ["POST", "/", canonical_query, canonical_headers, signed_headers, payload_hash]
    )

    credential_scope = f"{date_stamp}/{REGION}/{SERVICE}/request"
    string_to_sign = "\n".join(["HMAC-SHA256", amz_date, credential_scope, _hash_hex(canonical_request)])

    k_date = _sign(sk.encode("utf-8"), date_stamp)
    k_region = _sign(k_date, REGION)
    k_service = _sign(k_region, SERVICE)
    k_signing = _sign(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"HMAC-SHA256 Credential={ak}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    url = f"https://{HOST}/?{canonical_query}"
    headers = {
        "Content-Type": "application/json",
        "Host": HOST,
        "X-Date": amz_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": authorization,
    }
    with httpx.Client(timeout=120) as client:
        resp = client.post(url, headers=headers, content=payload.encode("utf-8"))
        if resp.is_error:
            raise RuntimeError(f"Jimeng API {action} 失败 {resp.status_code}: {resp.text[:400]}")
        return resp.json()


def _frames_for_seconds(seconds: int) -> int:
    return 241 if seconds >= 8 else 121


class JimengVideoClient:
    def __init__(self):
        if not _has_jimeng_keys():
            raise ValueError("未配置 VOLC_ACCESSKEY / VOLC_SECRETKEY")

    def submit_task(
        self,
        *,
        prompt: str,
        image_path: str | None = None,
        seconds: int = 5,
        aspect_ratio: str = "9:16",
        seed: int = -1,
    ) -> str:
        body: dict[str, Any] = {
            "req_key": REQ_KEY,
            "prompt": (prompt or "natural jewelry product motion, vertical video")[:800],
            "frames": _frames_for_seconds(seconds),
            "aspect_ratio": aspect_ratio,
            "seed": seed,
        }
        if image_path and Path(image_path).exists():
            b64 = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
            body["binary_data_base64"] = [b64]

        data = _volc_request("CVSync2AsyncSubmitTask", body)
        code = data.get("code") or (data.get("ResponseMetadata") or {}).get("Error", {}).get("Code")
        if str(code) not in ("10000", "0", "None") and data.get("code") not in (10000, 0):
            if data.get("data") is None and not (data.get("Result") or {}).get("task_id"):
                raise RuntimeError(f"Jimeng 提交失败: {data}")
        inner = data.get("data") or data.get("Result") or data
        task_id = inner.get("task_id") or inner.get("TaskId")
        if not task_id:
            raise RuntimeError(f"Jimeng 未返回 task_id: {data}")
        return str(task_id)

    def get_result(self, task_id: str) -> dict[str, Any]:
        body = {"req_key": REQ_KEY, "task_id": task_id}
        return _volc_request("CVSync2AsyncGetResult", body)

    def wait_result(self, task_id: str, timeout: int = 900, interval: float = 8.0) -> dict[str, Any]:
        deadline = time.time() + timeout
        last: dict[str, Any] = {}
        while time.time() < deadline:
            last = self.get_result(task_id)
            inner = last.get("data") or last.get("Result") or last
            status = str(inner.get("status") or inner.get("Status") or "").lower()
            if status in ("done", "success", "succeeded"):
                return last
            if status in ("failed", "error", "not_found", "expired"):
                raise RuntimeError(f"Jimeng 任务失败: {last}")
            time.sleep(interval)
        raise TimeoutError(f"Jimeng 超时 task_id={task_id} last={last}")

    @staticmethod
    def _extract_video_url(result: dict[str, Any]) -> str:
        inner = result.get("data") or result.get("Result") or result
        url = inner.get("video_url") or inner.get("VideoUrl")
        if isinstance(url, str) and url.startswith("http"):
            return url
        resp = inner.get("resp_data")
        if isinstance(resp, str):
            try:
                parsed = json.loads(resp)
                url = parsed.get("video_url")
                if url:
                    return url
            except Exception:
                pass
        raise RuntimeError(f"Jimeng 完成但无 video_url: {list(inner.keys())}")

    def download_video(self, url: str, out_path: str | Path) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            out.write_bytes(resp.content)
        return out

    def generate_beat_clip(self, beat: dict[str, Any], out_path: str | Path) -> dict[str, Any]:
        prompt = beat.get("motion_prompt", "") or ""
        if beat.get("spoken"):
            prompt = f"{prompt}\n本段中文口播/字幕原文：「{beat['spoken']}」"
        if beat.get("visual"):
            prompt = f"{prompt}\n画面：{beat['visual']}"
        prompt = (
            "竖屏中文短视频续拍。"
            "说话必须中文普通话，字幕必须简体中文；禁止英文/外文字幕与中英混杂。"
            f"\n{prompt}"
        )
        duration = int(max(4, min(10, beat.get("duration_sec", 5))))

        first = None
        if beat.get("first_frame") and isinstance(beat["first_frame"], dict):
            first = beat["first_frame"].get("path")

        task_id = self.submit_task(prompt=prompt, image_path=first, seconds=duration, aspect_ratio="9:16")
        result = self.wait_result(task_id)
        url = self._extract_video_url(result)
        self.download_video(url, out_path)
        return {
            "task_id": task_id,
            "path": str(out_path),
            "status": "succeeded",
            "provider": "jimeng",
            "url": url,
        }
