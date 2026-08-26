# 会话日志格式（format）

元史按「目录 = 会话集」工作：一个目录下有若干 `*.jsonl` 会话文件，可选一个 `sessions.json` 索引。目录由 `--dir` 指定（缺省读环境变量 `YOTTA_LOGS_DIR`，再自动定位首个已知目录）。

## 会话文件（*.jsonl）

每行一个 JSON 对象，追加写入。常见字段：

| 字段 | 说明 |
|---|---|
| type | `session`（会话元数据）或 `message`（消息） |
| timestamp | ISO 时间戳（如 `2026-08-26T03:00:01+08:00`） |
| message.role | `user` / `assistant` / `toolResult`（归一为 `tool`） |
| message.content | 文本或列表；列表项 `type=text` 取文本，`type=toolCall` / `toolResult` 取工具名 |
| message.usage.cost.total | 单条成本 |
| message.usage.input_tokens / output_tokens | token 数 |

会话 ID = 文件名主干（去掉 `.jsonl`）。文件只被读取，绝不写入 / 修改 / 删除。

## 索引文件（sessions.json）

可选，把别名映射到会话 ID。两种形态均可：

```json
{ "微信-部署": "a1", "ci-排查": "b2" }
```

```json
[ { "key": "微信-部署", "sessionId": "a1" } ]
```

search / session / stats / tools 的 `--session` / `-s` 参数同时接受会话 ID 与别名。

## 容错规则

- content 为字符串时直接作为文本；为列表时只取 `type=text` 项；
- role 可在 message 内或顶层；`toolResult` / `tool_result` 统一归一为 `tool`；
- usage 可在 message 内或顶层；
- 坏行（非法 JSON / 非对象）跳过并计入 `invalid`，不中断检索；
- 非 `.jsonl` 文件（如 `sessions.json`、`notes.txt`）不会被当作会话。
