"""LoRA 微调小模型：根据主题生成爆款短视频结构脚本。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForLanguageModeling,
    Trainer,
    TrainingArguments,
)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/train/sft.jsonl")
    ap.add_argument(
        "--base_model",
        default="/root/autodl-tmp/models/Qwen/Qwen2.5-1.5B-Instruct",
        help="本机缓存或魔搭下载后的路径",
    )
    ap.add_argument("--modelscope_id", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--out", default="/root/autodl-tmp/video-platform/models/script_lora")
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--batch_size", type=int, default=1)
    ap.add_argument("--grad_accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--max_len", type=int, default=2048)
    args = ap.parse_args()

    data_path = Path(args.data)
    rows = load_jsonl(data_path)
    if len(rows) < 4:
        raise SystemExit(f"样本太少({len(rows)})，请先跑批量拆解并 build_sft_dataset")

    base = Path(args.base_model)
    if not base.exists():
        print(f"[download] {args.modelscope_id} -> {base}")
        from modelscope import snapshot_download

        base.parent.mkdir(parents=True, exist_ok=True)
        snapshot_download(args.modelscope_id, local_dir=str(base))

    tokenizer = AutoTokenizer.from_pretrained(str(base), trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        str(base),
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    def to_text(ex):
        text = tokenizer.apply_chat_template(ex["messages"], tokenize=False, add_generation_prompt=False)
        return {"text": text}

    ds = Dataset.from_list(rows).map(to_text)

    def tokenize(batch):
        out = tokenizer(
            batch["text"],
            truncation=True,
            max_length=args.max_len,
            padding=False,
        )
        out["labels"] = [ids.copy() for ids in out["input_ids"]]
        return out

    tokenized = ds.map(tokenize, batched=True, remove_columns=ds.column_names)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    targs = TrainingArguments(
        output_dir=str(out_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=5,
        save_steps=50,
        save_total_limit=2,
        bf16=True,
        warmup_steps=5,
        report_to=[],
        remove_unused_columns=False,
        dataloader_pin_memory=False,
    )
    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    trainer = Trainer(model=model, args=targs, train_dataset=tokenized, data_collator=collator)
    trainer.train()

    adapter = out_dir / "adapter"
    model.save_pretrained(str(adapter))
    tokenizer.save_pretrained(str(adapter))
    meta = {
        "base_model": args.modelscope_id,
        "base_local": str(base),
        "samples": len(rows),
        "task": "viral-short-video-script-sft",
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] adapter -> {adapter}")


if __name__ == "__main__":
    main()
