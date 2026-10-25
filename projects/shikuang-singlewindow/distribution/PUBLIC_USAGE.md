# 跨账号公开使用｜v1.0.2-public-candidate

**入口（无需原账号 OAuth）**：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.0.2/projects/shikuang-singlewindow/START_HERE.md
**ZIP 原始链接**：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.0.2/projects/shikuang-singlewindow/releases/shikuang-singlewindow-v1.0.2-public-candidate.zip
**GitHub 目录**：https://github.com/574210187-ship-it/koubo-rules/tree/shikuang-public-v1.0.2/projects/shikuang-singlewindow
**版本校验**：获取同目录 `SHA256SUMS.txt`，对 ZIP 文件运行 `sha256sum` 或 `shasum -a 256`，再执行 `python release_verify.py <zip路径>`。

## 给另一个 ChatGPT 账号的一句话

> 请阅读公开 GitHub 规则 https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.0.2/projects/shikuang-singlewindow/START_HERE.md ，按“实况视频单窗口”v1.0.2-public-candidate 加载完整00~04规则和当前程序，模式REVIEW。优先下载并检查同目录 ZIP 及 SHA256；本轮附件是一条主视频和一条有正文的对标视频（或者主视频+对标图片），00自动识别角色并检查全文和排版；01只用ImageGen产生透明文字PNG；用户确认后原速截取约2.9秒，静态叠加文字，成品严格小于3秒并保留主视频原声，完整验收。若当前工具无法下载 ZIP、执行 FFmpeg 或进行ImageGen/视觉QA，明确报告缺少的能力并停止，不声称自动安装/已完成。

## 运行环境
Python 3.10+，ffmpeg和ffprobe、Pillow，支持 ImageGen 的 ChatGPT/Work 模式或等效已授权图片生成工具。ChatGPT 文字模式中的一句口令仅能指引加载文件；工具下载和视频生成是否可用由当前账号真实工具决定。

## REVIEW/AUTO 差别
REVIEW：00、01、最终验收各人工确认，局部返工后恢复同一任务。AUTO：各阶段都要执行真实QA且经批准的视频引擎可用时才连续运行；遇到语义模糊、错字、布局超差、无法读字或执行环境缺失直接停下。

## 通用限制
- 禁止把一个账号的 OAuth、账号相关 secrets、私人聊天媒体、空间路径直接继承给另一个账号。
- 公共发布的是程序/规则/候选执行ZIP，不包含用户本轮的主视频及输出产物。
- 当前公开发布位于既有公开仓库单独分支，原仓库主分支不改变；后续若新建专用公开仓库可通过新版本登记迁移。
- COS 专用表情PNG/GIF MCP 不能写本项目 ZIP，未发布时如实报告，不假装多端同步完成。