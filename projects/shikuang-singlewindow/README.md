# 实况视频单窗口｜v1.0.2-public-candidate

**公开跨账号入口**：https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/shikuang-public-v1.0.2/projects/shikuang-singlewindow/START_HERE.md

完整执行合同、REVIEW/AUTO模式、阶段状态/返工程序见 `START_HERE.md`、`rules/`、`src/`、`config/`。正式启动使用公开ZIP+SHA256核验。无需原账号登录即可从公开GitHub查看和下载；实际执行视频和 ImageGen 仍需目标账号的工具与授权。

### 内容
- `src/shikuang.py`：状态机、路由、门禁、返工、恢复、哈希和引擎调用。
- `src/prepare_00.py`、`src/media_probe.py`：原素材技术分析/只读探针。
- `src/short_static_policy.py`：原速连续截取+三秒以内+静态文字硬性门禁。
- `rules/00~04`：语义/版式分析、ImageGen RGBA文字层、视频制作、验收和跨阶段复用规范。
- `config/routes.json`：两种输入自动路由；`config/engines.json`内视频ZIP仍为**候选未批准**，不得装作正式自动上线。
- `tools/sync_publish.py`：GitHub和通用COS发布脚本（需要合法目标环境凭据）；当前ChatGPT资料库通过文件工具单独同步。
- `tests/`：测试工程；不包含用户真实媒体、现场生成素材或成品。

技术验证：`python -m unittest discover -s tests -v`、`python release_verify.py <ZIP路径>`。说明详见 `distribution/PUBLIC_USAGE.md`。