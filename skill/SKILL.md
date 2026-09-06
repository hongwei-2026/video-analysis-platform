---
name: viral-short-script
description: >-
  根据品类/卖点/人群生成可拍摄的爆款短视频结构脚本（钩子、分镜节拍、口播、CTA）。
  当用户需要短视频脚本、种草口播、一键复刻结构、爆款分镜时使用本 skill。
---

# 爆款短视频结构脚本 Skill

## 何时使用
- 用户要「短视频脚本 / 口播稿 / 分镜 / 种草结构」
- 用户要「复刻某类爆款」的可执行结构，而不是空泛文案
- 用户提供了产品、人群、风格，需要一键出结构 JSON

## 输出格式（必须）
输出合法 JSON，字段尽量齐全：

```json
{
  "meta": {
    "estimated_duration_sec": 30,
    "platform_style": "抖音",
    "genre": "种草",
    "one_line_summary": ""
  },
  "hook": {
    "type": "痛点|反差|悬念|利益点",
    "first_3s_script": "",
    "visual_hook": ""
  },
  "beats": [
    {
      "idx": 1,
      "t_start_sec": 0,
      "t_end_sec": 3,
      "role": "开场钩子",
      "visual": "",
      "spoken_or_subtitle": "",
      "product_visible": false
    }
  ],
  "script_skeleton": {
    "structure_pattern": "钩子-痛点-方案-证据-CTA",
    "spoken_script_full": "",
    "cta": ""
  },
  "replication_notes": {
    "must_keep": [],
    "can_replace": ["人物形象", "产品"]
  }
}
```

## 工作流
1. 确认产品品类、目标人群、风格（痛点/避雷/清单/剧情）。
2. 先写 3 秒钩子，再拆 4–8 个 beats。
3. 口播与画面一一对应；CTA 明确。
4. 标注哪些可换人/换品，便于一键复刻。

## 可选：调用本地微调模型
- Web：`python studio/app.py`（视频/文字 → 脚本）
- 视频理解：`Qwen2.5-VL-3B-Instruct`（~6GB，轻量）
- 脚本生成：`Qwen2.5-1.5B` + `studio/adapter/` LoRA
- 仓库：https://gitcode.com/hongwei-2026/shiping_shengce

没有本地模型时，按上述 JSON schema 直接生成即可。
