# Reference ClipFlow（对标短视频两阶段工作流）

一个可在本地/云电脑运行的开放式 Python + FFmpeg 工具。当前版本 **v0.4.6**，增加独立音频ASR、词级时间戳和逐片段台词MD。**仅做用户指定的视频处理，不上传私人视频或音轨到GitHub；只有已授权并配置云端ASR时才向专用服务传输音频分块。**

## 两阶段，一键完成用户确认的1–5项需求

| 阶段 | 输入 | 默认执行 | 输出 |
|---|---|---|---|
| **1. 对标视频处理** | 一个参考 MP4 | 三准则(>3且<=8秒／镜头优选／完整句尾)＋C方案水印＋音频ASR/SRT | **`ClipFlow_完整交付.zip` + ZIP外独立 `文案.txt`**（ZIP内分段MP4、每段开头截图、`captions.srt`、`segments_transcript.md`、`manifest.json`、`segments_list.csv`、字幕样张及样式配置）；另保留旧版独立ZIP兼容 |
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
# 输出 asr_only/captions.srt + asr_only/transcript.md + asr_only/文案.txt（纯台词）
```

## v0.4.6：交付独立TXT、从飞书多维表自检领取任务并回填

第一阶段处理完成时**必须同时提供两个独立文件**：`ClipFlow_完整交付.zip` 和 `文案.txt`。`文案.txt`是**纯口播文案**：只有从原声ASR或用户提供的校对SRT中取得的文字，每条字幕源台词一行；没有序号、时间、标题、文档标记、来源说明或其他解释。UTF-8无BOM，保留原始台词正常标点；SRT句末去标点仅作用于SRT，**不会改变TXT或逐段台词MD**。`文案.txt`存放在ZIP**外部**，不能打包进去。生成器拒绝缺少TXT的完整交付，ZIP读回拒绝误混入TXT。独立 `clipflow transcribe` 同时额外输出该纯文案TXT。

**新窗口默认从飞书多维表工作，而不是让用户在聊天框上传视频。** 用户会预先固定表格页面/列/输入附件/输出附件和`未完成`标记，ChatGPT先用已连接的MCP/CLI/API任一可行路径核对真实目标表的记录读取、素材完整下载、成品多附件上传和回读能力，通过后只处理标记为未完成的记录。第一阶段把完整ZIP和TXT分别追加到**该记录**的指定成品附件单元格；第二阶段把最终MP4、验收JSON等追加同样的输出位置。失败时HOLD，不能假装交付或强迫用户再次上传视频。

**目前处于字段绑定待定状态**：真实多维表URL、阶段列、状态/备注列、输入附件列和成品附件列尚未由用户确定，所以工具在代码库提供的是**可执行操作合同和启动指令，不是已连接指定表的生产调度器**。各账号需独立确认权限；只做授权范围自查不等于有权上传测试文件。特别是现有附件MCP视频/ZIP接口不代表能上传 `.txt`，必须另行实测或通过获授权的通用飞书附件CLI/API提供独立TXT，且读回成功后才能完成任务。详细步骤见 [`BITABLE_WORKFLOW.md`](BITABLE_WORKFLOW.md)，对应两条简短启动指令见 [`PROMPT_FOR_CHATGPT.md`](PROMPT_FOR_CHATGPT.md)。

## v0.4.5：全片三准则切分、开头前10帧文字最少

**第一阶段三条切分准则，同时满足**：

1. **每一段实际导出MP4都必须严格大于3.000秒、且小于或等于8.000秒**，包含最后一段；导出后要用FFprobe再次检查，`--max-seconds`默认8、不允许输入>8或<=3。短于等于3秒的原视频不能生成合格片段。
2. **镜头画面优先**：使用现有的画面场景变化检测提取画面切换候选，但不能单靠镜头变化切开正在讲的话。多处完整句尾符合时长规则时，优先选择靠近实际镜头切换的位置。
3. **台词必须讲完才能切**：非片尾切点必须具有可信的完整句终证据，取自尚未清理标点的ASR原始台词（或明确提供、已核对的SRT）及已有词级时间戳；字幕SRT的“每行显示结束”、句中逗号、分号、单独长停顿都不等于完整句子结束。动态规划在全片选择满足两项硬约束的路线，避免最后剩余<=3秒；若长句>8秒、只有不完整台词或尾段不可行，输出`cut_conflict.json`明确HOLD，拒绝生成不合格完整ZIP，绝不暗中硬切。ASR自动生成的语义标点仍可能出错，重要视频应抽查。

**每段开头代表截图规则**：仅查看原对标MP4该段开始后的**前10个实际解码帧**。先剔除明显黑场、闪白等不可用帧，然后使用**Tesseract中文OCR**对每帧原始画面统计可信文字字符数，优先选择**文字最少**的帧；如果字符数相同，再比识别字框面积、清晰稳定度及较早帧。完成选择后才加和对应MP4一样的左上角C方案编号水印001、002等，其他画面内容不改。`manifest.json`记录识别语言、前10帧索引、字符数和编号对应关系。OCR对小字、特殊字体可能漏检，不等于保证画面绝对零文字。

**必需环境**：除Python、FFmpeg/FFprobe外，截图文字选择需要Tesseract可执行文件，以及简体中文语言数据`chi_sim`或`HanS`。Python依赖安装`pytesseract`；Linux示例安装`tesseract-ocr`和`tesseract-ocr-chi-sim`，macOS或Windows安装对应Tesseract与中文语言文件。运行`clipflow doctor`核对环境；缺少OCR组件或中文模型时停止，不允许以清晰度旧逻辑假装已检测文字。云端Whisper只负责从音频识别讲话，不替代画面OCR。

## v0.4.4：所有SRT每条字幕末尾去标点（强制）

**统一导出规则**：无论来自云端/本地Whisper，还是用户提供的已校对SRT，最终写出的 `captions.srt` 每条字幕的**每个显示行结尾**都不保留中英文句号、感叹号、问号、逗号、省略号、引号等标点（连续多个一起去掉），句内逗号等仍保留。实现于唯一 `save_srt` 写出入口，剪映可以继续直接导入，原始SRT时间码与字幕顺序保持不变。只改SRT显示文字，不改录音ASR结果、原始输入文件及 `segments_transcript.md` 的完整台词内容。

示例：`大家好，我是姜律师。` → `大家好，我是姜律师`；`遇到合同纠纷怎么办？！` → `遇到合同纠纷怎么办`；`这个问题，我们来分析一下……` → `这个问题，我们来分析一下`。连续句尾符号、全角/半角标点均清理；没有识别到实质文字的纯标点字幕不会生成空白SRT条目。

该规则覆盖第一阶段输出目录中的 `captions.srt`、`ClipFlow_完整交付.zip` 内的SRT、兼容包 `subtitle_reference_stylekit.zip` 内的SRT，以及独立 `clipflow transcribe` 的SRT。ZIP写完后必须再次检查里面的SRT没有句末标点，且文件可正常打开和解压。**此处理不改变画面开头截图、分段视频序号水印、字幕样张或逐段台词MD。**

## v0.4.3：截图同步显示对应视频的左上角序号

第一阶段 `segment_stills/NNN_镜头.jpg` 必须叠加与 `segments/NNN_镜头.mp4` **完全一致的三位数编号和C方案水印**（左上角灰白大字、40%文字透明度、80%黑色描边；横屏1920宽时10px，竖屏1080宽时7px，按原画幅自适应）。

实现方式：先从对标原视频对应片段的开头前10帧挑选最干净的一帧，再用与MP4相同的 FFmpeg `drawtext_filter` 加编号。保留原始画幅/原字幕，不另做裁剪、调色或其他图像动画。截图编号与视频文件名、`manifest.json` 内的 `still_sequence_number`、`still_watermark_scheme=C` 必须一致；截图缺失、无法叠加编号或清单不一致均禁止交付完整ZIP。

## v0.4.2：每段视频增加开头干净截图

每次第一阶段导出的视频片段，必须同时生成**一段一张** `segment_stills/001_镜头.jpg`、`002_镜头.jpg`……，和 `segments/001_镜头.mp4` 等一一对应。

- **取帧范围**：从原视频中该片段起点往后 **开头前10个实际帧**，不从中后段截图；短片段只取段内真正存在的帧。
- **挑选原则**：用曝光、黑场/闪白检测、画面清晰度和帧间稳定度评分，优先避免黑屏、闪白、模糊和转场残影；同等质量优先靠近段首。该规则只代表技术筛选，不能保证人物一定没有闭眼或异常嘴型，重要项目仍需抽查。
- **截图质量**：保留原视频分辨率，以高质量JPEG输出，不缩放、不裁切、不重新调色；仅新增与对应视频完全相同的左上角C方案三位数编号水印；原视频中已存在的字幕和场景元素不擅自移除。
- **可追溯性**：`manifest.json` 各段记录截图路径、选中的原视频时间、段内偏移与原始帧序号；`segments_list.csv` 追加截图文件列。
- **强制验收**：`ClipFlow_完整交付.zip` 必须包含且仅包含每段对应的一张 JPG；数量、编号、非空文件、清单引用和ZIP CRC均校验。缺失或不匹配时必须报错，不将不完整ZIP作为成品交付。

## v0.4.1：第一阶段完整交付 ZIP（默认主交付）

不再让用户分别下载视频ZIP和字幕参考ZIP。处理一条对标视频，**必须首先交付两个独立文件：`ClipFlow_完整交付.zip` + ZIP外的 `文案.txt`**，它的内容固定为：

```text
ClipFlow_完整交付.zip
├── segments/001_镜头.mp4, 002_镜头.mp4, ...
├── segment_stills/001_镜头.jpg, 002_镜头.jpg, ...  # 每段开头前10帧中文字最少的一帧，左上角有与视频相同序号
├── captions.srt                  # 完整原视频时间轴，剪映导入
├── segments_transcript.md       # 只按片段分段台词，不给每句话标时间
├── manifest.json                # 机器可读切分清单及来源证据
├── segments_list.csv            # 简易切分清单（编号／文件／时间范围／时长／截图文件）
├── subtitle_style_profile.json  # 对标样式待审核配置
└── subtitle_samples/            # 联系表、原视频截图、样张索引
    ├── subtitle_reference_contact.jpg
    ├── cue_001_...jpg
    └── sample_index.json
