# Reference ClipFlow｜当前执行规则

唯一线上执行线定义在 [ONLINE_WORK_MODE.md](ONLINE_WORK_MODE.md)。任何执行窗口先读该文件；与它冲突的历史指令一律不执行。

## 范围

只处理第一阶段的原始对标 MP4 切分。禁止第二阶段拼接、调色、换声、烧字幕。WorkBuddy 不在本工作流中；浏览器只做 Work Mode 控制端到普通媒体页的原生附件交接。

## 质量合同

- 每段实际 FFprobe 时长：`3.000 < duration <= 8.000`；
- 非末段只能在可信完整句尾切；镜头变化是优先候选；无可行路线写 `cut_conflict.json` 并 HOLD；
- 每段 JPG 只从原片该段开头前10帧选中文 OCR 文字最少的一帧，选定后才加 C 同号水印；
- 可信 ASR 或用户校对 SRT 是完整句尾和纯文案的前提，视觉 OCR 不能替代；
- 正式成品仅为 `videos_and_screenshot.zip`、`supporting_materials.zip`、ZIP 外 `文案.txt`。

## 角色边界

- **Work Mode 控制端**：筛选/锁行、从飞书重建并核验源字节、控制云端浏览器原生附件交接、最终飞书读回验收。
- **普通 ChatGPT 媒体页**：仅处理已原生附入的一个 MP4，验证自身本地文件，运行 v0.4.8，append 三件成品。
- **浏览器**：只上传已核验的源 MP4 到该页面；不处理媒体、不写飞书。
- **飞书**：输入和结果持久层；只允许 append-only 成品上传与远端读回。
- **WorkBuddy**：不参与。

`chatgpt_widget_transfer_ready`、资源链接、临时 URL、源端 SHA 都不是媒体页已有输入文件的证据。输入只有在控制端重建→原生上传→媒体页 stat/SHA/ffprobe 全部通过后才能处理。

固定启动入口见 [PROMPT_FOR_CHATGPT.md](PROMPT_FOR_CHATGPT.md)。