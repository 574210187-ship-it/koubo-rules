# Reference ClipFlow｜飞书多维表工作流（v0.4.8）

本文件定义 v0.4.8 的线上回填合同；实际 Work Mode 调度见 [ONLINE_WORK_MODE.md](ONLINE_WORK_MODE.md)。

## 固定绑定

- app：`TRbibTAzmagpV4shYbcchcIVnhd`
- table：`tblgYhWtUJDDKJjJ`
- view：`剧情`（`vewG1nXQcP`）
- 输入附件：`对标视频、图文`
- 成品附件：`处理后音、视频`
- 行识别：`视频编号`

连接器必须先报告 `bitable_connection_status.connected=true`。有连接不等于允许读取、下载、上传或原生物化媒体；每项需在目标表上实际验证。

## 筛选与串行锁定

只处理以下谓词为真的行：

```text
输出附件字段为空
AND 输入字段恰有一条 MP4
AND (
  ZED 包含“拆分”
  OR (ZED 为空 AND 二次分类 = “剧情”)
)
```

每次重新从剧情视图读取并以记录字段复核，按稳定顺序串行锁定一行。输入、输出或字段名有歧义时 HOLD；不跨视图猜测，不因凑数量放宽条件。

## 输入不得伪造

下载/物化要证明四件事：目标运行时实际文件路径、`stat` 字节数、本地 SHA-256、`ffprobe` 可解码。源端文件 token、服务端 SHA、resource link 和 `chatgpt_widget_transfer_ready` 均不足。缺任一项为 `INPUT_BRIDGE_HOLD`，不运行 ClipFlow、不上传文件、不修改任何记录。

## 回填的唯一清单

成功一行只允许追加下列三件到该行 `处理后音、视频`：

| 文件 | 内容 |
|---|---|
| `videos_and_screenshot.zip` | 所有编号 MP4 与同编号 JPG，且不含 TXT/支持文档 |
| `supporting_materials.zip` | SRT、MD、manifest、CSV、样式与样张等全部非媒体支持材料 |
| `文案.txt` | 独立、UTF-8 无 BOM、逐行纯原始台词文字 |

上传使用 append-only 和 `record_id + v0.4.8 + SHA-256` 幂等键。上传后重新读取同一记录，逐件核验名称、大小和完整 SHA-256；未读回则是 `UPLOAD_READBACK_HOLD`，不得报成功。不得上传旧版 `ClipFlow_完整交付.zip`、`segments_transcript.txt` 或任何中间文件作为替代。

不覆盖、不删除旧附件，不写 `执行记录`，不写其他行或状态字段。