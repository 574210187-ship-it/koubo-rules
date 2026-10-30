# ClipFlow｜Work Mode 固定启动提示词（v0.4.8）

把下面整段发送到**同一账号、已连接飞书 MCP 的 Work Mode 窗口**即可。它不适用于普通聊天页，不使用 WorkBuddy 或浏览器自动化。

```text
执行 ClipFlow v0.4.8 纯线上第一阶段。先读取当前仓库 tools/reference-clipflow 的 AGENTS.md、ONLINE_WORK_MODE.md 和 BITABLE_WORKFLOW.md，并严格按它们执行；不要启动第二阶段、不要打开普通 ChatGPT 子页面、不要使用 WorkBuddy、不要要求我手工上传视频。

先以实际返回字段验证绑定完整；若ZED、输入附件或输出附件字段不可见，报告 BINDING_HOLD 并停止，不得猜字段。固定绑定：app_token=TRbibTAzmagpV4shYbcchcIVnhd；table_id=tblgYhWtUJDDKJjJ；剧情 view_id=vewG1nXQcP；输入附件字段=对标视频、图文；输出附件字段=处理后音、视频；识别字段=视频编号。扫描剧情视图中输出字段为空、输入恰有一个 MP4，并且（ZED 含“拆分”或 ZED 为空且二次分类型为“剧情”）的全部记录；稳定排序后逐行串行执行。

每行先锁定 record_id 和视频编号，实际验证飞书连接、源附件、本地原生文件路径、stat字节数、SHA-256 和 ffprobe。只有源 MP4 已真实进入当前 Work Mode 媒体运行时，才运行 clipflow reference。chatgpt_widget_transfer_ready、临时下载链接、resource link 或仅服务端 SHA 一律是 INPUT_BRIDGE_HOLD：不得处理、不得上传、不得改任何字段；报告该行 HOLD 后停止本次运行。

处理时严格执行：每段实际时长 >3 秒且 <=8 秒；切点优先镜头变化但必须是完整句尾；无解输出 cut_conflict.json 并 HOLD；每段截图只从开头前10帧选文字最少的一帧，选好才加同号 C 水印。成功时只生成并验证 videos_and_screenshot.zip、supporting_materials.zip、文案.txt：第一个ZIP只放编号MP4+对应JPG，第二个ZIP放全部支持材料，文案.txt独立、UTF-8无BOM、每行纯台词且绝不进入ZIP。

将这三件以 append-only 方式上传到同一 record_id 的处理后音、视频字段；使用 record_id+v0.4.8+文件SHA-256 幂等键。然后读回同一记录并逐件以完整SHA-256核验名称、大小和内容。三件全部读回一致才报告该行完成并继续下一行。不得覆盖或删除附件，不得改执行记录或其他业务字段。没有符合条件的行报告 NO_ELIGIBLE_ROWS。
```

真正可全自动的前提是飞书连接器能把附件原生物化到**当前 Work Mode**媒体运行时。若尚不能，以上提示会在 `INPUT_BRIDGE_HOLD` 正确停止，而不会制造假的三件成品。