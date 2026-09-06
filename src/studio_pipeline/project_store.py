from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.video_platform.utils import ensure_dir


class ProjectStore:
    def __init__(self, root: str | Path):
        self.root = ensure_dir(root)

    def new_id(self) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{ts}_{uuid.uuid4().hex[:8]}"

    def project_dir(self, project_id: str) -> Path:
        return ensure_dir(self.root / project_id)

    def plan_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "plan.json"

    def save_plan(self, plan: dict[str, Any]) -> Path:
        pid = plan["project_id"]
        path = self.plan_path(pid)
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_plan(self, project_id: str) -> dict[str, Any]:
        path = self.plan_path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"项目不存在: {project_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def assets_dir(self, project_id: str) -> Path:
        return ensure_dir(self.project_dir(project_id) / "assets")

    def frames_dir(self, project_id: str) -> Path:
        return ensure_dir(self.project_dir(project_id) / "frames")

    def clips_dir(self, project_id: str) -> Path:
        return ensure_dir(self.project_dir(project_id) / "clips")

    def output_dir(self, project_id: str) -> Path:
        return ensure_dir(self.project_dir(project_id) / "output")
