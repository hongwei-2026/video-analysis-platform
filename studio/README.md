# 爆款短视频生产平台

A/B 两条路径共用一条流水线：**脚本确认 → AI 资产 → 分镜首尾帧 → MiniMax 视频 → 质检拼接**。

## 模型

| 用途 | 模型 | 约大小 |
|------|------|--------|
| 视频拆解（A） | Qwen2.5-VL-3B-Instruct | ~6GB |
| 脚本/分镜规划 | Qwen2.5-1.5B + LoRA | ~3GB + 81MB |
| 高清成片 | MiniMax H3 API | 按量计费 |

## 启动

```bash
cd studio
pip install -r requirements.txt
cp ../scripts/.env.example ../scripts/.env   # 填入 MINIMAX_API_KEY
cd .. && python studio/app.py
```

## 流水线步骤（Web「生产流水线」Tab）

1. **① 生成脚本** — A 上传参考视频拆解；B 填关键信息或上传脚本 JSON
2. **② 确认脚本** — 展示可编辑 JSON，人工 Gate
3. **③ 资产看板** — AI 生成人设多视角+产品图；可选上传替换
4. **④ 分镜首尾帧** — 每 beat 首帧/尾帧预览
5. **⑤ 生成视频** — MiniMax H3（I2V / 首尾帧 / Ref2VA）+ ffmpeg 拼接 + 质检
6. **⑥ 单镜重生成** — 质检不通过的 beat 单独重跑

勾选「跳过 MiniMax」可本地跑通全流程（不生高清视频）。

## 环境变量

见 `scripts/.env.example`：

- `MINIMAX_API_KEY` — 视频生成（必填才能出成片）
- `VL_MODEL_DIR` / `BASE_MODEL_DIR` / `ADAPTER_DIR`
- `STUDIO_PROJECTS_DIR` — 项目与 plan.json 存储目录
- `PORT` — 默认 7860（云端 AutoDL 用 6006）

## 代码结构

```
src/studio_pipeline/
  orchestrator.py    # 主编排
  llm_service.py     # 脚本/导演/资产规划
  minimax_client.py  # MiniMax H3 API
  qc_service.py      # 一致性质检
  asset_service.py   # 资产+分镜帧生成
skill/
  viral-short-script/
  video-director/
  keyframe-planner/
  minimax-video-gen/
  video-qc/
```

## 快速脚本 Tab

保留旧版「仅拆解 / 仅生成脚本」轻量入口。
