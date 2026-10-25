# 其他聊天窗口启动词｜Reference ClipFlow v0.5.0（纯画面 OCR）

执行 Reference ClipFlow：优先使用本地已安装程序；如缺失或旧版本，再从已连接 GitHub 的 `574210187-ship-it/koubo-rules/tools/reference-clipflow` 获取最新版本，遵守 README.md 与 AGENTS.md。上传对标视频默认按视觉镜头切分为 ≤10 秒，C 方案水印，OCR 识别**原视频画面可见字幕**，交付 `numbered_segments.zip` 与**每段对应一个时间范围、一整段台词的 `segments_transcript.md`**（以及 manifest；有可见字幕才生成 SRT）。没有字幕要据实写未知，绝不使用音频 ASR。上传新视频片段默认按序完整拼接和去灰通透调色；原声替换及字幕合成仅明确要求时做，字幕样式以对标为准；不默认60fps。不要重复安装已有程序。
