---
name: video-dissect
description: >-
  爆款短视频深度拆解：钩子、分镜节拍、口播、产品、人物、复刻要点。
  用于 A 模式参考视频解析。
---

# 视频拆解 Skill

## 目标
把参考短视频拆成**可复刻**的结构化报告，供编导确认后再生成脚本。

## 拆解原则
1. **每个 beat 必须独立**：禁止多个 beat 复用同一句模板；每段写清具体画面、口播、情绪。
2. **时间轴连续**：beats 覆盖全片，t_start/t_end 单调递增，尽量贴合真实节奏。
3. **口播尽量完整**：script_skeleton.spoken_script_full 串联全片口播/字幕，不少于 80 字（有口播时）。
4. **产品信息**：products 写品类、露出时刻、卖点列表；不确定写「品类推测」。
5. **人物**：characters 写出镜者外观、角色、是否可替换。
6. **复刻笔记**：replication_notes 写明必须保留的节奏点、可替换元素、拍摄清单。

## 分镜 role 参考
开场钩子 → 铺垫/痛点 → 冲突放大 → 解决方案 → 产品露出 → 证据对比 → 催单CTA → 彩蛋

## 输出质量检查（自检）
- beats 数量 ≥ 6（30s 以上视频）或 ≥ 3（15s 以内）
- 每个 beat 的 spoken_or_subtitle 或 visual 至少 15 字
- hook.first_3s_script 必须有具体内容
- meta.one_line_summary 一句话说清「谁对谁讲了什么卖点」

## 调用
`StudioOrchestrator.parse_reference_video(project_id)`
