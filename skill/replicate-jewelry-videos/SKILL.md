---
name: replicate-jewelry-videos
description: >-
  饰品带货短视频复刻工作流参考。完整 Skill 见 ~/.codex/skills/replicate-jewelry-videos。
---

# 饰品复刻（项目内引用）

本地开发时设置 `JEWELRY_MODE=1`，解析对标视频会注入 `references/reverse-prompt.md`（去产品细节反推）。

完整 10 步工作流、质检与脚本见 Codex Skill：`~/.codex/skills/replicate-jewelry-videos`

## 本目录

- [references/reverse-prompt.md](references/reverse-prompt.md) — 反推提示词（饰品用 `{{PRODUCT_SLOT}}`）
- [references/image-gen-prompts.md](references/image-gen-prompts.md) — Phase A/B 生图模板
