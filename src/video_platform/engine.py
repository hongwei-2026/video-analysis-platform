from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import torch


class QwenVLEngine:
    """轻量 Qwen-VL 推理（默认 Qwen2.5-VL-3B，兼容 2B/3B/8B 系列）。"""

    def __init__(
        self,
        model_dir: str,
        dtype: str = "bfloat16",
        attn_implementation: str = "sdpa",
    ):
        self.model_dir = str(model_dir)
        self.dtype = dtype
        self.attn_implementation = attn_implementation
        self.model = None
        self.processor = None

    def load(self) -> None:
        torch_dtype = {
            "bfloat16": torch.bfloat16,
            "float16": torch.float16,
            "auto": "auto",
        }.get(self.dtype, torch.bfloat16)

        from transformers import AutoModelForImageTextToText, AutoProcessor

        kwargs: dict[str, Any] = {
            "device_map": "auto",
            "trust_remote_code": True,
            "torch_dtype": torch_dtype if torch_dtype != "auto" else "auto",
        }
        last_err: Exception | None = None
        for attn in (self.attn_implementation, "sdpa", None):
            try:
                k = dict(kwargs)
                if attn:
                    k["attn_implementation"] = attn
                print(f"[load] vl={self.model_dir} attn={attn}")
                self.model = AutoModelForImageTextToText.from_pretrained(self.model_dir, **k)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                print(f"[load] attn={attn} failed: {e}")
                self.model = None
        if self.model is None:
            raise RuntimeError(f"VL 模型加载失败: {last_err}")

        self.processor = AutoProcessor.from_pretrained(self.model_dir, trust_remote_code=True)
        print(f"[load] ok: {self.model_dir}")

    @torch.inference_mode()
    def chat(self, messages: list[dict], max_new_tokens: int = 2048) -> str:
        if self.model is None or self.processor is None:
            raise RuntimeError("请先调用 load()")

        try:
            from qwen_vl_utils import process_vision_info

            text = self.processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )
        except Exception:
            inputs = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )

        inputs = inputs.to(self.model.device)
        generated = self.model.generate(**inputs, max_new_tokens=max_new_tokens)
        trimmed = [out[len(inp) :] for inp, out in zip(inputs.input_ids, generated)]
        texts = self.processor.batch_decode(
            trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        return texts[0] if texts else ""


# 向后兼容旧名
Qwen3VLEngine = QwenVLEngine


def download_model_from_modelscope(model_id: str, local_dir: str) -> str:
    """国内源：ModelScope snapshot_download。"""
    os.environ.setdefault("MODELSCOPE_CACHE", str(Path(local_dir).parent.parent))
    from modelscope import snapshot_download

    Path(local_dir).parent.mkdir(parents=True, exist_ok=True)
    path = snapshot_download(model_id, local_dir=local_dir)
    return path
