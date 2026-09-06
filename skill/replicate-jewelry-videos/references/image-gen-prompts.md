# 生图与生视频提示词

## Phase A — 仅替换产品

**模板（中文，供 Agnes Image / 即梦图像使用）：**

```
竖屏电商饰品短视频静帧。保持原构图与光线：{scene_lighting}。
人物：{subject_pose_clothing}。
手部动作：{hand_motion}。
产品替换为：[PRODUCT]{product_identity_block}[/PRODUCT]。
要求：产品清晰对焦，反光自然，白平衡与参考帧一致，9:16，高清，无文字水印。
负面：变形首饰、多余件数、错误颜色、模糊产品、多指、畸形手。
```

`product_identity_block` 从 `product_identity.json` 拼接。

**运动提示词（供视频模型，Phase A 预览可选）：**

```
Cinematic vertical 9:16 jewelry product shot. {camera_motion}.
Subject: {subject_summary}. Hand gently moves {{PRODUCT_SLOT}} to catch soft light.
Keep product shape stable, no morphing. Natural micro-shake like smartphone footage.
```

## Phase B — 背景替换

在 Phase A 已确认图上追加：

```
在保持产品与手部完全不变的前提下，将背景与道具调整为：
服装→{new_outfit}；桌面/家具→{new_props}；花材→{new_flowers}。
整体色温{warmth}，保持带货短视频质感，不要复制原视频布景。
负面：改变产品、改变手部姿势、品牌 logo。
```

## 视频生成 motion prompt（分镜确认后）

```
Vertical 9:16 jewelry commerce clip, {duration}s.
Scene: {scene_summary}. Camera: {camera_motion}.
Action: {action_physics}. Product: [PRODUCT]{product_identity_block}[/PRODUCT].
Audio mood: {audio_mood}. Smooth motion, stable product geometry, realistic hands.
```

## 与平台字段映射（视频分析平台）

| Skill 字段 | 平台 JSON 字段 |
|------------|----------------|
| scene_lighting | beat.visual |
| hand_motion | beat.motion_prompt |
| product_identity_block | products[0] + 用户资产 |
| camera_motion | beat.motion_prompt |
