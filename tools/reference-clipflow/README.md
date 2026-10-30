# Reference ClipFlow v0.4.8

ClipFlow 只做第一阶段：把一条原始对标 MP4 按严格合同切成编号短片。唯一线上执行线、固定提示词和飞书绑定分别见：

- [ONLINE_WORK_MODE.md](ONLINE_WORK_MODE.md) — 唯一正式流程母本
- [PROMPT_FOR_CHATGPT.md](PROMPT_FOR_CHATGPT.md) — Work Mode 启动词
- [BITABLE_WORKFLOW.md](BITABLE_WORKFLOW.md) — 表字段与回填合同

不要使用仓库或历史聊天中的其它流程描述。

## 输出

一次合格处理的正式交付恰好三件：

| 文件 | 内容 |
|---|---|
| `videos_and_screenshot.zip` | `segments/` 中连续编号 MP4 与 `segment_stills/` 中同编号 JPG，且仅这些媒体文件 |
| `supporting_materials.zip` | SRT、逐段 MD、manifest、CSV、样式和样张等其余支持材料 |
| `文案.txt` | ZIP 外、UTF-8 无 BOM、逐行纯台词 |

旧 `ClipFlow_完整交付.zip`、`numbered_segments.zip`、`subtitle_reference_stylekit.zip` 不是当前成品。

## 媒体合同

- 每段实际编码时长严格大于 3 秒、且不高于 8 秒；
- 切点优先贴近镜头变化，但只能是可信完整句尾；没有合法方案即输出 `cut_conflict.json` 并 HOLD；
- 每段截图仅从该段原视频开头连续前10帧中，以中文 OCR 可见文字最少优先选择，选中后才加 C 同号水印；
- 可信 ASR 或用户校对 SRT 是句尾和 `文案.txt` 的前提，视觉 OCR 不能编造口播。

## 本地运行

需要 Python 3.10+、FFmpeg/FFprobe、Tesseract 中文语言包与可信 ASR 或校对 SRT：

```bash
pip install -e '.[asr,test]'
clipflow reference --input source.mp4 --out delivery --model small --language zh
# 或：clipflow reference --input source.mp4 --out delivery --srt checked.srt
pytest -q tests/test_delivery.py
```

## 线上边界

当前已验证的输入桥不是普通 ChatGPT 页面直接调用飞书物化。它是：

```text
飞书附件字节 → Work Mode 控制端下载/重建+SHA核验
→ 云端浏览器原生上传 → 普通 ChatGPT 媒体页再次核验
→ ClipFlow → 飞书 append + 控制端远端 SHA 读回
```

这条线全程云端、无需 WorkBuddy。