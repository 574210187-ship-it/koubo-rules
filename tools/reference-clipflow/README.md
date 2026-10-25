# Reference ClipFlow v0.5.0｜纯画面字幕 OCR 版本

**已按用户要求回撤音频转文字功能：不再安装、下载或调用 Whisper、faster-whisper、云端 ASR 服务，也不从人声推测台词。** 文字只取自视频画面中真实可见的字幕，或用户主动提供的已核对 SRT。

## 固定工作流

| 输入 | 默认动作 | 交付 |
|---|---|---|
| 对标原视频 MP4 | 视觉镜头检测，最长每段不超过 10 秒；左上 001 起 C 方案灰白大号编号水印；画面字幕 OCR | `numbered_segments.zip`、**`segments_transcript.md`**、`manifest.json`、`subtitle_reference_stylekit.zip`；如有可信画面字幕，另有 `captions.srt` |
| 多个新视频 MP4 | 按编号顺序拼接、不额外裁切、不变速，默认模拟去灰通透 | 合成 MP4、校验报告 |

原声替换 `--replace-audio` 与字幕合成 `--burn-subtitles` 只有用户明确要求时才开启，不默认补帧或 60fps 重制。

## 新的台词 Markdown 规则

每次处理对标视频**始终生成同一个 `segments_transcript.md`**：第 001 段、第 002 段……每段只写一次原视频起止时间、片段文件名和该段画面字幕文字，**不再给每句话单独标时间**。例如：

```md
## 第001段｜00:00—00:06
- 视频：`001_镜头.mp4`

**台词：** （本段真正识别到的可见字幕）

## 第002段｜00:06—00:10
- 视频：`002_镜头.mp4`

**台词：** （本段真正识别到的可见字幕）
```

- **有画面字幕**：每个片段按其可见的画面字幕整理，去掉同一画面跨多帧造成的重复字句。机器 OCR 可能错字，需抽查原帧。
- **没有画面字幕**：仍生成上述 MD，但每段明确写“本段未检测到可识别画面字幕；口播内容未知”。**禁止从视频标题、上下文、人嘴动作或音频猜词。** `captions.srt` 也不会伪造为空白字幕。
- `captions.srt` 只在可靠 OCR 识别到画面字幕，或用户明确上传已核对 SRT 时生成。其时间是**画面上文字可见的时间**，不是配音原声的词级时间戳。
- 画面字幕 OCR 不是理解语音，识别到文字也不代表其与配音逐字一致。

## 程序依赖和安装（没有 ASR）

必需：Python ≥3.10、FFmpeg/FFprobe、OpenCV/Numpy、Tesseract OCR 执行程序和中文 `chi_sim` 语言包（可用 `--ocr-language HanS` 选择别的已装语言数据）、字体。其他依赖见 `pyproject.toml`。**没有 faster-whisper、PyTorch、Whisper 模型和云端 ASR 密钥需求。**

先检查现有工具；已存在则无需重复安装：

```bash
python -m clipflow.cli doctor
python -m pip install -e .   # 仅在 ClipFlow 项目尚未安装时执行；不会安装任何 ASR
```

Windows：Tesseract 安装后保证 `tesseract.exe` 可在 PATH 找到，并在其语言数据目录安装 `chi_sim.traineddata`；FFmpeg/FFprobe 同样加入 PATH。已安装无需重复配置。

## 对标处理

```bash
clipflow reference --input "对标视频.mp4" --out "project"
```

画面字幕不在默认中央偏下区域时可调整，坐标以画面宽高相对比例填写：

```bash
clipflow reference --input "对标视频.mp4" --out "project" --ocr-region 0.06 0.25 0.94 0.94
```

需要更密集抽样时调整 `--ocr-interval`，默认 0.55 秒：

```bash
clipflow reference --input "对标视频.mp4" --out "project" --ocr-interval 0.35
```

用户已经自行校对视频**可见画面字幕**，可显式使用 `--srt 已核对字幕.srt`；来源会记录为 `supplied_srt`，绝不标记成 OCR 或 ASR。

导出目录主要文件：

```text
project/
  numbered_segments.zip
  segments_transcript.md  # 每段视频仅一个标题/时间范围/台词块
  manifest.json           # 每段 transcript/transcript_status、OCR审计摘要
  subtitle_samples/       # 原视频帧截图与联系表
  subtitle_style_profile.json
  subtitle_reference_stylekit.zip
  captions.srt            # 仅在可见画面字幕可识别或提供已校对SRT时才存在
  segments/001_镜头.mp4 ...
```

切分优先视觉场景边界，OCR 字幕变化/消失时间可作为辅助候选；最长每段 9.8 秒。**纯画面模式不能声称已按音频句尾精准切分。** 自动镜头边界、OCR 文字需检查。

水印 C 方案：从 001 开始；灰白字 alpha 0.40、黑描边 alpha 0.80；横屏以 1920px 宽 10px 描边、竖屏以 1080px 宽 7px 描边，左上角。新视频拼接调色为模拟去灰通透，不是剪映私有滤镜。

## 新片段拼接

```bash
clipflow assemble --clips-dir new_clips --out new_final.mp4
```

顺序不明确时，按原规则优先数字命名，必要时提供 `--order-file`。只有用户明确指定才进行原声替换或字幕合成；字幕合成遵循**对标实际字形、大小、字重、间距、颜色、描边、位置与节奏**。无对标字幕时才使用后备样式，不得默认把统一彩色关键字强加到已有对标字幕上。

## 与其他窗口配合

以本文件和 `AGENTS.md` 为现行说明。不得使用旧 ASR 安装包或自动下载模型。下载/检查现有程序后，直接处理用户上传视频；无法从画面取得字幕时清晰记录原因，仍交付编号视频 ZIP 与逐段 MD。
