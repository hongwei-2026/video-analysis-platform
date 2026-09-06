from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

GenMode = Literal["t2va", "i2va", "i2va_fl", "r2va"]
ProjectMode = Literal["A", "B"]


@dataclass
class ImageAsset:
    id: str
    path: str
    prompt: str
    role: str  # character_front | character_34 | product | scene | first_frame | last_frame
    source: str = "ai"  # ai | upload | extract

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StoryboardBeat:
    idx: int
    role: str
    duration_sec: int
    motion_prompt: str
    spoken: str
    gen_mode: GenMode
    first_frame: ImageAsset | None = None
    last_frame: ImageAsset | None = None
    reference_video_clip: str | None = None
    reference_image_path: str | None = None
    status: str = "pending"
    clip_path: str | None = None
    task_id: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.first_frame:
            d["first_frame"] = self.first_frame.to_dict()
        if self.last_frame:
            d["last_frame"] = self.last_frame.to_dict()
        return d


@dataclass
class ProjectPlan:
    project_id: str
    mode: ProjectMode
    script: dict[str, Any]
    assets: dict[str, Any] = field(default_factory=dict)
    storyboard: list[dict[str, Any]] = field(default_factory=list)
    clips: list[dict[str, Any]] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
