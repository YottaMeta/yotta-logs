# 更新日志

## v0.2.1 (2026-08-27)

文档中英双版（老张拍板「英文门面 + 中文全档」）：

- **README.md 改为英文**：作为 GitHub / npm / ClawHub 首页的英文门面（翻译 + 精简，覆盖定位 / 核心价值 / 命令 / 快速使用 / 安装 / 使用示例 / 开发校验全流程）。
- **新增 README.zh-CN.md**：原中文完整主文档整体平移，继续服务中文用户，顶部加语言切换链接。
- **package.json**：description 改英文；files 加 README.zh-CN.md；版本 0.2.0 → 0.2.1。
- 版本四处对齐：package.json / SKILL frontmatter / 引擎 VERSION / 文档。
- 边界（B 方案）：references / CHANGELOG / 测试注释不翻译；SKILL 触发描述保持中文。

## v0.2.0 (2026-08-27)

多格式通用化：不再只认 JSONL，按「格式族 × 字段别名归一 + 配置兜底」适配一切格式（老张拍板三点：方向认可 / 版本 v0.2.0 / 默认检索范围动作工时定）：

- **五大格式族 reader**：JSONL（支持嵌套子目录与 Codex rollout payload 形态）/ 单文件 JSON（数组、dict-of-lists）/ SQLite（opencode schema 实测 + 通用列映射兜底，只读 mode=ro）/ Markdown（YAML frontmatter 结构化记忆 + 自由笔记）/ 二进制（只降级读标题不崩）。
- **统一 Record 模型**：{source, format, kind, session, time, role, text, path, meta}；字段别名归一（time / role / text / session / title），秒 / 毫秒自动推断，JSON 字符串解包。
- **discover 全源登记**：locate 遍历所有 reader 的 discover()，登记 Codex / Claude Code / Clawdbot / opencode（XDG_DATA_HOME / OPENCODE_DATA / 默认路径）/ VS Code·Cursor state.vscdb / Continue / yotta-memory（memory_home 配置）/ Codex 笔记 / Aider / Windsurf 等已知根。
- **配置兜底**：~/.config/yotta-logs/config.json（$YOTTA_LOGS_CONFIG 覆盖），sources[] 自定义源（table / col_time / col_role / col_text / col_session / col_title），引擎零改动接入怪格式。
- **过滤与默认范围**：新增 --source / --kind / --format；默认检索范围 = 会话源 + 结构化记忆源开，自由笔记 / 二进制日志关（可显式开）。
- 测试：139 项全绿（75 项 v0.1.0 回归 + 64 项 v0.2.0 通用化用例）；py_compile / validate-skill / 元安 / 元审全过。
- 文档：新增 references/agent-formats.md 普查登记表；format.md / cli.md / security.md / SKILL.md / README.md 同步；版本 0.1.0→0.2.0 四件对齐（package.json / SKILL frontmatter / 引擎 VERSION / 文档）。

## v0.1.0 (2026-08-27)

YottaMeta 自有实现首版（历史会话日志检索方向参考开源社区 session-logs 类技能思路，已完全重写，无上游代码）：

- 元史（yotta-logs）—— 零依赖跨智能体会话日志检索引擎（Python 3.8+ 标准库）。
- 能力：locate / scan / search / session / stats / tools / version；关键词 / 正则 / 日期 / 会话 ID / 别名 / 角色过滤；默认脱敏（--no-redact 关闭）；--json 结构化输出；只读安全；容错 JSONL 解析（含 sessions.json 索引别名）。
- 测试：scripts/test_yotta_logs.py 75 项全绿。
- 版权：YottaMeta 纯自有 MIT + NOTICE 品牌声明；README 一行上游致谢。
