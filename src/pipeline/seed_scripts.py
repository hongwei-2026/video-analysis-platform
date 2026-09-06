"""用 catalog 标题生成种子结构脚本，保证训练样本充足。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


TEMPLATES = [
    {
        "hook_type": "痛点",
        "pattern": "钩子-痛点-方案-证据-CTA",
        "beats": [
            ("开场钩子", "前3秒抛出痛点问题", "你是不是也遇到过……"),
            ("冲突/痛点", "放大焦虑", "普通方法根本没用"),
            ("解决方案", "引出产品/方法", "其实只要换个做法"),
            ("产品露出", "特写卖点", "关键是这一点"),
            ("证据/对比", "前后对比", "你看效果差在哪"),
            ("催单/CTA", "行动号召", "想要的扣1/链接放这"),
        ],
    },
    {
        "hook_type": "反差",
        "pattern": "结果先行-过程-对比-CTA",
        "beats": [
            ("开场钩子", "先给结果画面", "先看结果"),
            ("铺垫", "交代场景", "以前我一直……"),
            ("解决方案", "展示方法", "后来改成这样"),
            ("证据/对比", "左右对比", "差距一目了然"),
            ("催单/CTA", "转化", "同款在这"),
        ],
    },
    {
        "hook_type": "避雷测评",
        "pattern": "避雷声明-实测-结论-替代方案",
        "beats": [
            ("开场钩子", "避雷标题党", "别再被骗了"),
            ("冲突/痛点", "常见坑点", "商家不会告诉你"),
            ("证据/对比", "实测画面", "我们测了N天"),
            ("解决方案", "正确选购", "认准这几点"),
            ("催单/CTA", "收藏关注", "关注防踩坑"),
        ],
    },
]


def make_script(title: str, play: int, duration: int, tpl: dict) -> dict:
    beats = []
    t = 0
    step = max(duration // max(len(tpl["beats"]), 1), 3)
    for i, (role, visual, spoken) in enumerate(tpl["beats"], 1):
        beats.append(
            {
                "idx": i,
                "t_start_sec": t,
                "t_end_sec": t + step,
                "role": role,
                "visual": f"{visual}｜参考主题：{title[:40]}",
                "spoken_or_subtitle": spoken,
                "camera": "中景/特写切换",
                "emotion": "好奇",
                "product_visible": "产品" in role or "方案" in role,
                "person_visible": True,
            }
        )
        t += step
    return {
        "meta": {
            "estimated_duration_sec": duration or 60,
            "platform_style": "抖音",
            "language": "zh",
            "aspect_ratio": "9:16",
            "overall_hook_score": 8,
            "overall_retention_score": 7,
            "overall_conversion_score": 7,
            "genre": "种草",
            "one_line_summary": title,
            "ref_play": play,
        },
        "hook": {
            "type": tpl["hook_type"],
            "first_3s_script": tpl["beats"][0][2],
            "visual_hook": tpl["beats"][0][1],
            "audio_hook": "强节奏BGM+口播",
        },
        "beats": beats,
        "characters": [{"id": "P1", "role": "出镜主播", "appearance": "可替换", "replaceable": True}],
        "products": [{"id": "PR1", "name_guess": title[:20], "first_appear_sec": step, "selling_points": ["核心卖点"], "replaceable": True}],
        "script_skeleton": {
            "structure_pattern": tpl["pattern"],
            "spoken_script_full": "。".join(b[2] for b in tpl["beats"]) + "。",
            "cta": tpl["beats"][-1][2],
            "hashtags_style": ["种草", "避雷", "干货"],
        },
        "replication_notes": {
            "must_keep": ["前3秒钩子", "节拍结构", "CTA"],
            "can_replace": ["人物形象", "产品", "具体口播用词"],
            "shooting_checklist": ["竖屏", "字幕", "产品特写"],
        },
        "_synthetic": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default="data/catalog.json")
    ap.add_argument("--out", default="data/scripts")
    args = ap.parse_args()
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for i, row in enumerate(catalog):
        title = row.get("title") or row.get("bvid") or f"item{i}"
        bvid = row.get("bvid") or f"SYN{i:03d}"
        dur = int(row.get("duration") or 60)
        play = int(row.get("play") or 0)
        tpl = TEMPLATES[i % len(TEMPLATES)]
        data = make_script(title, play, dur, tpl)
        path = out / f"{bvid}_seed.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        n += 1
    print(f"[ok] wrote {n} seed scripts -> {out}")


if __name__ == "__main__":
    main()