```

**台词MD格式**：每个实际导出的片段一节，标题包含 `第001段｜00:00.000—00:06.500｜6.500秒`，下一行放视频文件名，正文只有该段对应的一段台词；不为每句写起止时间。片段内没有可信识别结果时必须明确标注，禁止编造。SRT仍保留逐条字幕的时间码，不受此改动影响。

**验收门禁**：ZIP采用临时文件原子写入；程序必须核实每个编号MP4非空、SRT/MD/清单/样张存在、编号连续且MD与片段数量匹配，再重新打开ZIP核对文件名单、大小与CRC；任何缺项立即报错，不能把半成品交给用户。ChatGPT输出下载链接前，还须确认实际文件路径在当前运行环境存在、可访问，并通过聊天附件/沙箱返回实际可下载文件；本地测试不能保证别的聊天账号拥有文件读取权限。

历史 `numbered_segments.zip` 和 `subtitle_reference_stylekit.zip` 暂时保留，仅用于兼容已有自动化，不再作为主要交付物。Cloud ASR已配置时仍从原声生成SRT与逐段台词；无ASR且未提供已校对SRT时必须报告阻塞，不可生成虚假的文字文件。

## 阶段一：对标视频 → 一个完整交付ZIP

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
  文案.txt                    # 独立纯文案，绝不进入完整ZIP
  captions.srt                 # 对标完整视频的可导入剪映字幕（UTF-8 BOM）
  segments_transcript.md      # 001...编号、原视频起止时间、每段时长与识别台词
  ClipFlow_完整交付.zip        # 与文案.txt并列主交付：分段MP4+开头截图+SRT+台词MD+清单+样张
  numbered_segments.zip       # 001_镜头.mp4 ... NNN_镜头.mp4
  manifest.json               # 参考视频起止秒、序号、音轨/分辨率、方案C参数
  subtitle_style_profile.json # 待视觉审核的对标样式配置（初始不作假定）
  subtitle_samples/           # 对标原帧截图与总览，供分析字体/颜色/位置
  subtitle_reference_stylekit.zip # SRT+逐段台词MD+manifest+样张+配置模板，可转交其他窗口
  segments/                   # 单段MP4
    001_镜头.mp4
    002_镜头.mp4
  segment_stills/             # 每段开头一张加有对应C方案编号水印的原画面JPG
    001_镜头.jpg
    002_镜头.jpg
```

