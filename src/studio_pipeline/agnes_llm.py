"""Agnes 云端 LLM/VL（OpenAI 兼容 Chat Completions）。"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

from src.studio_pipeline.agnes_client import _env

DEFAULT_CHAT_MODEL = "agnes-2.5-flash"
DEFAULT_PROMPT_MODEL = "agnes-1.5-flash"


def use_agnes_llm() -> bool:
    provider = _env("LLM_PROVIDER").lower()
    if provider in ("agnes", "agens"):
        return bool(_env("AGNES_API_KEY"))
    # 显式未设置时：有 key 且不要求本地 VL 则走云端
    if not provider and _env("AGNES_API_KEY") and _env("FORCE_LOCAL_LLM") not in ("1", "true", "yes"):
        return True
    return False


def _chat_model(for_json: bool = False) -> str:
    if for_json:
        return _env("AGNES_PROMPT_MODEL", DEFAULT_PROMPT_MODEL) or DEFAULT_PROMPT_MODEL
    return _env("AGNES_CHAT_MODEL", DEFAULT_CHAT_MODEL) or DEFAULT_CHAT_MODEL


def _base_url() -> str:
    base = _env("AGNES_BASE_URL", "https://apihub.agnes-ai.com").rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _image_to_data_uri(path: str | Path) -> str:
    p = Path(path)
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    suffix = p.suffix.lower().lstrip(".")
    mime = "png" if suffix == "png" else "jpeg"
    return f"data:image/{mime};base64,{data}"


def _convert_content(content: Any) -> Any:
    """Qwen-VL 内部格式 → OpenAI content blocks。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    blocks: list[dict[str, Any]] = []
    for item in content:
        if isinstance(item, str):
            blocks.append({"type": "text", "text": item})
            continue
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "text":
            blocks.append({"type": "text", "text": item.get("text", "")})
        elif t == "image":
            img = item.get("image") or item.get("image_url") or item.get("url")
            if img:
                url = _image_to_data_uri(img) if Path(str(img)).exists() else str(img)
                blocks.append({"type": "image_url", "image_url": {"url": url}})
        elif t == "image_url":
            blocks.append(item)
        elif "text" in item:
            blocks.append({"type": "text", "text": item["text"]})
    return blocks or ""


def _convert_messages(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for m in messages:
        role = m.get("role", "user")
        content = _convert_content(m.get("content"))
        out.append({"role": role, "content": content})
    return out


def agnes_chat_completion(
    messages: list[dict],
    *,
    max_tokens: int = 2048,
    temperature: float = 0.65,
    for_json: bool = False,
) -> str:
    api_key = _env("AGNES_API_KEY")
    if not api_key:
        raise ValueError("未配置 AGNES_API_KEY")

    payload = {
        "model": _chat_model(for_json=for_json),
        "messages": _convert_messages(messages),
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    url = f"{_base_url()}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=300) as client:
        resp = client.post(url, headers=headers, json=payload)
        if resp.is_error:
            raise RuntimeError(f"Agnes chat 失败 {resp.status_code}: {resp.text[:500]}")
        data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"Agnes chat 无 choices: {str(data)[:300]}")
    msg = choices[0].get("message") or {}
    return (msg.get("content") or "").strip()


def agnes_chat_text(system: str, user: str, *, max_new_tokens: int = 2800) -> str:
    return agnes_chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_new_tokens,
    )


class AgnesChatEngine:
    """与 QwenVLEngine 兼容的 chat 接口，供 dissect / classify 复用。"""

    def load(self) -> None:
        if not _env("AGNES_API_KEY"):
            raise ValueError("LLM_PROVIDER=agnes 但未配置 AGNES_API_KEY")
        print("[load] Agnes chat engine (cloud VL/LLM)")

    def chat(self, messages: list[dict], max_new_tokens: int = 2048) -> str:
        return agnes_chat_completion(messages, max_tokens=max_new_tokens)
