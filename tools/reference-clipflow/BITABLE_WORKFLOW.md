# ClipFlow｜飞书绑定与交付合同

完整执行顺序只见 [ONLINE_WORK_MODE.md](ONLINE_WORK_MODE.md)。本文件只固定飞书输入/输出边界，不另建流程。

## 绑定

| 项 | 值 |
|---|---|
| app_token | `TRbibTAzmagpV4shYbcchcIVnhd` |
| table_id | `tblgYhWtUJDDKJjJ` |
| view | `剧情` / `vewG1nXQcP` |
| 行识别 | `视频编号` |
| 输入附件 | `对标视频、图文` |
| 输出附件 | `处理后音、视频` |
| 分类字段 | `二次分类型` |
| 备注字段 | `zed备注` |

实际读回必须确认这些字段名及类型；任一不可见/不同即 `BINDING_HOLD`，不按历史或口语字段名猜测。

## 领取条件

```text
处理后音、视频为空
AND 对标视频、图文恰有一个 MP4
AND (
  zed备注 含“拆分”
  OR (zed备注 为空 AND 二次分类型 = “剧情”)
)
```

每次只锁一行。已有任意输出附件的记录不是新任务，不覆盖或补写。

## 交付

同一锁定 record 的 `处理后音、视频` 只 append：

1. `videos_and_screenshot.zip`
2. `supporting_materials.zip`
3. `文案.txt`

每件使用 `record_id + v0.4.8 + SHA-256` 的稳定幂等标识。写后必须重新读取同一 record，并对三件完整下载/远端 SHA-256 核验；名字、大小、SHA 都相同才通过。禁止改 `执行记录`、其他字段、其他行；禁止覆盖或删除附件。