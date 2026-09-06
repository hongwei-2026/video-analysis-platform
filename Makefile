# 短视频结构拆解 / 爆款脚本数据管线
# 云端: vGPU + Qwen2.5-VL-3B + Qwen2.5-1.5B LoRA

.PHONY: help remote-setup remote-download-model remote-test

help:
	@echo "本地: 用 scripts/deploy_remote.py 把代码同步到云机并安装依赖"
	@echo "云端: bash scripts/remote_setup.sh"

remote-setup:
	python scripts/deploy_remote.py --setup

remote-download-model:
	python scripts/deploy_remote.py --download-model

remote-sync:
	python scripts/deploy_remote.py --sync-only
