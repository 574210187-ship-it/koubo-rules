# 实况视频单窗口｜v1.2.0-1080p-mp4zip-candidate

> 公开候选入口。版本锁定，不包含任何用户原始视频/图片或凭据。

**完整启动ZIP（固定版）**：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.2.0/projects/shikuang-singlewindow/releases/shikuang-singlewindow-v1.2.0-1080p-mp4zip-candidate.zip

**ZIP SHA-256**：`fb87c590d94dce409072fb9ac7919d4287714446b412745facc4acf0799802ec`

**当前公共目录**：https://github.com/574210187-ship-it/koubo-rules/tree/shikuang-public-v1.2.0/projects/shikuang-singlewindow

## 启动口令（REVIEW/AUTO二选一）
下载并加载上方完整ZIP并逐字节核对 SHA-256；读取其中 START_HERE.md、rules/00～04、config/project.json、config/routes.json、config/engines.json、distribution/PUBLIC_USAGE.md，然后执行“启动实况 REVIEW”（人工验收）或“启动实况 AUTO”（自动质检）。用户上传一条主视频加一条有文字的对标视频或图片，自动从00识别角色开始。

## 业务规则（以此v1.2.0版本为准）
1. 两个视频时，有明显可读正文的是对标视频，基本没有正文的是主视频；不按文件名或上传次序硬判。有歧义停在00。
2. 00：锁定主/对标媒体SHA；从原图/原视频帧逐字提取正文、文字相对位置、比例、行距、样式；优先应用本轮用户明确改字要求。REVIEW 等待00确认。
3. 01：**仅用ImageGen**生成真实 RGBA 透明文字 PNG，同主视频比例，大小和位置尽量贴近对标；不得使用Python/PIL/JSON排文字替代ImageGen，亦不能生成流程示意图；对照原图逐字/布局/透明通道QA，REVIEW等待图片通过，局部返工不重新启动。
4. 02：透明 PNG 从第1帧到最后一帧完全静止叠加到主视频；不滚动、不逐字出现、不做淡入淡出/移动/光效；不加速不减速，主视频**原始完整时长**，保留原声（如有）。
5. 03：固定输出**1080P MP4**（竖屏1080×1920，横屏1920×1080）及**包含相同MP4的ZIP**两个独立文件；检查分辨率、时长、音轨、关键帧、完整解码、SHA；错误停在当前阶段，保留上游通过产物。
6. REVIEW关键点人工确认；AUTO仅在ImageGen、视觉QA、ffmpeg及**正式批准的视频引擎**齐备时自动连续运行，缺权限/引擎未批准必须原位阻断。

## 限制与版本边界
- 本版本的引擎状态仍是 `CANDIDATE_NOT_APPROVED`；软件与测试存在不等于生产全自动已验收，不能擅自升格。
- 当前 ZIP 中个别旧分发元数据（如 distribution/TARGETS.json）可能仍引用 v1.0.2 公共地址；**不得把旧版链接当作本版ZIP**。版本识别必须以本页固定ZIP及SHA为准；发现运行合同冲突应报告而不是混用代码。
- 其他 ChatGPT 账号无权自动读取本账号的私有 Space。若新账号无法直接下载 ZIP，请先从上方链接下载后以文件形式附给它；仅能读网页不意味着能执行 Python、ffmpeg、ImageGen。
- 若用户需要此前“2.9秒/小于3秒”版本，应显式改用已归档的 v1.0.2，而不是混用两个版本。
