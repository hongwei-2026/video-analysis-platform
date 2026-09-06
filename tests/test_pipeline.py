"""流水线单元测试（不加载大模型）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.studio_pipeline.orchestrator import StudioOrchestrator

SAMPLE_SCRIPT = {
    "meta": {"estimated_duration_sec": 20, "one_line_summary": "测试"},
    "hook": {"first_3s_script": "你还在踩雷吗？"},
    "beats": [
        {
            "idx": 1,
            "t_start_sec": 0,
            "t_end_sec": 5,
            "role": "开场钩子",
            "visual": "女生举产品",
            "spoken_or_subtitle": "夏天防晒真的别乱买",
        },
        {
            "idx": 2,
            "t_start_sec": 5,
            "t_end_sec": 12,
            "role": "产品露出",
            "visual": "产品特写",
            "spoken_or_subtitle": "这支喷雾敏感肌也能用",
        },
    ],
    "script_skeleton": {"cta": "评论区领券"},
    "characters": [{"appearance": "25岁清爽女生"}],
    "products": [{"name_guess": "防晒喷雾"}],
}

SAMPLE_SB = {
    "beats": [
        {
            "idx": 1,
            "role": "开场钩子",
            "duration_sec": 5,
            "motion_prompt": "slow dolly push",
            "spoken": "夏天防晒真的别乱买",
            "gen_mode": "i2va",
            "first_frame_prompt": "女生举防晒喷雾，明亮室内",
        },
        {
            "idx": 2,
            "role": "产品露出",
            "duration_sec": 6,
            "motion_prompt": "rack focus to product",
            "spoken": "这支喷雾敏感肌也能用",
            "gen_mode": "i2va_fl",
            "first_frame_prompt": "产品特写",
            "last_frame_prompt": "产品使用场景",
        },
    ]
}

SAMPLE_ASSETS = {
    "character_sheet": {
        "persona": "25岁清爽女生",
        "angles": [
            {"id": "front", "label": "正脸", "prompt": "正脸半身"},
            {"id": "three_quarter", "label": "3/4侧", "prompt": "3/4侧"},
        ],
    },
    "product": {"prompt": "防晒喷雾产品图"},
    "scene_style": {"prompt": "明亮种草风"},
}


def test_pipeline_dry_run(tmp_path: Path):
    root = tmp_path / "projects"
    orch = StudioOrchestrator(root)

    with (
        patch("src.studio_pipeline.orchestrator.generate_script", return_value=SAMPLE_SCRIPT),
        patch("src.studio_pipeline.asset_service.plan_assets", return_value=SAMPLE_ASSETS),
        patch("src.studio_pipeline.asset_service.plan_storyboard", return_value=SAMPLE_SB),
    ):
        plan = orch.create_project(
            mode="B", product="防晒", topic="测试", audience="通用用户", style="痛点钩子"
        )
        pid = plan["project_id"]
        plan = orch.build_assets(pid)
        assert len(plan["assets"]["images"]) >= 2
        plan = orch.build_storyboard(pid)
        assert len(plan["storyboard"]) == 2
        plan = orch.generate_videos(pid, dry_run=True)
        assert plan["output"].get("note")

    plan_path = root / pid / "plan.json"
    assert plan_path.exists()
    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    assert saved["storyboard"][0]["first_frame"]["path"]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        test_pipeline_dry_run(Path(d))
        print("pipeline test passed")
