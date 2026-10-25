# Reference ClipFlow（对标短视频两阶段工作流）

一个可在本地/云电脑运行的开放式 Python + FFmpeg 工具。**仅做用户指定的视频处理，不上传视频/音轨到 GitHub 或其他服务器。**

## 两阶段，一键完成用户确认的1–5项需求

| 阶段 | 输入 | 默认执行 | 输出 |
|---|---|---|---|
| **1. 对标视频处理** | 一个参考 MP4 | 视觉镜头变化检测 + 对白句尾辅助切分（每段 ≤10s） + C方案水印（001…，40%白字、80%黑描边） + ASR/SRT | `numbered_segments.zip`、`captions.srt`、`manifest.json` |
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
clipflow --help
```

Mac：`brew install ffmpeg`；Ubuntu：`sudo apt install ffmpeg fonts-noto-cjk`。Windows可用 `winget install Gyan.FFmpeg` 并把ffmpeg加入PATH。

没有ASR环境时，可以先 `pip install -e .`，用 `--srt` 传入已经校对的字幕；**程序不会在无识别条件时编造SRT**。高级ASR可以选择 `--model large-v3`，但需要更多内存与算力。

## 阶段一：只给对标视频，获得编号片段ZIP + SRT

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
  numbered_segments.zip       # 001_镜头.mp4 ... NNN_镜头.mp4
  manifest.json               # 参考视频起止秒、序号、音轨/分辨率、方案C参数
  segments/                   # 单段MP4
    001_镜头.mp4
    002_镜头.mp4
```

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

需要**原声替换**时才追加 `--replace-audio`；需要**SRT文字合成**时才追加 `--burn-subtitles`。可同时指定两个选项：

```bash
clipflow assemble --clips-dir new_clips --out new_final.mp4 \
  --reference "对标原视频.mp4" --manifest project/manifest.json \
  --replace-audio --burn-subtitles --subtitle-style B
```

原声/新视频总时长若相差过大，程序会报错，防止无意裁掉画面。字幕合成会根据 `manifest.json` 将对标SRT的时间轴转换到新片段累计时间轴；如果字幕已经烧录在新片段里，可以使用 `--skip-existing-subs 2 5` 跳过指定片段的二次叠加，**不会尝试抹除已有硬字幕**。字幕外观B约为粗宋体、白字/黄绿色重点词、黑描边和3px字距；C约为特粗黑体。未确认样式时应在ChatGPT中预览并告知用户：对标字体很难百分之百反推。

如果用户明确取消去灰通透，可加 `--no-grade`。没有该参数，就**默认去灰通透**。`assemble` 只输出最终MP4，不默认生成1080P/60fps新版本。

## 与其他ChatGPT账号配合

请阅读同目录 `AGENTS.md` 和 `PROMPT_FOR_CHATGPT.md`。完整流程只能在拥有执行命令、处理本地视频和运行FFmpeg的环境中实际执行。只有聊天阅读能力的账号可以提供命令和解释，但**不能声称已经本地执行**。

GitHub仓库只发布程序源代码、测试和说明，**绝不包含原视频、用户声音、SRT内容、私有字体或密钥**。

## 验收标准

- 阶段1：编号连续、片段最长≤10秒、SRT字幕时间非负、原顺序连续覆盖；转场和句尾应抽查。
- 阶段2：各片段的排序可追溯、总时长约等于片段累加、不额外裁剪；不要求音轨替换和字幕时不得执行；调色标记为 simulated_dehaze。
- `*.report.json` 记录来源片段、排序方法、fps、处理选项和SHA256；不是对内容语义已人工审定的证明。

## License

MIT；依赖FFmpeg、OpenCV、faster-whisper 等各自遵循其许可证。发布包不附带字体文件或模型权重。
