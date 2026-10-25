# Reference ClipFlow（对标短视频两阶段工作流）

一个可在本地/云电脑运行的开放式 Python + FFmpeg 工具。当前版本 **v0.3.0**，增加独立音频ASR、词级时间戳和逐片段台词MD。**仅做用户指定的视频处理，不上传视频/音轨到 GitHub 或其他服务器。**

## 两阶段，一键完成用户确认的1–5项需求

| 阶段 | 输入 | 默认执行 | 输出 |
|---|---|---|---|
| **1. 对标视频处理** | 一个参考 MP4 | 视觉镜头变化检测 + 对白句尾辅助切分（每段 ≤10s） + C方案水印（001…，40%白字、80%黑描边） + ASR/SRT | `numbered_segments.zip`、`captions.srt`、**`segments_transcript.md`（编号+时间+台词）**、`manifest.json`、字幕样张及样式配置模板（可一键下载 `subtitle_reference_stylekit.zip`） |
| **2. 新片段合成** | 多个新视频MP4 | 排序 → **原样完整拼接**（不变速、不额外裁切） → 模拟「去灰通透」调色 | 合成MP4、验收报告JSON |

两个**明确可选项**：**原视频声音替换** `--replace-audio` 与 **字幕压制** `--burn-subtitles`。未要求时两者**都不做**；不会自作主张叠字或换音轨。

不做 60fps、不默认AI补帧、不调用剪映的私有滤镜；「去灰通透」是近似的可复现 FFmpeg 调色，不是剪映内部效果。保留新视频原始分辨率、帧率、画面长度（以技术编码容差为限）。

## 安装

**必要环境：** Python 3.10+、系统 `ffmpeg` + `ffprobe`（建议版本5及以上）、中文/英文系统字体。首次做ASR需要网络下载Whisper模型。CPU可以运行，大视频耗时与设备性能有关。

```bash
# 解压本仓库的 reference-clipflow-release.zip 后进入所在目录
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e '.[asr]'
clipflow doctor
clipflow --help
```

Mac：`brew install ffmpeg`；Ubuntu：`sudo apt install ffmpeg fonts-noto-cjk`。Windows可用 `winget install Gyan.FFmpeg` 并把ffmpeg加入PATH。

可选择一次性安装+缓存模型（有网络时）：`python scripts/setup_asr.py --model small`，之后其他视频直接复用缓存。`clipflow doctor` 只检查软件是否存在，并不代表模型已下载成功。`faster-whisper` 默认使用 **CPU int8**；有GPU的环境可选 `--device cuda`。模型首次下载需要能访问对应权重站点（通常为 Hugging Face）；在隔离环境可将离线准备好的模型目录传给 `--model /本地/模型目录`。

**重要：** 没有ASR环境时，可以先 `pip install -e .`，用 `--srt` 传入已经校对的字幕；**程序不会在无识别条件时编造SRT**。高级ASR可选 `--model large-v3`，但需要更多内存与算力。画面有没有字幕与识别原声音频是两回事：只要音轨存在，省略 `--srt` 就执行真实音频识别。

独立语音转文字（不拆视频）：

```bash
clipflow transcribe --input "无字幕的原视频.mp4" --out "asr_only" --model small --language zh
# 输出 asr_only/captions.srt + asr_only/transcript.md（逐条字幕时间与台词）
```

## 阶段一：只给对标视频，获得编号片段ZIP + SRT + 逐段台词MD

```bash
clipflow reference --input "对标原视频.mp4" --out "project" --model small --language zh
```

如果有更准的字幕文件，可选择它替代自动识别：

```bash
clipflow reference --input "对标原视频.mp4" --out "project" --srt "人工核对.srt"
```

输出示例：

```text
project/
  captions.srt                 # 对标完整视频的可导入剪映字幕（UTF-8 BOM）
  segments_transcript.md      # 001...编号、原视频起止时间、每段时长与识别台词
  numbered_segments.zip       # 001_镜头.mp4 ... NNN_镜头.mp4
  manifest.json               # 参考视频起止秒、序号、音轨/分辨率、方案C参数
  subtitle_style_profile.json # 待视觉审核的对标样式配置（初始不作假定）
  subtitle_samples/           # 对标原帧截图与总览，供分析字体/颜色/位置
  subtitle_reference_stylekit.zip # SRT+逐段台词MD+manifest+样张+配置模板，可转交其他窗口
  segments/                   # 单段MP4
    001_镜头.mp4
    002_镜头.mp4
```

