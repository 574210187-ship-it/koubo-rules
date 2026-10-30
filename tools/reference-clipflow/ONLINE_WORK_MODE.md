# ClipFlow v0.4.8｜纯线上 Work Mode 流程

## 范围

此流程只给**同一账号的 Work Mode 窗口**使用。该窗口本身读取飞书、处理媒体、上传和读回；不打开普通 ChatGPT 子页面、不使用 WorkBuddy、不使用浏览器自动化，也不使用本机 Worker。

绑定目标：

| 项 | 固定值 |
|---|---|
| app_token | `TRbibTAzmagpV4shYbcchcIVnhd` |
| table_id | `tblgYhWtUJDDKJjJ` |
| 工作视图 | `剧情` / `vewG1nXQcP` |
| 输入附件字段 | `对标视频、图文` |
| 输出附件字段 | `处理后音、视频` |
| 识别字段 | `视频编号` |
| 筛选字段 | `ZED`、`二次分类型` |

## 领取条件

只在剧情视图中处理同时满足以下条件的记录：

- `处理后音、视频` 为空；
- 输入字段恰有一个可解码 MP4；
- `ZED` 包含“拆分”，**或** `ZED` 为空且 `二次分类型` 为“剧情”。

先获取本视图的当前记录再以字段值复核；不能仅相信视图名称。当前 MCP 实读字段名为`二次分类型`；若`ZED`、输入附件或输出附件字段在本次读取中不可见，先报`BINDING_HOLD`，不得猜字段。按稳定记录顺序**串行**处理所有符合项。每行是一个独立事务：上一行读回通过才开始下一行；任何一行 HOLD 不得改写该行、不得改写别行，也不得猜测其为已完成。

## 严格输入桥门禁

1. 调用 `bitable_connection_status`，再读取视图/记录，确认上述绑定和唯一 MP4。
2. 读取源附件大小和 SHA-256；调用附件原生物化能力。
3. 只有 Work Mode 的**媒体运行时**出现真实可读文件，且可取得绝对路径、`stat` 字节数、同源 SHA-256 和 `ffprobe` 解码信息，才是 `INPUT_BRIDGE_PASS`。
4. `chatgpt_widget_transfer_ready`、资源链接、临时下载 URL、仅服务端 SHA，均不是文件。它们只能得到 `INPUT_BRIDGE_HOLD`；禁止改用截图、假文件、浏览器绕行、手工补传或上传模拟成品。

当前连接器必须把附件物化到**当前 Work Mode 运行时**才可真正全自动。若这一能力尚未实际返回本地文件，此流程的正确运行结果是 HOLD，而不是“已处理”。

## 单行执行与验收

输入桥通过后：

1. 在当前 Work Mode 运行时运行 v0.4.8 `clipflow reference`。
2. 先通过三约束：实际每段 `>3s && <=8s`、完整句尾、镜头优先；无解写 `cut_conflict.json` 并 HOLD。
3. 验证前 10 帧 OCR 选图与 C 同号水印。
4. 只生成并验收 `videos_and_screenshot.zip`、`supporting_materials.zip` 与 ZIP 外 `文案.txt`。第一 ZIP 仅 MP4/JPG；第二 ZIP 仅支持材料；TXT 必须 UTF-8 无 BOM、逐行纯文字且不在 ZIP 内。
5. 对三件计算本地 SHA-256；以 `record_id + 文件 SHA-256 + v0.4.8` 形成稳定幂等键，使用 `bitable_upload_file_append` 仅追加到同一记录的 `处理后音、视频` 字段。
6. 重新读取该记录，并对三件执行完整远端 SHA-256 读回。只有文件名、大小、完整 SHA 都与本地一致时才标记 `UPLOADED_READBACK_PASS`。

不覆盖、不删除附件；不改 `执行记录` 或其他状态字段。历史存在旧附件时，记录不是可领取项，因为输出字段不为空。

## 状态词

- `NO_ELIGIBLE_ROWS`：没有满足条件的行。
- `INPUT_BRIDGE_HOLD`：飞书附件未成为当前 Work Mode 可读媒体文件。
- `CUT_CONTRACT_HOLD`：没有可同时满足 3–8 秒、完整句尾和镜头优先的切分。
- `DELIVERY_HOLD`：三件本地成品或 ZIP/TXT 验收失败。
- `UPLOAD_READBACK_HOLD`：上传结果无法逐件远端读回。
- `UPLOADED_READBACK_PASS`：一行的三件文件全部读回匹配，可继续下一行。

固定启动提示词见 `PROMPT_FOR_CHATGPT.md`。