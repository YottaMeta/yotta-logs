# CLI 协议（cli）

入口：`scripts/yotta_logs.py`（Python 3.8+ 标准库，零依赖）。

## 通用选项

| 选项 | 说明 |
|---|---|
| --dir PATH | 会话日志目录；缺省读环境变量 YOTTA_LOGS_DIR，再自动定位首个已知目录 |
| --json | 输出纯净 JSON（stdout 无其它噪音） |
| --no-redact | 关闭默认脱敏 |
| --limit N | 最多返回 N 条（默认 50） |
| --version | 打印版本 |

## 子命令

### locate
自动发现本机常见会话日志目录（`~/.clawdbot/agents/*/sessions`、`~/.codex/sessions`、`~/.claude/projects/*`、`~/.config/opencode/sessions`、`~/.gemini/sessions`、`~/.agents/sessions`），只返回存在且含 `*.jsonl` 的目录。

### scan
列出目录下所有会话：ID / 日期（首条消息）/ 消息数 / 大小 / sessions.json 别名。支持 `--limit`、`--json`。空目录退出码 1。

### search <query>
跨会话检索，输出时间线命中（会话 / 时间 / 角色 / 原文片段）。

| 选项 | 说明 |
|---|---|
| --regex | 把 query 当正则（默认不区分大小写） |
| --date YYYY-MM-DD | 只检索指定日期（也支持 YYYY-MM） |
| -s / --session SID | 只检索指定会话 ID / 别名（可多次） |
| --role ROLE | user / assistant / tool / system |
| --context N | 命中上下文半径字符数（默认 40） |
| --limit N | 最多返回 N 条（默认 50） |

--json 输出：`{command, tool, version, query, regex, dir, total_matches, sessions_hit, truncated, matches[]}`，每条命中含 `session / timestamp / role / line / match / text`。

### session <sid>
提取单个会话原文（时间线 + 角色 + 文本）。`--role` 过滤、`--tools` 标注工具调用、`--limit`、`--json`。未知会话退出码 4。

### stats
会话统计：消息 / 角色分布 / token / 成本 / 时间范围；`--daily` 输出每日汇总；`-s/--session` 限定单会话。空目录退出码 1。

### tools
工具调用次数排行（`toolCall` / `toolResult` 的工具名计数），`-s/--session` 限定单会话。

### version
打印 `yotta-logs 0.1.0`。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功（检索到结果 / 操作完成） |
| 1 | 无匹配 / 空结果集 |
| 4 | 用法错误 / 目录不存在 / 未知会话 / 致命异常 |

## JSON 输出约定

- stdout 只输出 JSON，进度 / 提示走 stderr；
- `ensure_ascii=False`，中文原样输出；stdout 已重配 UTF-8（GBK 控制台不炸）。