### 无画面字幕时的真实音频识别与逐片段文案

- `reference` 未设置 `--srt` 时，使用已安装的本地 **faster-whisper** 从原视频音轨（FFmpeg自动提取16kHz单声道）识别中文。画面没有字幕并不影响；无需OCR，也不会把视觉识别文字冒充ASR。
- 自动输出 **`captions.srt`**（全文SRT时间轴）和 **`segments_transcript.md`**（一份Markdown，逐段包含`001｜00:00.000—00:06.500｜6.500秒`、MP4文件名、该段台词）。片段台词使用ASR词级时间戳按镜头时间分配，避免把完整SRT硬按字数切开；只有没有词时间戳或直接提供SRT时才做时间比例估算，文档明确标注。
- `manifest.json` 也记录每个片段的 `transcript`、`caption_source`、`transcript_alignment`，可供其他ChatGPT窗口或剪辑程序读取。台词文档还放进 `subtitle_reference_stylekit.zip`；编号视频ZIP仍只包含独立MP4。
- ASR可能误识别人名、方言、法律术语、数字；建议对照原声抽查。无法加载模型、没有可识别音轨或软件包未安装时明确报错，不生成假字幕。
- `--srt 已校对.srt` 继续支持：SRT和逐段台词MD正常生成，但标记为“用户提供SRT”，**不是本次音频识别结果**。

水印C方案：灰白大字左上角、文字alpha **0.40**，黑描边alpha **0.80**；在1920像素宽的横屏描边**10px**，1080像素宽的竖屏描边**7px**，字号随宽度缩放，序号从001开始。黑描边不意味着新增一层水印。

切分优先顺序：连续镜头、完整句子、每段强制小于10秒。视觉检测和ASR不保证100%识别出人物/机位，`manifest.json` 中 `role` 默认“待确认”，必要时可以人工校对切点后重跑；不要把自动检测结果称作已人工核验。

## 阶段二：只给新视频片段，默认拼接+去灰通透

如果片段名为 `001_xxx.mp4`、`002_xxx.mp4`…，直接自动排序：

```bash
clipflow assemble --clips-dir "new_clips" --out "new_final.mp4"
```

如果片段文件名随机，但仍有与参考视频一致的原声，可带上参考视频尝试音频匹配排序，**这不代表要原声替换**：

```bash
clipflow assemble --clips-dir "new_clips" --reference "对标原视频.mp4" --out "new_final.mp4"
```

若音频改变或匹配分数过低，程序会停止并要求显式顺序清单，而不是乱序拼接：

`order.txt` 每行一个文件名，第一行即第001段；然后运行：

```bash
clipflow assemble --clips-dir "new_clips" --order-file order.txt --out "new_final.mp4"
```

## 字幕规则：对标优先，而不是固定 C/B/B 或84px

- **对标视频有可见字幕**：先查看第一阶段 `subtitle_samples/` 内的原分辨率截图及总览。按实际对标逐项核对 **字体字形或可用的最接近字体、粗细、尺寸比例、字距、横纵位置、单行/多行、描边、阴影、常规字色、逐词/逐句强调色、显示时机**。不能仅凭用户场景或此前视频套用 C/B/B、84/94px、固定黄绿色关键词。
- **对标字幕分段颜色不同**：在 `subtitle_style_profile.json` 的 `caption_styles` 中写每条字幕专用 `runs`（每个词组颜色/字号），或覆盖该条 `highlight_terms`，而不是默认把“律师/合同”等词一律变色。允许字幕全白、全黄、蓝字、渐变近似色等具体对标方案。
- **对标没有字幕**：经查看截图确认后，将 JSON 内 `reference_has_subtitles=false`、`visually_reviewed=true`；此时才使用后备样式（此前约84/94px、白字和黄绿色强调、黑描边、少量字间距，按画幅自适应）。
- **有字幕但字体名称无法确定**：优先匹配可见字形；选择合法安装的最相近字体，记录“近似”，不要声称100%识别出原始字体；涉及商业字体需用户自行取得合法授权。
- **样张未复核**：`reference_has_subtitles` 初始为 `null`；执行字幕合成会主动停止，防止悄悄退回固定B字模。新ChatGPT账号应先完成该文件的视觉核验。只拼接不加字幕时不受影响。
- **时间轴和内容独立于外观**：依然用 SRT/原声时间对齐；对标硬字幕已在新片段画面里时优先不重复叠加；遇到不确定的样式先给两三帧对照样张。

