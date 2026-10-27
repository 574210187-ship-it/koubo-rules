# 实况视频单窗口｜精简版 v1.3.1 候选

启动口令：**启动实况 REVIEW**（默认）或 **启动实况 AUTO**。

**只做三件事：** 00 文字和大概位置分析 → 01 生成三张（可选四张）透明PNG供用户挑选 → 02 用户把选中PNG发回来并说“用这张图片生成视频”，直接合成1080P MP4和包含同MP4的ZIP。

00需要用户说“00通过”。在01必须用 ImageGen 实际生成3～4张**各自独立**的透明PNG，不是三图拼图，也不使用Python/JSON绘字。此时等用户挑选、复制粘贴上传选中的那张；以用户刚上传的那张为准，不二次生图。收到“用这张图片生成视频”后无需再次询问，直接执行02。

两条视频按有无清晰正文判断主/对标，不依赖上传顺序。若提供主视频+对标图片直接识别。用户在00额外说替换哪个字，00更新文字即可。两视频都很有字、都没字、或字幕动态不清时才停00问必要问题。

本版**保留原视频完整时长**、不变速，文字从头到尾静止，使用主视频原音。输出1080P（竖屏1080×1920/横屏1920×1080）。没有其他风格分支，没有背景图或单独成品图，不做转场、光效、额外文案。

REVIEW：00等用户通过、01等用户选图。AUTO：00可自动进入01，但**也必须等用户选图片**，不能自作主张选择。任何错误停当前阶段，修好继续同一任务。该工具包不自动获得其他ChatGPT账号的ImageGen或FFmpeg权限，不能执行就说清楚。

执行命令及最简示例见 `README.md`。原v1.2旧版继续作为独立历史存档，不随包内复制。

公开下载入口（固定版本）：https://github.com/574210187-ship-it/koubo-rules/tree/shikuang-public-v1.3.1/projects/shikuang-singlewindow

完整启动ZIP：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.3.1/projects/shikuang-singlewindow/releases/shikuang-simple-v1.3.1-candidate.zip