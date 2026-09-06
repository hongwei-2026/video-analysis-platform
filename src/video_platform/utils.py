from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        candidates = [
            Path("configs/default.yaml"),
            Path("/root/autodl-tmp/video-platform/configs/default.yaml"),
        ]
        for c in candidates:
            if c.exists():
                path = c
                break
        else:
            raise FileNotFoundError("找不到 configs/default.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出中尽量抽出 JSON 对象。"""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    def _try_load(s: str) -> dict[str, Any]:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            fixed = re.sub(r",\s*}", "}", s)
            fixed = re.sub(r",\s*]", "]", fixed)
            fixed = re.sub(r"\}\s*\{", "},{", fixed)
            return json.loads(fixed)

    try:
        return _try_load(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return _try_load(m.group(0))


def ensure_dir(p: str | Path) -> Path:
    path = Path(p)
    path.mkdir(parents=True, exist_ok=True)
    return path