### 对标样式的工作方法

第一阶段会自动生成：

```text
project/subtitle_samples/subtitle_reference_contact.jpg
project/subtitle_samples/cue_001_...jpg  # 原分辨率帧
project/subtitle_style_profile.json      # 初始状态 pending，须视觉确认
```

视觉确认后填入 JSON（详见 `examples/subtitle_style_profile_example.json`），包括 `source_canvas_width/height`、`font_family`、`font_size_px`、`letter_spacing_px`、`position_x_ratio/y_ratio`、描边和颜色。`caption_styles` 可逐条重写样式；`runs` 必须拼起来与该条 SRT 原文完全相同，保证颜色位置不乱。

**该版本并没有声称可以用纯FFmpeg自动反查字体名称**：ChatGPT需要读取样张并判断，程序将经审阅的样式按参数应用。尺寸按对标分辨率比例缩放，并在长句超边时自动收缩。ASS支持静态字体、色块、描边、阴影和淡入淡出；特殊三维字体、复杂关键帧动画和剪映私有效果需要另外处理。

### 第二阶段字幕合成示例

需要**原声替换**时才追加 `--replace-audio`；需要**SRT文字合成**时才追加 `--burn-subtitles`。可同时指定两个选项：

```bash
clipflow assemble --clips-dir new_clips --out new_final.mp4 \
  --reference "对标原视频.mp4" --manifest project/manifest.json \
  --replace-audio --burn-subtitles
```

当 `--manifest project/manifest.json` 存在时，程序自动读取同目录已经核验的 `subtitle_style_profile.json`；也可以通过 `--subtitle-profile path/to/style.json` 显式指定。**样式选择顺序：经审核的对标配置 > 对标明确无字幕时的后备方案**。当完全没有对标视频但明确要求叠加字幕时，可按后备方案处理。

原声/新视频总时长若相差过大，程序会报错，防止无意裁掉画面。字幕合成会根据 `manifest.json` 将对标SRT的时间轴转换到新片段累计时间轴；如果字幕已经烧录在新片段里，可以使用 `--skip-existing-subs 2 5` 跳过指定片段的二次叠加，**不会尝试抹除已有硬字幕**。**只有确认对标无字幕时**才使用此前的B或C后备字模；不再固定指定C/B/B或84px。视觉确认、关键词颜色和字体可用性需要如实记录。

如果用户明确取消去灰通透，可加 `--no-grade`。没有该参数，就**默认去灰通透**。`assemble` 只输出最终MP4，不默认生成1080P/60fps新版本。

## 与其他ChatGPT账号配合

请阅读同目录 `AGENTS.md` 和 `PROMPT_FOR_CHATGPT.md`。完整流程只能在拥有执行命令、处理本地视频和运行FFmpeg的环境中实际执行。只有聊天阅读能力的账号可以提供命令和解释，但**不能声称已经本地执行**。

GitHub仓库只发布程序源代码、测试和说明，**绝不包含原视频、用户声音、SRT内容、私有字体或密钥**。

## 验收标准

- 阶段1：编号连续、片段最长≤10秒、SRT字幕时间非负、原顺序连续覆盖；逐段MD编号、时长、台词与manifest对应；语音来自ASR或已提供的SRT须准确标注；转场和句尾应抽查。
- 阶段2：各片段的排序可追溯、总时长约等于片段累加、不额外裁剪；不要求音轨替换和字幕时不得执行；调色标记为 simulated_dehaze。
- `*.report.json` 记录来源片段、排序方法、fps、处理选项和SHA256；不是对内容语义已人工审定的证明。

## License

MIT；依赖FFmpeg、OpenCV、faster-whisper 等各自遵循其许可证。发布包不附带字体文件或模型权重。