### 无画面字幕时的真实音频识别与逐片段文案

- `reference` 未设置 `--srt` 时，使用已安装的本地 **faster-whisper** 从原视频音轨（FFmpeg自动提取16kHz单声道）识别中文。画面没有字幕并不影响；无需OCR，也不会把视觉识别文字冒充ASR。
- 自动输出 **`captions.srt`**（全文SRT时间轴）和 **`segments_transcript.md`**（一份Markdown，逐段包含`001｜00:00.000—00:06.500｜6.500秒`、MP4文件名、该段台词）。片段台词使用ASR词级时间戳按镜头时间分配，避免把完整SRT硬按字数切开；只有没有词时间戳或直接提供SRT时才做时间比例估算，文档明确标注。
- `manifest.json` 也记录每个片段的 `transcript`、`caption_source`、`transcript_alignment`，可供其他ChatGPT窗口或剪辑程序读取。台词文档还放进 `subtitle_reference_stylekit.zip`；编号视频ZIP仍只包含独立MP4。
- ASR可能误识别人名、方言、法律术语、数字；建议对照原声抽查。无法加载模型、没有可识别音轨或软件包未安装时明确报错，不生成假字幕。
- `--srt 已校对.srt` 继续支持：SRT和逐段台词MD正常生成，但标记为“用户提供SRT”，**不是本次音频识别结果**。

