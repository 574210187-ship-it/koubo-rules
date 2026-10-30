# ClipFlow｜唯一正式线上执行线

此文件是本项目唯一可执行流程母本。WorkBuddy、普通页面自己从飞书物化、`bitable_materialize_attachment` 直接入媒体容器、临时 URL、resource link、旧 OCR-only/v0.5 包，以及任何多页并发分支，均不是当前流程。

## 唯一闭环

```text
飞书多维表
  → Work Mode 控制端锁定并下载/重建输入字节、核验 SHA-256
  → 控制端的云端浏览器把已核验 MP4 原生附入一个普通 ChatGPT 媒体页
  → 该媒体页 stat + SHA-256 + ffprobe 后，运行 ClipFlow v0.4.8
  → 该媒体页向原记录 append 2 ZIP + 1 TXT
  → Work Mode 控制端重新读取并逐件核验远端 SHA-256
```

这条线完全云端运行，**不使用 WorkBuddy**。浏览器只做原生附件交接；不处理视频、不跑 FFmpeg/ASR/OCR、不写飞书。普通媒体页才是媒体执行器；Work Mode 控制端才是选行、输入桥和独立验收者。

## 1. Work Mode 控制端：筛选与单行锁

固定表身份：

- app：`TRbibTAzmagpV4shYbcchcIVnhd`
- table：`tblgYhWtUJDDKJjJ`
- view：`剧情` / `vewG1nXQcP`
- 记录识别：`视频编号`
- 输入：`对标视频、图文`
- 输出：`处理后音、视频`

每次先从剧情视图读取，并在实际记录内确认字段存在。只领取：

```text
输出字段为空
AND 输入字段恰有一个 MP4
AND (
  zed备注 含“拆分”
  OR (zed备注 为空 AND 二次分类型 = “剧情”)
)
```

字段未返回、字段名不符、附件不唯一或输出已有内容，均为 `BINDING_HOLD`；不得猜字段、补条件、覆盖历史附件。按稳定顺序一次只锁一行；只有上一行的最终远端读回通过，才可继续下一行。

## 2. 已验证输入桥

1. 控制端读取锁定 record_id、视频编号、唯一 file_token、文件名、大小与源端 SHA-256。
2. 控制端用 `bitable_read_attachment_chunk` 顺序取得真实字节，逐块核验块 SHA，重建一个临时 MP4，并核验完整本地 SHA-256 与 `ffprobe`。
3. 控制端在云端浏览器中新开/复用**一个**普通 ChatGPT 媒体页，通过页面原生附件 UI 上传这一个已核验 MP4。
4. 媒体页必须独立再次给出其容器内绝对路径、stat 字节数、SHA-256 和 ffprobe；任一不一致即 `INPUT_BRIDGE_HOLD`，不开始媒体处理、不写飞书。

`chatgpt_widget_transfer_ready` 不是这条桥的成功信号，也不能替代第 2–4 步。此前成功的桥正是“控制端字节核验后原生上传”，不是“普通页面直接从飞书得到文件”。

## 3. 媒体页处理

媒体页只处理锁定的一个 record。它必须使用当前 GitHub 的 ClipFlow v0.4.8 正式代码，并先证明程序包身份；没有可验证的 v0.4.8 程序包则 `PROGRAM_GATE_HOLD`。

处理和交付合同：

- 每段实际编码时长严格 `>3.000 && <=8.000`；
- 只在可信完整句尾切；镜头变化仅作优先候选；无可行解输出 `cut_conflict.json` 并 `CUT_CONTRACT_HOLD`；
- 每段截图只从开头前10帧选中文 OCR 文字最少者，选完后才加 C 方案同号水印；
- 成功的正式本地文件**仅**是：
  1. `videos_and_screenshot.zip`：编号 MP4 + 同号 JPG；
  2. `supporting_materials.zip`：其余支持材料；
  3. `文案.txt`：ZIP 外、UTF-8 无 BOM、逐行纯台词。
- 媒体页先在本地验证三件的 ZIP 成员/CRC、时长、映射、TXT，再用 `bitable_upload_file_append` append 到同一条记录的 `处理后音、视频`。不修改 `执行记录` 或任何其他业务字段。

## 4. 控制端最终验收

控制端重新精确读取同一 record：

- 输出字段恰有本轮三件，没有重复或额外模拟成品；
- 名称、大小、完整远端 SHA-256 与媒体页本地文件一致；
- 输入字段、`执行记录` 和其他行没有变化。

所有条件成立才为 `DELIVERY_VERIFIED`。失败为 `OUTPUT_HOLD`，保留页面和状态以便精确恢复；不删除聊天、关闭浏览器或删除飞书附件，除非用户单独授权。

唯一启动提示词在 `PROMPT_FOR_CHATGPT.md`。其它说明文件只能引用本文件，不能再定义第二条执行线。