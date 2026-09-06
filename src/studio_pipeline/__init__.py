"""短视频 A/B 生产流水线：脚本 → 资产 → 分镜 → 视频 → 质检。"""

from src.studio_pipeline.orchestrator import StudioOrchestrator

__all__ = ["StudioOrchestrator"]