水印C方案：灰白大字左上角、文字alpha **0.40**，黑描边alpha **0.80**；在1920像素宽的横屏描边**10px**，1080像素宽的竖屏描边**7px**，字号随宽度缩放，序号从001开始。黑描边不意味着新增一层水印。

切分规则：每段严格>3且<=8秒，必须在确认完整句尾切分，并在合法句尾中优选镜头变化位置。无解必须HOLD。视觉检测和ASR不保证100%识别出人物/机位，`manifest.json` 中 `role` 默认“待确认”，必要时可以人工校对切点后重跑；不要把自动检测结果称作已人工核验。

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

**用户提示词无需重复整套规则**：见同目录 `PROMPT_FOR_CHATGPT.md` 中的两条极简启动词。同账号优先复用已安装的程序，其他账号只需传入公开仓库地址；收到对标视频自动走第一阶段，收到新片段自动走第二阶段。完整执行细则集中维护于 `AGENTS.md` 和本文件，不随提示词复制。

请阅读同目录 `AGENTS.md` 和 `PROMPT_FOR_CHATGPT.md`。完整流程只能在拥有执行命令、处理本地视频和运行FFmpeg的环境中实际执行。只有聊天阅读能力的账号可以提供命令和解释，但**不能声称已经本地执行**。

GitHub仓库只发布程序源代码、测试和说明，**绝不包含原视频、用户声音、SRT内容、私有字体或密钥**。

## 验收标准

- 阶段1：编号连续、每段实际时长严格>3且<=8秒、切点为可信句尾、SRT字幕时间非负、原顺序连续覆盖；逐段MD编号、时长、台词与manifest对应；语音来自ASR或已提供的SRT须准确标注；转场和句尾应抽查。
- 阶段2：各片段的排序可追溯、总时长约等于片段累加、不额外裁剪；不要求音轨替换和字幕时不得执行；调色标记为 simulated_dehaze。
- `*.report.json` 记录来源片段、排序方法、fps、处理选项和SHA256；不是对内容语义已人工审定的证明。

## License

MIT；依赖FFmpeg、OpenCV、faster-whisper 等各自遵循其许可证。发布包不附带字体文件或模型权重。


## 2026-10-26 实际部署验收

