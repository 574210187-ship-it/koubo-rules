# Reference ClipFlow｜执行合同（v0.4.8）

本目录只处理第一阶段：从已经绑定的飞书多维表取得一条原始对标 MP4，按固定质量合同切分，并把最终三件成品追加回**同一条记录**。不执行第二阶段，不拼接新视频、不换声、不调色、不烧字幕。WorkBuddy、浏览器多页面调度不属于本版本。

## 最终交付：恰好 2 ZIP + 1 TXT

成功时只把下列三件作为正式对外交付并回填成品附件格：

1. `videos_and_screenshot.zip`：只包含 `segments/` 下连续编号的 MP4 和 `segment_stills/` 下同编号 JPG；每段视频与一张截图一一对应。
2. `supporting_materials.zip`：包含 `captions.srt`、`segments_transcript.md`、`manifest.json`、`segments_list.csv`、`subtitle_style_profile.json` 和 `subtitle_samples/` 的全部支持材料。
3. `文案.txt`：独立于两个 ZIP；UTF-8 无 BOM；每行只是一条可信原始口播文本，不含编号、时间码、文件名、Markdown、标题或解释。

`文案.txt` 绝不能进入 ZIP。不得交付旧的 `ClipFlow_完整交付.zip`、`numbered_segments.zip` 或 `subtitle_reference_stylekit.zip` 作为额外正式成品。

## 不可放宽的媒体合同

- 每段**实际 FFprobe 时长**严格 `> 3.000s && <= 8.000s`。
- 非片尾切点只能是可信原始 ASR 或人工校对 SRT 的完整句尾；镜头变化只是候选优先级。没有同时满足条件的路线，写出 `cut_conflict.json` 并 HOLD，不硬切、不放宽时长。
- 每段 JPG 只从该段原视频开头连续前 10 帧中选取：先排除黑场/闪白，再按中文 OCR 可见文字最少、文字面积最小、清晰稳定、较早帧排序；**选中后**才加 C 方案同号水印。
- 需要可信 ASR（或用户提供的校对 SRT）才能证明完整句尾并生成纯文案。视觉 OCR 不可替代音频句尾证据。
- 交付前必须逐段验证时长、编号、MP4/JPG 对应关系、SRT、manifest、两个 ZIP 的成员和 CRC，以及 ZIP 外 TXT 的 UTF-8 纯文本属性。

## Work Mode 纯线上执行

唯一正式操作说明是 `ONLINE_WORK_MODE.md`，固定启动文本是 `PROMPT_FOR_CHATGPT.md`。在已连接飞书 MCP 的 Work Mode 窗口中，流程为：

`剧情视图筛选 → 锁定一条 → 原生文件桥验收 → clipflow reference → 本地三件验证 → 同记录追加上传 → 远端逐件 SHA-256 读回`

输入桥只有在处理运行时能对源 MP4 实际执行路径读取、字节数、SHA-256 和 ffprobe 时才通过。仅返回 `chatgpt_widget_transfer_ready`、临时 URL、resource link 或源端 SHA 都是 `INPUT_BRIDGE_HOLD`，不得开始处理或写任何成品。一个运行窗口串行处理，失败只 HOLD 当前记录；不得跳过、猜字段、修改受保护业务字段、覆盖或删除既有附件。

## 代码入口

`clipflow reference --input <source.mp4> --out <out-dir>` 生成三件最终交付。打包由 `clipflow.delivery.build_final_delivery_packages` 负责。它拒绝时长/截图元数据/manifest/样张/CRC/文案约束不合格的输出。

所有远端上传都是 append-only；完成仅以目标记录读回的文件名、大小、完整 SHA-256 与本地一致为准。没有读回，不得报告完成。
