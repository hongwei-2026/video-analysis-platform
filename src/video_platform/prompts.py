"""爆款短视频结构拆解 Prompt —— 输出可训练的结构化脚本 JSON。"""

DISSECT_SYSTEM = """你是资深短视频编导与数据分析师。你的任务是把一条短视频拆解成「可复刻的结构脚本」，用于：
1) 换人物/换产品的一键复刻；
2) 作为训练「爆款脚本生成小模型」的语料。

要求：
- 只依据视频画面与可感知的旁白/字幕/音效节奏分析，不要编造无法从视频推断的事实。
- 时间尽量用秒（可估算），结构字段必须完整。
- beats 数组每个元素内容必须互不重复，禁止用「口播或字幕要点」等占位符敷衍。
- 短视频越长，beats 越多（约每 8–15 秒一个 beat）。
- 输出必须是合法 JSON（不要 Markdown 代码围栏，不要多余解释）。
"""

DISSECT_USER = """请深度拆解这条短视频，输出如下 JSON（字段齐全）：

{
  "meta": {
    "estimated_duration_sec": 0,
    "platform_style": "抖音/快手/小红书/未知",
    "language": "zh",
    "aspect_ratio": "9:16|16:9|其他",
    "overall_hook_score": 1,
    "overall_retention_score": 1,
    "overall_conversion_score": 1,
    "genre": "种草|口播|剧情|测评|教程|混剪|其他",
    "one_line_summary": "一句话：谁向谁推销什么/讲什么"
  },
  "hook": {
    "type": "痛点|反差|悬念|利益点|冲突|结果先行|其他",
    "first_3s_script": "开场前3秒具体口播/字幕原文",
    "visual_hook": "开场画面具体描述",
    "audio_hook": "音效/BGM/语气特点"
  },
  "beats": [
    {
      "idx": 1,
      "t_start_sec": 0,
      "t_end_sec": 0,
      "role": "开场钩子|铺垫|冲突/痛点|解决方案|产品露出|证据/对比|催单/CTA|彩蛋",
      "visual": "本段画面：人物、场景、产品、字幕（具体）",
      "spoken_or_subtitle": "本段口播或字幕原文（尽量完整）",
      "camera": "特写|中景|运镜|切镜",
      "emotion": "情绪",
      "product_visible": false,
      "person_visible": false
    }
  ],
  "characters": [
    {
      "id": "P1",
      "role": "出镜主播|配角|路人",
      "appearance": "年龄感、穿着、表情、站位",
      "replaceable": true
    }
  ],
  "products": [
    {
      "id": "PR1",
      "name_guess": "产品品类或名称",
      "first_appear_sec": 0,
      "appear_moments": ["第几秒如何露出"],
      "selling_points": ["卖点1", "卖点2"],
      "replaceable": true
    }
  ],
  "script_skeleton": {
    "structure_pattern": "钩子-痛点-方案-证据-CTA",
    "spoken_script_full": "全片口播/字幕串联成可朗读稿，尽量完整",
    "cta": "结尾行动号召原文",
    "hashtags_style": ["风格标签"]
  },
  "replication_notes": {
    "must_keep": ["必须保留的节奏/结构点"],
    "can_replace": ["可换人物/产品/场景"],
    "shooting_checklist": ["拍摄清单条目"]
  }
}

重要：每个 beat 写真实内容，不要复制 JSON 字段名当正文。
每个 beat 的 visual 至少 40 字，spoken_or_subtitle 写出口播/字幕原文（至少 20 字）。
spoken_script_full 必须串联全片口播，不少于 120 字。开始分析。
"""


def build_messages(video_path: str, fps: float | None = None, max_frames: int = 96):
    """构造 Qwen-VL 多模态消息。"""
    from src.studio_pipeline.dissect_service import build_dissect_system

    video_item: dict = {"type": "video", "video": video_path}
    if max_frames:
        video_item["max_frames"] = max_frames
    if fps:
        video_item["fps"] = fps

    return [
        {"role": "system", "content": [{"type": "text", "text": build_dissect_system()}]},
        {
            "role": "user",
            "content": [
                video_item,
                {"type": "text", "text": DISSECT_USER},
            ],
        },
    ]