- **实际部署**：Vercel 独立项目 `clipflow-asr-private`；生产根地址 `https://clipflow-asr-private.vercel.app`，POST 接口 `/v1/transcribe?language=zh`。
- **服务器状态**：生产部署 READY、`GET /health` 返回 HTTP 200，Whisper Small 模型文件存在。
- **真实推理验证**：隔离预览部署使用临时合成普通话音频实际运行 Whisper，返回中文文本、词级 `start/end` 时间戳和语言 `zh`。机器人合成发音不自然造成个别识别错误，不能声称所有口播100%准确。
- **生产接口验收**：受保护的隔离测试客户端对生产URL发送真实POST音频请求；无密钥返回 401，有服务器密钥返回 200，返回 `captions`、`words`、`alignment=word_timestamps`、`language=zh`。这一测试覆盖生产网络、应用鉴权及实际推理接口，但没有验证每种真实人声/口音的准确率。
- **访问控制**：生产API向网络开放但要求应用Bearer密钥；Vercel预览环境仍由Vercel Authentication保护。未配置正确密钥的请求不能使用模型。服务限制每块最长30秒、最大3MB，处理音频使用临时文件，不把用户视频/音频提交到公开GitHub。
- **客户端接入（每个获授权运行环境配置一次）**：在安全环境变量中设置 `CLIPFLOW_ASR_URL=https://clipflow-asr-private.vercel.app` 及 `CLIPFLOW_ASR_API_KEY`（由所有者经安全渠道分配；不得将值写入提示词、README、ChatGPT聊天或公共仓库）。运行 `clipflow doctor` 检查客户端配置，再以 `clipflow transcribe` 或 `clipflow reference` 处理真实媒体。其他ChatGPT账号**不会自动继承密钥或Python运行环境**。
- **测试范围**：云端部署、中文语音识别引擎和生产API的有密钥/无密钥调用均已验收；不同ChatGPT账号的独立客户端接入仍须在各自已授权环境配置凭据并以实际视频确认，不能因为云端就绪就宣称所有账号已经自动连接。
- **保留两阶段行为**：水印拆分+SRT+逐段台词MD，第二阶段默认排序拼接+去灰通透；原声替换和字幕压制只在用户明确要求时执行，不默认60帧。

## v0.4.0：统一云端ASR（只需服务端部署一次模型）

**工作方式：** ClipFlow客户端从视频提取每段约20秒的16kHz单声道FLAC音频，以HTTPS和Bearer密钥发送至专用云端ASR服务；云端运行Whisper Small中文识别，返回带时间戳的文字。客户端仍在本地生成 `captions.srt`、`segments_transcript.md`、001起的分段水印ZIP。**原视频画面和视频片段不会传给ASR，也不上传GitHub。**

**自动选择：** 设置了`CLIPFLOW_ASR_URL`和`CLIPFLOW_ASR_API_KEY`时，`clipflow reference`及`clipflow transcribe`默认调用云端；没有配置时保留旧版本地faster-whisper。可通过`--asr-backend cloud`或`--asr-backend local`显式选择。失败时报告原因，不编造文字，也不偷偷转发到其他服务。

| 变量 | 放在哪里 | 用途 |
|---|---|---|
| `CLIPFLOW_ASR_URL` | 客户端安全环境变量 | 云端服务器HTTPS根地址 |
| `CLIPFLOW_ASR_API_KEY` | 客户端秘密管理系统 | 带权限的访问密钥（不要写入GitHub/提示词） |
| `CLIPFLOW_ASR_SERVER_KEY` | 云端容器秘密变量 | 校验客户端密钥；不设置时拒绝请求 |
| `CLIPFLOW_ASR_CHUNK_SECONDS` | 客户端可选 | 默认20秒，允许5—25秒，每块限3MB |
| `CLIPFLOW_ASR_SERVER_MODEL` | 服务端可选 | 默认 small；Docker构建时缓存模型 |

### 云端部署

项目提供 `Dockerfile.vercel` 供Vercel容器部署，也提供普通 `Dockerfile`。模型权重在镜像构建阶段下载一次，不要求各ChatGPT账号分别下载安装。**实际部署和在线使用可能产生云计算费用**，因此需要有授权的部署目标、平台秘密变量和实际中文音频验收；下载程序或通过离线测试并不代表服务已经上线。

Vercel建议单独新建ClipFlow ASR项目，将Git仓库Root Directory设为`tools/reference-clipflow`，使用container/Dockerfile.vercel。服务暴露`GET /health`和`POST /v1/transcribe?language=zh`（请求体为音频FLAC）。服务器要求Bearer鉴权，只接收最长30秒、≤3MB音频片段，完成后清除临时文件。可用Docker主机替代Vercel。请在平台密钥管理界面设置密钥，不要在聊天中粘贴。

**重要：** Cloud ASR仅能解决「每个账号不用各装模型」。其他ChatGPT账号仍需要能运行ClipFlow的文件/FFmpeg操作环境，以及能访问云端服务器的网络和授权凭据。云端没有真正部署、密钥没有配置、真实口播测试没有通过时，不能声称跨账号ASR已全面可用。音频发送到服务端必须获得用户授权并符合当地隐私要求；本地无云端配置时不发送任何音频。
