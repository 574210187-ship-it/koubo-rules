# 实况视频单窗口 · v1.3.2 候选

这是一套可执行但非自带AI视觉推理的三阶段工具：00 ChatGPT视觉分析并给用户确认，01 ChatGPT真实ImageGen生成3至4张RGBA文字层供选择，02 FFmpeg把所选图原位静态覆盖到主视频并交付1080P MP4与单MP4的ZIP。

## 对话入口
- 本账号：阅读 `LOCAL_START.md` 直接复制；资料库 `/实况/单窗口/`。
- 其他账号：阅读 `EXTERNAL_START.md` 直接复制；使用公开GitHub固定ZIP，若不能读取网络资源则用户上传此ZIP附件。

## CLI（自动管理状态与文件，不自行绘图）
```
python src/shikuang.py init --run-dir runs/001 --main <主视频> --reference <对标视频或图片>
python src/shikuang.py analyze --run-dir runs/001 --analysis 00.json
python src/shikuang.py approve-00 --run-dir runs/001
python src/shikuang.py options --run-dir runs/001 --png A.png --imagegen-id imagegen:<真实ID_A> --png B.png --imagegen-id imagegen:<真实ID_B> --png C.png --imagegen-id imagegen:<真实ID_C>
python src/shikuang.py select --run-dir runs/001 --index 2
python src/shikuang.py render --run-dir runs/001
```
- 用户选中图已在当前执行环境可访问时，`--index` 直接复用已确认候选，不重复上传。
- 用户确实重新上传修改图时，可以 `select --png <确实存在的新文件>`。
- 错误保持当前阶段，不能标记成功；新版本输出不覆盖上一版本。

## 验证与限制
`python -m unittest discover -s tests -v`；`python verify.py <本ZIP路径>`。
技术测试包含使用FFmpeg真实编码和完全解码的测试素材，但其他账号访问ImageGen/源视频/FFmpeg仍依赖其权限与环境；复制指令不能授权工具。
当前版本默认保持**源视频全长、原速、原声**，由用户明确提出更短时长时才按需求变更（使用独立明确批准的执行规则）。