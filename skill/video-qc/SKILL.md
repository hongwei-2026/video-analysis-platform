---
name: video-qc
description: >-
  成片一致性质检：人脸色调、首尾帧、口播时长、片段完整性。
  不通过可单镜重生成。
---

# 视频质检 Skill

## 检查项
1. 首帧是否存在
2. 口播时长 vs 镜头时长（±4s 告警）
3. 首帧 vs 角色参考色调偏差
4. 首尾帧色调一致性（i2va_fl）
5. 片段文件是否存在
6. 生成失败 beat 标红

## 输出
```json
{
  "score": 85,
  "passed": true,
  "issues": [{"beat": 2, "level": "warn", "msg": "..."}],
  "summary": "质检得分 85，问题 1 项"
}
```

## 单镜重跑
`StudioOrchestrator.rerun_beat(project_id, beat_idx)`

## 代码
`src/studio_pipeline/qc_service.py`
