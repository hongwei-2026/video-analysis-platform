from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


SYSTEM = (
    "你是爆款短视频编导。根据用户给出的品类/卖点/风格，"
    "输出可拍摄的结构脚本 JSON（含 hook、beats、script_skeleton、replication_notes）。"
    "只输出合法 JSON，不要 Markdown 围栏。"
)

AUGMENT_STYLES = ["痛点钩子", "反差对比", "结果先行", "避雷测评", "清单种草", "剧情植入"]
AUGMENT_AUDIENCES = ["学生党", "打工人", "宝妈", "数码爱好者", "健身人群", "护肤小白"]


def _one_line(data: dict) -> str:
    meta = data.get("meta") or {}
    sk = data.get("script_skeleton") or {}
    hook = data.get("hook") or {}
    return (
        f"品类={meta.get('genre') or '种草'}; "
        f"风格={meta.get('platform_style') or '抖音'}; "
        f"钩子={hook.get('type') or ''}; "
        f"结构={sk.get('structure_pattern') or ''}; "
        f"摘要={meta.get('one_line_summary') or ''}"
    )


def _clean_target(data: dict) -> dict:
    # 去掉内部字段，保留可训练结构
    out = {k: v for k, v in data.items() if not str(k).startswith("_") and k != "parse_error" and k != "raw_text"}
    return out


def build_samples(scripts_dir: Path) -> list[dict]:
    samples: list[dict] = []
    for p in sorted(scripts_dir.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("parse_error"):
            continue
        target = _clean_target(data)
        if not target.get("beats") and not (target.get("script_skeleton") or {}).get("spoken_script_full"):
            continue

        base_user = (
            f"请生成一条短视频结构脚本。\n"
            f"参考信息：{_one_line(data)}\n"
            f"要求：竖屏口播/种草风格，包含钩子、分镜节拍、口播稿、CTA。"
        )
        samples.append(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": base_user},
                    {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
                ],
                "source": p.name,
            }
        )

        # 轻量增强：换风格/人群指令，目标仍用原结构（学结构骨架）
        for _ in range(2):
            style = random.choice(AUGMENT_STYLES)
            aud = random.choice(AUGMENT_AUDIENCES)
            user = (
                f"目标人群：{aud}\n"
                f"内容风格：{style}\n"
                f"主题：{(data.get('meta') or {}).get('one_line_summary') or '爆款种草'}\n"
                f"请输出完整结构脚本 JSON（hooks/beats/口播/CTA）。"
            )
            samples.append(
                {
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
                    ],
                    "source": p.name,
                    "augmented": True,
                }
            )
    return samples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts", default="data/scripts")
    ap.add_argument("--out", default="data/train/sft.jsonl")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    random.seed(args.seed)

    samples = build_samples(Path(args.scripts))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"[ok] samples={len(samples)} -> {out}")


if __name__ == "__main__":
    main()
