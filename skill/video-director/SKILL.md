---
name: video-director
description: >-
  将脚本 JSON 深化为分镜规划：每 beat 的运镜、时长、生成模式、首尾帧描述。
  用于 A/B 流水线步骤 ④ 之前的导演层。
---

# 视频导演 Skill

## 输入
- `script.json`（viral-short-script 格式）
- 模式 `A`（有参考片拆解）或 `B`（纯创作）

## 输出 beats 字段
```json
{
  "beats": [
    {
      "idx": 1,
      "role": "开场钩子",
      "duration_sec": 5,
      "motion_prompt": "slow dolly push, rack focus to product",
      "spoken": "口播文本",
      "gen_mode": "i2va|i2va_fl|t2va|r2va",
      "first_frame_prompt": "9:16, character medium shot, soft daylight",
      "last_frame_prompt": "optional",
      "use_reference_video": false
    }
  ]
}
```

## 规则（参考 kling-3-prompting / OpenMontage）
- 口播镜：`i2va`，轻微运镜
- 转场/表情变化：`i2va_fl` + 首尾帧
- 产品 B-roll：`t2va`
- A 模式保留原片运动：`r2va` + `use_reference_video=true`
- 单镜 4–15s；口播时长优先（约 4 字/秒）

## 调用
`StudioOrchestrator.build_storyboard(project_id)`
