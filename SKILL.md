---
name: yotta-logs
version: 0.1.0
description: 元史 —— 跨智能体的历史会话日志检索技能：零依赖检索 / 分析会话 JSONL 记录，回溯旧对话与父会话上下文，为跨会话追溯提供原始日志依据。触发：用户问起先前聊过的内容 / 父会话 / 历史上下文、要查以前说过的结论、跨会话回溯某次讨论、需要从会话日志定位某段决策时。边界：仅读取本机自己的会话日志文件；不修改、不删除会话记录；只查本地日志不联网上传；与元忆（语义记忆）互补，本技能只做原始日志检索。
license: MIT
---

# 元史（yotta-logs）

跨智能体的历史会话日志检索技能：**零依赖检索 / 分析会话 JSONL 记录**，回溯旧对话与父会话上下文，为跨会话追溯提供原始日志依据。

零依赖（Python 3.8+ 标准库），Windows + Linux + macOS 通用；Claude Code / Cursor / Codex / 通用 Agent 均可调用。

## 何时使用

- 用户引用先前聊过的内容 / 父会话 / 历史上下文；
- 要查以前说过的结论、决策、命令或结果；
- 需要从会话日志定位某段讨论发生在哪个会话、什么时间、谁说的。

**Do NOT trigger**：

- 只读：不修改、不删除任何会话记录；
- 只查本地日志，不联网上传；
- 语义记忆 / 长期知识请用元忆（yotta-memory）；本技能只管原始会话日志检索，二者互补。

## 快速使用

Windows 用 python，Linux/macOS 用 python3。

```bash
# 自动发现本机常见会话日志目录
python3 scripts/yotta_logs.py locate

# 列出目录下所有会话（ID / 日期 / 消息数 / 大小）
python3 scripts/yotta_logs.py scan --dir ~/.clawdbot/agents/<agentId>/sessions

# 跨会话检索关键词（时间线命中，默认脱敏）
python3 scripts/yotta_logs.py search "部署方案" --dir /path/to/sessions

# 正则 + 日期 + 会话过滤
python3 scripts/yotta_logs.py search "CI 失败" --regex --date 2026-08-26 --dir /path/to/sessions

# 提取单个会话原文
python3 scripts/yotta_logs.py session abc123 --dir /path/to/sessions

# 统计（消息 / token / 成本 / 每日汇总）
python3 scripts/yotta_logs.py stats --dir /path/to/sessions --daily

# 工具调用排行
python3 scripts/yotta_logs.py tools --dir /path/to/sessions
```

退出码（与元安 / 元审 / 元盾 / 元真家族一致）：0 = 成功；1 = 无匹配 / 空结果集；4 = 用法错误 / 致命异常。

## 工作流程（AI 智能体回溯历史时）

1. **定位**：locate 或 scan 找到会话日志目录与会话 ID；
2. **检索**：search 按关键词 / 正则跨会话命中，先看时间线片段；
3. **提取**：命中后 session <sid> 提取该会话原文；
4. **核对**：需要精确出处时用 --json 拿结构化结果（会话 ID / 行号 / 时间戳 / 角色）；
5. **统计**：需要成本 / token / 工具使用回顾时用 stats / tools。

## 能力

- **零依赖检索**：Python 3.8+ 标准库，不依赖 jq / rg 等外部工具；
- **容错解析**：字段缺失 / 坏行自动跳过并计数，可容忍不同智能体的 JSONL 形态差异；
- **默认脱敏**：输出自动打码疑似密钥 / token / 口令（--no-redact 关闭）；
- **多维度过滤**：关键词 / 正则 / 日期 / 会话 ID / 别名 / 角色；
- **结构化输出**：--json 输出纯净 JSON（含行号 / 时间戳 / 角色）；
- **只读安全**：只读本地日志，不修改、不删除、不联网。

## 参考文档

- references/format.md — 会话日志 JSONL 格式与 sessions.json 索引说明
- references/cli.md — CLI 子命令 / 参数 / 退出码 / JSON schema 详解
- references/security.md — 安全边界 / 脱敏规则 / 与元忆的差异化

## 责任声明

本技能只做本地会话日志的只读检索；输出原文片段可能包含隐私，默认脱敏且仅用于本机回溯，请勿将检索结果外传。
