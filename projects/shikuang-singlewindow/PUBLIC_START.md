# 实况视频单窗口｜跨 ChatGPT 账号启动（v1.2.0）

请加载 **v1.2.0-1080p-mp4zip-candidate**，入口：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.2.0/projects/shikuang-singlewindow/START_HERE.md

直接下载固定ZIP：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.2.0/projects/shikuang-singlewindow/releases/shikuang-singlewindow-v1.2.0-1080p-mp4zip-candidate.zip

核对 SHA-256：fb87c590d94dce409072fb9ac7919d4287714446b412745facc4acf0799802ec。若无法直接下载，我会以附件发送同版ZIP；不得使用旧版v1.0.2冒充。

以 REVIEW 模式从00开始；每步真实执行与QA，00/01/03等待我的确认。支持直接修改当前阶段后局部返工并继续，不需要重启。

输入为主视频＋带文字的对标视频/图片；对标视频画面有明显正文，主视频基本无正文，按画面自动识别角色，不根据文件名判定。收到本轮附加改字要求，先写入00。01只能用ImageGen生成RGBA透明文字PNG，尽量保持对标的逐字、大小、比例、位置、布局；禁止Python/JSON绘字。02将透明文字静止覆盖主视频全时长，不加速减速，不滚动不做文字动画，保留主视频原声（如有）。03交付1080P MP4以及包含同一MP4的ZIP，逐项解码/时长/帧率/音轨/字位校验；不合格停当前阶段。

AUTO模式仅替换 REVIEW 为 AUTO；真实ImageGen、自动视觉QA、FFmpeg和正式批准引擎都存在时才能连续执行。当前引擎为CANDIDATE_NOT_APPROVED，须保留阻断，不得伪称已生产完成。
