# 实况视频单窗口｜v1.0.2-public-candidate｜跨账号公开入口

公开规则入口：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.0.2/projects/shikuang-singlewindow/START_HERE.md
公开 ZIP：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.0.2/projects/shikuang-singlewindow/releases/shikuang-singlewindow-v1.0.2-public-candidate.zip
公开项目目录：https://github.com/574210187-ship-it/koubo-rules/tree/shikuang-public-v1.0.2/projects/shikuang-singlewindow

最短启动口令：`启动实况 REVIEW`（分阶段人工确认），或 `启动实况 AUTO`（自动质检后连续执行）。

## 识别和处理规则
1. 读取本包所有 `rules/00_*.md`、`rules/01_*.md`、`rules/02_*.md`、`rules/03_*.md`、`rules/04_*.md`，`config/routes.json`、`config/engines.json` 与 `distribution/PUBLIC_USAGE.md`。若文件或平台能力缺失明确停止，而不是自行改写规则。
2. 两条视频：画面含清楚可读的正文者是对标，正文少或无正文的是主视频；不得凭文件名和传输顺序判断。参考也可能是图片。异常歧义须停在00。
3. 00：真实查看、提取、逐字整理对标文字、大小和布局位置，并整合用户本轮文字修改要求；锁定主/参考文件哈希，REVIEW等待批准。
4. 01：仅用本账号 ImageGen 创建与主视频同比例的真实 RGBA 透明文字 PNG；保留对标行列、字体大小比例和位置，不额外添字和装饰。尺寸、Alpha、逐字、视觉对照自检。REVIEW 图片不满意就局部返工，直到用户确认。
5. 02：不加速不减速，只从原视频连续截取默认约2.9秒，输出严格 < 3秒；文字从首帧至末帧完全静止，无滚动、光效、文字动画，保留原声（如果有）。视频引擎仅在明确批准及SHA/环境检查合格后运行。
6. 03：完整解码与关键帧视觉检查，MP4真时长、音轨、帧率、文字和原音验证后交付；失败在当前阶段停止，保留状态与已审核产物。

## 跨账号启动
- 在可联网读取 GitHub 的 ChatGPT 新窗口，把上面的公开规则入口和启动命令一起发给模型，再上传两条视频（或主视频+对标图片）。
- ChatGPT 不能通过普通网页阅读自动安装本地 Python 程序。若当前账号没有网页ZIP下载/运行能力，可先从公开 ZIP 下载并上传聊天，或使用支持文件下载/运行的 Work/电脑环境。
- 不同账号的 ImageGen、FFmpeg、读视频和原生附件权限要各自核实；联网能访问规则 ≠ 已自动获得本账号的执行权限。
- 若使用 AUTO 缺 ImageGen/真实视觉QA/批准引擎，不可绕过门禁伪称全自动完成。

## 生产门禁状态
本包是候选程序分发，包含真实CLI/测试，但内置FFmpeg引擎状态 `CANDIDATE_NOT_APPROVED`，**不等于多个账号已端到端跑通**。不包含任何个人原视频、授权凭据或密钥。使用详情阅读 `distribution/PUBLIC_USAGE.md`。