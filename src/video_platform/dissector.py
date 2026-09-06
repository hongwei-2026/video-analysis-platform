from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.video_platform.engine import QwenVLEngine
from src.video_platform.prompts import build_messages
from src.video_platform.utils import extract_json


class VideoDissector:
    def __init__(self, engine: QwenVLEngine, num_frames: int = 32, max_new_tokens: int = 2048):
        self.engine = engine
        self.num_frames = num_frames
        self.max_new_tokens = max_new_tokens

    def dissect(self, video_path: str | Path) -> dict[str, Any]:
        video_path = str(Path(video_path).resolve())
        messages = build_messages(video_path, max_frames=self.num_frames)
        raw = self.engine.chat(messages, max_new_tokens=self.max_new_tokens)
        try:
            data = extract_json(raw)
        except Exception:
            data = {"parse_error": True, "raw_text": raw}
        data["_source_video"] = video_path
        data["_num_frames"] = self.num_frames
        return data

    def dissect_to_file(self, video_path: str | Path, out_path: str | Path) -> dict[str, Any]:
        data = self.dissect(video_path)
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data
