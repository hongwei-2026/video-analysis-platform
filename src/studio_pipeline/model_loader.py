from __future__ import annotations

import os
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
DEFAULT_VL = ROOT / "models" / "Qwen2.5-VL-3B-Instruct"
ADAPTER_DIR = Path(os.environ.get("ADAPTER_DIR", str(ROOT / "studio" / "adapter")))

BASE_ID = os.environ.get("BASE_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
VL_ID = os.environ.get("VL_MODEL_ID", "Qwen/Qwen2.5-VL-3B-Instruct")

_vl_engine = None
_script_tokenizer = None
_script_model = None


def _resolve_dir(env_key: str, *candidates: Path) -> str | None:
    env = os.environ.get(env_key, "").strip()
    if env and Path(env).exists():
        return env
    for c in candidates:
        if c.exists() and any(c.iterdir()):
            return str(c)
    return None


def load_vl():
    global _vl_engine
    if _vl_engine is not None:
        return _vl_engine

    from src.studio_pipeline.agnes_llm import use_agnes_llm

    if use_agnes_llm():
        from src.studio_pipeline.agnes_llm import AgnesChatEngine

        _vl_engine = AgnesChatEngine()
        _vl_engine.load()
        return _vl_engine

    from src.video_platform.engine import QwenVLEngine

    vl_dir = _resolve_dir(
        "VL_MODEL_DIR",
        DEFAULT_VL,
        Path("/root/autodl-tmp/models/Qwen/Qwen2.5-VL-3B-Instruct"),
    )
    if not vl_dir:
        from modelscope import snapshot_download

        vl_dir = snapshot_download(VL_ID, local_dir=str(DEFAULT_VL))
    _vl_engine = QwenVLEngine(vl_dir, attn_implementation="sdpa")
    _vl_engine.load()
    return _vl_engine


def load_script_model():
    global _script_tokenizer, _script_model
    if _script_model is not None:
        return _script_tokenizer, _script_model

    from src.studio_pipeline.agnes_llm import use_agnes_llm

    if use_agnes_llm():
        raise RuntimeError("LLM_PROVIDER=agnes 时不应加载本地脚本模型，请使用 agnes_chat_text")

    base = _resolve_dir("BASE_MODEL_DIR", DEFAULT_BASE, ROOT / "studio" / "base_model")
    if not base:
        from modelscope import snapshot_download

        base = snapshot_download(BASE_ID, local_dir=str(DEFAULT_BASE))

    _script_tokenizer = AutoTokenizer.from_pretrained(base, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        base,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        trust_remote_code=True,
    )
    if ADAPTER_DIR.exists() and any(ADAPTER_DIR.iterdir()):
        model = PeftModel.from_pretrained(model, str(ADAPTER_DIR))
    _script_model = model.eval()
    return _script_tokenizer, _script_model
