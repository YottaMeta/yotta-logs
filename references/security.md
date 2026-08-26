# 安全边界（security）

## 只读保证

- 引擎只调用读取类操作（`open(path, "r")`），对会话目录不做任何写入 / 修改 / 删除；
- 检索、提取、统计全程无网络请求；不把日志内容上传到任何服务；
- 测试含只读回归：跑完 scan / search / session / stats / tools 后目录文件清单与大小不变。

## 默认脱敏

输出（search 命中片段、session 原文）默认把疑似密钥 / token / 口令打码，`--no-redact` 关闭。覆盖：

| 形态 | 示例 |
|---|---|
| API key 前缀 | sk-xxx / rk-xxx / pk-xxx |
| GitHub / Slack token | ghp_xxx / xoxb-xxx |
| AWS access key | AKIAxxx / ASIAxxx |
| JWT | eyJ...\\.eyJ...\\.eyJ... |
| Bearer token | Bearer xxx |
| URL 口令 | https://user:pass@host → https://user:***@host |
| 赋值式密钥 | token=xxx / password=xxx / secret=xxx / api_key=xxx |
| 超长 token | 40+ 位字母数字串 |
| PEM 私钥 | -----BEGIN ... PRIVATE KEY----- |

URL 路径（非凭据）原文保留，方便回溯链接。

## 边界

- 只检索 `*.jsonl` 会话文件与 `sessions.json` 索引；不读取、不分析其它文件；
- 检索范围限定用户显式传入的 `--dir`（或环境变量 / 自动定位结果），不主动扫描磁盘；
- 输出可能包含会话原文中的隐私，默认脱敏且仅用于本机回溯，请勿外传。

## 与元忆（yotta-memory）的分工

| 维度 | yotta-logs（元史） | yotta-memory（元忆） |
|---|---|---|
| 定位 | 原始会话日志（JSONL 事实） | 语义记忆（结构化条目） |
| 输出 | 原文片段 + 行号 + 时间戳 | 记忆条目 + 权限边界 + 画像 |
| 写操作 | 无（只读） | 支持（remember / forget / archive） |
| 权限 | 目录级只读 | 类型 / 属主级权限边界 |

回溯「原文」用元史；沉淀「长期知识 / 偏好 / 承诺」用元忆，二者互补。
