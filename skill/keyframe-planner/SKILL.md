---
name: keyframe-planner
description: >-
  分镜首尾帧规划：为每个 beat 生成首帧/尾帧 prompt，保持光线色调人物一致。
  借鉴首尾帧锚定工作流（Kling/Runway/MiniMax H3）。
---

# 分镜关键帧 Skill

## Beat 类型 → 帧策略

| 类型 | 首帧 | 尾帧 | 时长 |
|------|------|------|------|
| 钩子 | 强构图 | 略推近 | 3–5s |
| 口播 | 人物中景 | 可不设 | 5–8s |
| 转场 | 场景 A | 场景 B | 4–6s |
| CTA | 人+品同框 | 引导构图 | 3–5s |

## Prompt 公式
`[主体+动作] → [运镜动词] → [光线来源] → [9:16竖屏]`

## 一致性
- 首尾帧同色调、同服装、同光线方向
- 先静帧确认，再 I2V
- 尾帧与下 beat 首帧可衔接（硬切）

## 实现
`src/studio_pipeline/asset_service.py` → `StoryboardService.build_storyboard`
