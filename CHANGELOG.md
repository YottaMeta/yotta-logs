# 更新日志

## v0.1.0 (2026-08-27)

YottaMeta 自有实现首版（历史会话日志检索方向参考开源社区 session-logs 类技能思路，已完全重写，无上游代码）：

- 元史（yotta-logs）—— 零依赖跨智能体会话日志检索引擎（Python 3.8+ 标准库）。
- 能力：locate / scan / search / session / stats / tools / version；关键词 / 正则 / 日期 / 会话 ID / 别名 / 角色过滤；默认脱敏（--no-redact 关闭）；--json 结构化输出；只读安全；容错 JSONL 解析（含 sessions.json 索引别名）。
- 测试：scripts/test_yotta_logs.py 75 项全绿。
- 版权：YottaMeta 纯自有 MIT + NOTICE 品牌声明；README 一行上游致谢。
