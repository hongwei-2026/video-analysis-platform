# 短视频分析平台

轻量视频理解 + 爆款脚本生成，面向「上传视频 / 填关键信息 → 出结构脚本」。

## 模型选型

| 模型 | 用途 | 大小 |
|------|------|------|
| **Qwen2.5-VL-3B-Instruct** | 看视频拆结构 | ~6GB |
| **Qwen2.5-1.5B + LoRA** | 生成脚本 JSON | ~3GB + 81MB |

已弃用 Qwen3-VL-8B（~17GB，过重）。

## Web 应用

```bash
pip install -r studio/requirements.txt
python studio/app.py
```

支持三种模式：仅文字生成 / 视频拆解 / 视频+生成脚本。

## 云端

```bash
cd /root/autodl-tmp/video-platform
export PYTHONPATH=$PWD
bash scripts/download_models.sh   # 首次
bash scripts/cloud_run_studio.sh
```

## 批量拆解管线

```bash
python -m src.pipeline.download_videos --urls data/urls.txt
python -m src.pipeline.batch_dissect --frames 32
```

## GitCode

https://gitcode.com/hongwei-2026/shiping_shengce

推送：`python scripts/push_gitcode.py`（需 `GITCODE_TOKEN`）
