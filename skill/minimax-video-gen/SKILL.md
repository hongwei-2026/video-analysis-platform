---
name: minimax-video-gen
description: >-
  MiniMax H3 视频生成：T2V / I2V 首尾帧 / Ref2VA，异步轮询，分段拼接。
  配置 MINIMAX_API_KEY 后使用。
---

# MiniMax 视频生成 Skill

## 环境
```bash
# scripts/.env
MINIMAX_API_KEY=sk-api-...
MINIMAX_BASE_URL=https://api.minimaxi.com   # 国内
# MINIMAX_BASE_URL=https://api.minimax.io  # 国际
```

未配置 `MINIMAX_BASE_URL` 时，401 会自动在国内/国际节点间切换。

## 模式选择（互斥，不可混用）

| gen_mode | API 输入 |
|----------|----------|
| t2va | text only, ratio=9:16 |
| i2va | text + first_frame |
| i2va_fl | text + first_frame + last_frame |
| r2va | text + reference_video (+ reference_image) |

## 时长
- 4–15 秒整数
- 口播 beat：先估时长再定 duration

## 拼接
多 beat 生成后 `ffmpeg concat` → `output/master.mp4`

## 代码
- `src/studio_pipeline/minimax_client.py`
- `StudioOrchestrator.generate_videos()`

## 参考
- https://platform.minimax.io/docs/api-reference/video-generation-v2-create
