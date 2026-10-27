# AI 窗口项目汇报协议

这是一套给 ChatGPT、Codex、WorkBuddy 及其他 AI 执行窗口使用的飞书多维表汇报规范。

核心原则只有一句：**一个窗口的一次执行或一次问题，只新增一行。**

## 一键启动

把下面整段发给需要汇报的 AI 窗口，并替换尖括号中的目标信息：

```text
请立即读取并严格执行 https://raw.githubusercontent.com/574210187-ship-it/koubo-rules/main/ai-window-reporting-protocol/START.md 。目标飞书多维表：<飞书多维表链接>；目标子表：汇报项目；table_id：<汇报项目table_id>。本轮结束、达到汇报点、发生问题、问题恢复或需要更正时，必须按规范新增一行，写后回读并返回record_id；不得覆盖旧行，不得把多次汇报塞进同一个执行记录单元格。若无法读取规范或无法写表，不得声称成功，必须返回具体错误和完整待代写字段。
```

目标飞书链接和 `table_id` 不写进这个公开仓库，由发起人在每次启动指令中单独传入，避免把内部表地址永久公开。

## 仓库内容

- [`START.md`](START.md)：AI 必须执行的完整规范。
- [`ONE_CLICK_PROMPT.txt`](ONE_CLICK_PROMPT.txt)：可复制的一键启动提示词。
- [`templates/result-report.md`](templates/result-report.md)：结果汇报模板。
- [`templates/problem-report.md`](templates/problem-report.md)：问题故障模板。
- [`reporting-spec.json`](reporting-spec.json)：机器可读规则。
- [`AGENTS.md`](AGENTS.md)：Codex、WorkBuddy 等代理工具的入口说明。

## 数据安全

- 不要把飞书 OAuth token、Webhook key、Cookie 或其他密钥提交到本仓库。
- 公开规范只描述格式；实际目标表和权限由启动指令或执行环境提供。
- 写表成功必须以飞书回读和 `record_id` 为准。

## 版本

当前协议版本：`1.0.0`
