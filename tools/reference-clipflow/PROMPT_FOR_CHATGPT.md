# ClipFlow｜唯一 Work Mode 启动提示词

将下面整段发送给同账号、已连接飞书 MCP 的 **Work Mode 控制窗口**：

```text
执行 ClipFlow 唯一正式线上执行线。先完整读取当前 GitHub 仓库 574210187-ship-it/koubo-rules 的 tools/reference-clipflow/ONLINE_WORK_MODE.md；该文件是唯一流程母本，其它旧指令、旧 v0.5/OCR-only 包、直接 bitable_materialize、WorkBuddy、多页并发和普通页面自行从飞书取文件全部无效。

你是 Work Mode 控制端，不是媒体处理器：从 app_token=TRbibTAzmagpV4shYbcchcIVnhd、table_id=tblgYhWtUJDDKJjJ、剧情 view_id=vewG1nXQcP 中按唯一母本筛选并串行锁定一行；用飞书附件 chunk 真实重建并核验源 MP4；用云端浏览器原生附件 UI 把该 MP4 交给一个普通 ChatGPT 媒体页；该页独立核验文件后只按 v0.4.8 处理此行，向同一记录 append videos_and_screenshot.zip、supporting_materials.zip、文案.txt；最后由你读回三件完整 SHA-256 后才继续下一行。

绝不让普通媒体页直接调用 bitable_materialize_attachment 作为输入，绝不让 WorkBuddy/浏览器运行媒体算法，绝不写执行记录、覆盖或删除附件。任一字段、输入桥、程序包、切分合同、上传或读回门不通过时，准确 HOLD 当前行并停止；不伪造产物、不跳过、不扩批。
```

这个提示词只启动一条流程：**Work Mode 控制端 → 原生附件交接 → 一个普通媒体页 → 飞书远端读回**。