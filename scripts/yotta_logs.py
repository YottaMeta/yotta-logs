#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yotta_logs.py — YottaMeta 元史（yotta-logs）：跨智能体历史会话日志检索引擎。

零依赖（Python 3.8+ 标准库），只读检索 / 分析会话 JSONL 记录，为跨会话追溯
提供原始日志依据。与元忆（yotta-memory，语义记忆）互补：本技能只管原始会话
日志的定位、检索、提取与统计；不修改、不删除、不联网上传任何会话记录。

子命令：
  locate                 自动发现本机常见的会话日志目录
  scan   [--dir D]       列出目录下所有会话（ID / 日期 / 消息数 / 大小）
  search <query> [--dir D]  按关键词 / 正则跨会话检索，输出时间线命中
  session <sid> [--dir D]   提取单个会话原文（时间线 + 角色 + 文本）
  stats  [--dir D]       会话统计（消息 / token / 成本 / 每日汇总）
  tools  [--dir D]       工具调用次数排行
  version                打印版本

通用选项：
  --dir PATH      日志目录（缺省读环境变量 YOTTA_LOGS_DIR，再自动定位首个候选）
  --json          输出纯 JSON（stdout 无其它噪音）
  --no-redact     关闭默认脱敏（默认会把疑似密钥 / token / 口令打码）
  --limit N       最多返回 N 条（默认 50）

退出码（与元安 / 元审 / 元盾 / 元真家族一致）：
  0 = 成功（检索到结果 / 操作完成）
  1 = 无匹配 / 空结果集（search 未命中、scan / stats 无会话）
  4 = 用法错误 / 目录不存在 / 致命异常

用法示例：
  python3 yotta_logs.py locate
  python3 yotta_logs.py scan --dir ~/.clawdbot/agents/dashu/sessions
  python3 yotta_logs.py search "部署方案" --dir /path/to/sessions
  python3 yotta_logs.py search "CI 失败" --regex --date 2026-08-26
  python3 yotta_logs.py session abc123 --role assistant
  python3 yotta_logs.py stats --dir /path/to/sessions --daily
  python3 yotta_logs.py tools --dir /path/to/sessions
"""
import argparse
import datetime as _dt
import glob
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

VERSION = "0.1.0"
TOOL_NAME = "yotta-logs"
TOOL_CN = "元史"
DEFAULT_LIMIT = 50
DEFAULT_CONTEXT = 40  # 命中上下文半径（字符）
JSONL_SUFFIXES = (".jsonl", ".jsonlines", ".ndjson")
ROLE_TOOL = ("tool", "toolResult", "tool_result")


# ── 脱敏（默认开启）──────────────────────────────────────────────────────

_URL_RE = re.compile(r"(https?://[^\s\"'<>]+)", re.I)
_URL_USERPASS_RE = re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@", re.I)
_KNOWN_KEY_RE = re.compile(
    r"(?i)\b("
    r"sk-[a-z0-9_-]{8,}"           # OpenAI 类 API key
    r"|rk-[a-z0-9_-]{8,}"
    r"|pk-[a-z0-9_-]{8,}"
    r"|gh[pousr]_[a-z0-9]{20,}"    # GitHub token
    r"|xox[baprs]-[a-z0-9-]{10,}"  # Slack token
    r"|AKIA[0-9A-Z]{16}"           # AWS access key
    r"|ASIA[0-9A-Z]{16}"
    r")\b")
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/-]+")
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]+ PRIVATE KEY-----.*?-----END [A-Z0-9 ]+ PRIVATE KEY-----",
    re.S)
_ASSIGN_RE = re.compile(
    r"(?i)\b(token|password|passwd|secret|api[_-]?key|access[_-]?key|"
    r"client[_-]?secret)\b\s*[=:]\s*[\"']?[a-z0-9._~+/\-]{6,}")
_LONG_TOKEN_RE = re.compile(r"[a-z0-9+/_-]{40,}", re.I)


def redact(text):
    """把疑似密钥 / token / 口令打码（默认开启；--no-redact 关闭）。"""
    if not text:
        return text
    text = _PEM_RE.sub("[PRIVATE KEY REDACTED]", text)
    text = _URL_USERPASS_RE.sub(r"\1\2:***@", text)
    chunks = _URL_RE.split(text)  # 奇数下标为 URL，原文保留（路径不算密钥）
    out = []
    for i, chunk in enumerate(chunks):
        if i % 2 == 1:
            out.append(chunk)
            continue
        chunk = _KNOWN_KEY_RE.sub("***", chunk)
        chunk = _JWT_RE.sub("***", chunk)
        chunk = _BEARER_RE.sub("Bearer ***", chunk)
        chunk = _ASSIGN_RE.sub(lambda m: m.group(1) + "=***", chunk)
        chunk = _LONG_TOKEN_RE.sub("***", chunk)
        out.append(chunk)
    return "".join(out)


# ── 记录解析（容错：字段缺失不报错，坏行由 parse_jsonl 计数跳过）─────────

def _rec_ts(rec):
    ts = rec.get("timestamp")
    if not ts and isinstance(rec.get("message"), dict):
        ts = rec["message"].get("timestamp")
    return str(ts) if ts else ""


def _rec_role(rec):
    msg = rec.get("message")
    if isinstance(msg, dict) and msg.get("role"):
        role = str(msg["role"])
    else:
        role = rec.get("role")
        role = str(role) if role else ""
    if role in ROLE_TOOL:
        return "tool"
    return role


def _rec_content(rec):
    msg = rec.get("message")
    if isinstance(msg, dict):
        return msg.get("content")
    return rec.get("content")


def _rec_text(rec):
    """提取记录里的人类可读文本（content 列表只取 type=text，字符串直接取）。"""
    content = _rec_content(rec)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return ""


def _rec_tool_names(rec):
    """提取记录里的工具调用名（toolCall / toolResult）。"""
    content = _rec_content(rec)
    names = []
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") in ("tool_call", "toolCall", "toolResult"):
                nm = item.get("name") or item.get("toolName") or ""
                if nm:
                    names.append(str(nm))
    return names


def _rec_cost(rec):
    msg = rec.get("message")
    usage = None
    if isinstance(msg, dict):
        usage = msg.get("usage")
    if not isinstance(usage, dict):
        usage = rec.get("usage")
    if not isinstance(usage, dict):
        return 0.0
    cost = usage.get("cost")
    if isinstance(cost, dict):
        return float(cost.get("total") or 0)
    try:
        return float(cost or 0)
    except (TypeError, ValueError):
        return 0.0


def _rec_tokens(rec):
    msg = rec.get("message")
    usage = None
    if isinstance(msg, dict):
        usage = msg.get("usage")
    if not isinstance(usage, dict):
        usage = rec.get("usage")
    if not isinstance(usage, dict):
        return (0, 0)
    return (int(usage.get("input_tokens") or 0),
            int(usage.get("output_tokens") or 0))


def _is_message(rec):
    """是否为可计入统计的消息记录（排除 session 元数据 / 空角色）。"""
    role = _rec_role(rec)
    if role in ("", "session"):
        return False
    return True


# ── 会话日志目录 ─────────────────────────────────────────────────────────

def discover_dirs():
    """自动发现本机常见会话日志目录（只返回存在且含 *.jsonl 的目录）。"""
    home = Path.home()
    patterns = [
        home / ".clawdbot" / "agents" / "*" / "sessions",
        home / ".codex" / "sessions",
        home / ".claude" / "projects" / "*",
        home / ".config" / "opencode" / "sessions",
        home / ".gemini" / "sessions",
        home / ".agents" / "sessions",
    ]
    found = []
    for pat in patterns:
        for d in glob.glob(str(pat)):
            dp = Path(d)
            if not dp.is_dir():
                continue
            if any(p.is_file() and p.name.lower().endswith(JSONL_SUFFIXES)
                   for p in dp.iterdir()):
                found.append(str(dp))
    return sorted(set(found))


def list_sessions(dir_path):
    """返回目录下所有会话文件信息（只按文件名/大小，不解析内容）。"""
    d = Path(dir_path)
    out = []
    for p in sorted(d.iterdir()):
        if not p.is_file() or not p.name.lower().endswith(JSONL_SUFFIXES):
            continue
        st = p.stat()
        out.append({
            "session": p.stem,
            "path": str(p),
            "size": st.st_size,
            "mtime": _dt.datetime.fromtimestamp(st.st_mtime)
            .isoformat(timespec="seconds"),
        })
    return out


def parse_jsonl(path):
    """解析一个 JSONL 文件 → (records, invalid)。容错：坏行跳过并计数。"""
    records = []
    invalid = 0
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:  # noqa: BLE001
                invalid += 1
                continue
            if isinstance(obj, dict):
                records.append(obj)
            else:
                invalid += 1
    return records, invalid


def load_index(dir_path):
    """读取 sessions.json（若有）：返回 {别名: 会话ID}。"""
    idx = {}
    p = Path(dir_path) / "sessions.json"
    if not p.exists():
        return idx
    try:
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return idx
    if isinstance(data, dict):
        for k, v in data.items():
            idx[str(k)] = str(v)
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                sid = item.get("sessionId") or item.get("session_id") or item.get("id")
                key = item.get("key") or item.get("name")
                if sid and key:
                    idx[str(key)] = str(sid)
    return idx


def _resolve_session_ids(idx, key):
    """把别名 / 会话 ID 统一解析为候选会话 ID 集合。"""
    ids = {key}
    if key in idx:
        ids.add(idx[key])
    for alias, sid in idx.items():
        if sid == key:
            ids.add(alias)
            ids.add(sid)
    return ids


def _alias_for(idx, sid):
    for alias, value in idx.items():
        if value == sid:
            return alias
    return ""


def _ts_on_date(ts, date):
    if not ts:
        return False
    if len(date) == 10:
        return ts[:10] == date
    if len(date) == 7:
        return ts[:7] == date
    return date in ts


def _clock(ts):
    """从 ISO 时间戳取 HH:MM:SS 片段。"""
    if "T" in ts:
        return ts.split("T", 1)[1][:8]
    if " " in ts:
        return ts.split(" ", 1)[1][:8]
    return ts[:8]


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d B" % n if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%d B" % n


# ── 检索 / 提取 / 统计 ──────────────────────────────────────────────────

def scan_sessions(dir_path):
    idx = load_index(dir_path)
    rows = []
    total_messages = 0
    total_invalid = 0
    for info in list_sessions(dir_path):
        records, invalid = parse_jsonl(info["path"])
        total_invalid += invalid
        first_ts = ""
        messages = 0
        for rec in records:
            if not _is_message(rec):
                continue
            messages += 1
            ts = _rec_ts(rec)
            if not first_ts and ts:
                first_ts = ts
        total_messages += messages
        rows.append({
            "session": info["session"],
            "alias": _alias_for(idx, info["session"]),
            "path": info["path"],
            "size": info["size"],
            "date": first_ts[:10],
            "messages": messages,
            "invalid": invalid,
            "mtime": info["mtime"],
        })
    rows.sort(key=lambda r: (r["date"] or r["mtime"]), reverse=True)
    return {
        "dir": str(dir_path),
        "rows": rows,
        "total_sessions": len(rows),
        "total_messages": total_messages,
        "total_invalid": total_invalid,
    }


def search_sessions(dir_path, query, regex=False, date=None, sessions=None,
                    role=None, limit=DEFAULT_LIMIT, context=DEFAULT_CONTEXT,
                    no_redact=False):
    """跨会话关键词 / 正则检索，返回结构化命中列表。"""
    if regex:
        try:
            pat = re.compile(query, re.I)
        except re.error as e:
            raise SystemExit("正则无效：%s" % e)
    idx = load_index(dir_path)
    sid_filter = None
    if sessions:
        sid_filter = set()
        for g in sessions:
            sid_filter |= _resolve_session_ids(idx, g)
    matches = []
    hit_sids = set()
    truncated = False
    for info in list_sessions(dir_path):
        sid = info["session"]
        if sid_filter is not None and sid not in sid_filter:
            continue
        records, _ = parse_jsonl(info["path"])
        for lineno, rec in enumerate(records, 1):
            if not _is_message(rec):
                continue
            ts = _rec_ts(rec)
            if date and not _ts_on_date(ts, date):
                continue
            rrole = _rec_role(rec)
            if role and rrole != role:
                continue
            text = _rec_text(rec)
            if not text:
                continue
            if regex:
                m = pat.search(text)
                if not m:
                    continue
                span = m.span()
                matched = m.group(0)
            else:
                idx_f = text.lower().find(query.lower())
                if idx_f < 0:
                    continue
                span = (idx_f, idx_f + len(query))
                matched = query
            snippet = _snippet(text, span, context)
            if not no_redact:
                snippet = redact(snippet)
                matched = redact(matched)
            matches.append({
                "session": sid,
                "timestamp": ts,
                "role": rrole,
                "line": lineno,
                "match": matched,
                "text": snippet,
            })
            hit_sids.add(sid)
            if len(matches) >= limit:
                truncated = True
                return {
                    "matches": matches,
                    "sessions_hit": len(hit_sids),
                    "truncated": truncated,
                }
    return {"matches": matches, "sessions_hit": len(hit_sids),
            "truncated": truncated}


def extract_session(dir_path, session_id, role=None, with_tools=False,
                    no_redact=False):
    """提取单个会话原文（时间线 + 角色 + 文本）。"""
    idx = load_index(dir_path)
    info = None
    for sid in _resolve_session_ids(idx, session_id):
        p = Path(dir_path) / (sid + ".jsonl")
        if p.exists() and p.is_file():
            info = {"session": sid, "path": str(p)}
            break
    if info is None:
        p = Path(dir_path) / session_id
        if p.exists() and p.is_file():
            info = {"session": p.stem, "path": str(p)}
    if info is None:
        raise SystemExit("未找到会话：%s（可用 scan 列出会话 ID）" % session_id)
    records, invalid = parse_jsonl(info["path"])
    messages = []
    for lineno, rec in enumerate(records, 1):
        if not _is_message(rec):
            continue
        rrole = _rec_role(rec)
        if role and rrole != role:
            continue
        text = _rec_text(rec)
        tools = _rec_tool_names(rec)
        if not text and not tools:
            continue
        if not no_redact:
            text = redact(text)
        messages.append({
            "line": lineno,
            "timestamp": _rec_ts(rec),
            "role": rrole,
            "text": text,
            "tools": tools,
        })
    return {
        "session": info["session"],
        "dir": str(dir_path),
        "messages": messages,
        "invalid": invalid,
        "total_records": len(records),
    }


def session_stats(dir_path, session_id=None, daily=False):
    """汇总统计：消息 / 角色 / token / 成本 / 时间范围 / 每日汇总。"""
    idx = load_index(dir_path)
    sessions = list_sessions(dir_path)
    if session_id:
        ids = set()
        for g in (session_id if isinstance(session_id, (list, tuple)) else [session_id]):
            ids |= _resolve_session_ids(idx, g)
        sessions = [s for s in sessions if s["session"] in ids]
    agg = {
        "sessions": len(sessions),
        "messages": 0,
        "invalid": 0,
        "roles": {},
        "cost": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "first": "",
        "last": "",
        "days": {},
    }
    for info in sessions:
        records, invalid = parse_jsonl(info["path"])
        agg["invalid"] += invalid
        for rec in records:
            if not _is_message(rec):
                continue
            agg["messages"] += 1
            role = _rec_role(rec)
            agg["roles"][role] = agg["roles"].get(role, 0) + 1
            ts = _rec_ts(rec)
            if ts:
                day = ts[:10]
                if day:
                    d = agg["days"].setdefault(day, {"messages": 0, "cost": 0.0})
                    d["messages"] += 1
                    d["cost"] += _rec_cost(rec)
                if not agg["first"] or ts < agg["first"]:
                    agg["first"] = ts
                if not agg["last"] or ts > agg["last"]:
                    agg["last"] = ts
            agg["cost"] += _rec_cost(rec)
            ti, to = _rec_tokens(rec)
            agg["tokens_in"] += ti
            agg["tokens_out"] += to
    return agg


def tool_breakdown(dir_path, session_id=None):
    """工具调用次数排行 → [(工具名, 次数)]，按次数降序。"""
    idx = load_index(dir_path)
    sessions = list_sessions(dir_path)
    if session_id:
        ids = set()
        for g in (session_id if isinstance(session_id, (list, tuple)) else [session_id]):
            ids |= _resolve_session_ids(idx, g)
        sessions = [s for s in sessions if s["session"] in ids]
    counts = {}
    for info in sessions:
        records, _ = parse_jsonl(info["path"])
        for rec in records:
            for nm in _rec_tool_names(rec):
                counts[nm] = counts.get(nm, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _snippet(text, span, radius):
    start, end = span
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    pre = "…" if lo > 0 else ""
    post = "…" if hi < len(text) else ""
    return pre + text[lo:hi].replace("\n", " ") + post


# ── 文本格式化 ───────────────────────────────────────────────────────────

def fmt_scan(res):
    lines = []
    lines.append("会话日志目录：%s" % res["dir"])
    lines.append("会话 %d 个 ｜ 消息合计 %d ｜ 无效行 %d"
                 % (res["total_sessions"], res["total_messages"],
                    res["total_invalid"]))
    lines.append("")
    lines.append("%-24s %-12s %8s %10s  %s" % ("会话 ID", "日期", "消息", "大小", "别名"))
    for r in res["rows"]:
        lines.append("%-24s %-12s %8d %10s  %s"
                     % (r["session"][:24], r["date"] or "-",
                        r["messages"], _human_size(r["size"]), r["alias"]))
    return "\n".join(lines)


def fmt_search(res, query, dir_path, regex):
    lines = []
    if regex:
        desc = "正则：%s" % query
    else:
        desc = "检索词：%s" % query
    lines.append("匹配 %d 处 / %d 个会话（%s）"
                 % (len(res["matches"]), res["sessions_hit"], desc))
    if res["truncated"]:
        lines.append("（已达 --limit 上限，结果被截断）")
    lines.append("")
    cur = None
    for m in res["matches"]:
        if m["session"] != cur:
            cur = m["session"]
            lines.append("── 会话 %s ─────────────────────────" % cur)
        lines.append("%s [%s] %s" % (_clock(m["timestamp"]), m["role"], m["text"]))
    if not res["matches"]:
        lines.append("未命中。")
    return "\n".join(lines)


def fmt_session(res):
    lines = []
    counts = {}
    for m in res["messages"]:
        counts[m["role"]] = counts.get(m["role"], 0) + 1
    parts = " ｜ ".join("%s %d" % (k, v) for k, v in sorted(counts.items()))
    lines.append("会话：%s ｜ 消息 %d（%s）｜ 无效行 %d"
                 % (res["session"], len(res["messages"]), parts, res["invalid"]))
    lines.append("")
    for m in res["messages"]:
        lines.append("── %s ─────────────────────────" % _clock(m["timestamp"]))
        tag = "[%s]" % m["role"]
        if m["tools"]:
            tag += " 工具:%s" % ",".join(m["tools"])
        lines.append("%s %s" % (tag, m["text"]))
        lines.append("")
    return "\n".join(lines)


def fmt_stats(res, daily):
    lines = []
    lines.append("会话统计")
    lines.append("目录：%s" % res.get("dir", ""))
    roles = " ｜ ".join("%s %d" % (k, v)
                        for k, v in sorted(res["roles"].items()))
    lines.append("会话 %d ｜ 消息 %d（%s）｜ 无效行 %d"
                 % (res["sessions"], res["messages"], roles, res["invalid"]))
    if res["first"]:
        lines.append("时间范围 %s → %s" % (res["first"][:19], res["last"][:19]))
    lines.append("token 输入 %s ｜ 输出 %s ｜ 成本 $%.2f"
                 % (_fmt_int(res["tokens_in"]), _fmt_int(res["tokens_out"]),
                    res["cost"]))
    if daily and res["days"]:
        lines.append("")
        lines.append("── 每日汇总 ──")
        for day in sorted(res["days"], reverse=True):
            d = res["days"][day]
            lines.append("%s  消息 %d ｜ 成本 $%.2f" % (day, d["messages"], d["cost"]))
    return "\n".join(lines)


def _fmt_int(n):
    return format(n, ",")


def fmt_tools(items):
    lines = []
    lines.append("工具调用排行（按次数降序）")
    for name, count in items:
        lines.append("%6d  %s" % (count, name))
    if not items:
        lines.append("（无工具调用记录）")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self._print_message("%s: error: %s\n" % (self.prog, message), sys.stderr)
        raise SystemExit(4)


def _add_dir(ap):
    ap.add_argument("--dir", metavar="PATH",
                    help="会话日志目录（缺省读 YOTTA_LOGS_DIR，再自动定位）")


def resolve_dir(args):
    if getattr(args, "dir", None):
        d = Path(args.dir)
    else:
        env = os.environ.get("YOTTA_LOGS_DIR")
        if env:
            d = Path(env)
        else:
            found = discover_dirs()
            if not found:
                raise SystemExit(
                    "未找到会话日志目录：用 --dir 指定，或设 YOTTA_LOGS_DIR；"
                    "可用 locate 查看候选。")
            d = Path(found[0])
    if not d.is_dir():
        raise SystemExit("目录不存在：%s" % d)
    return d


def main(argv=None):
    ap = _Parser(
        prog=TOOL_NAME,
        description="%s（%s）：零依赖跨智能体会话日志检索引擎。" % (TOOL_CN, TOOL_NAME))
    ap.add_argument("--version", action="version",
                    version="%s %s" % (TOOL_NAME, VERSION))
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="打印版本")

    p_locate = sub.add_parser("locate", help="自动发现本机会话日志目录")
    p_locate.add_argument("--json", action="store_true", help="输出 JSON")

    p_scan = sub.add_parser("scan", help="列出目录下所有会话")
    _add_dir(p_scan)
    p_scan.add_argument("--json", action="store_true", help="输出 JSON")
    p_scan.add_argument("--limit", type=int, default=0,
                        help="最多列出 N 个会话（默认全部）")

    p_search = sub.add_parser("search", help="跨会话检索关键词 / 正则")
    p_search.add_argument("query", help="检索词（默认不区分大小写）")
    _add_dir(p_search)
    p_search.add_argument("--regex", action="store_true", help="把 query 当正则")
    p_search.add_argument("--date", metavar="YYYY-MM-DD",
                          help="只检索指定日期（或 YYYY-MM）")
    p_search.add_argument("-s", "--session", action="append", metavar="SID",
                          help="只检索指定会话 ID / 别名（可多次）")
    p_search.add_argument("--role", choices=("user", "assistant", "tool", "system"),
                          help="只检索指定角色")
    p_search.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                          help="最多返回 N 条命中（默认 %d）" % DEFAULT_LIMIT)
    p_search.add_argument("--context", type=int, default=DEFAULT_CONTEXT,
                          help="命中上下文半径字符数（默认 %d）" % DEFAULT_CONTEXT)
    p_search.add_argument("--json", action="store_true", help="输出 JSON")
    p_search.add_argument("--no-redact", action="store_true",
                          help="关闭默认脱敏")

    p_session = sub.add_parser("session", help="提取单个会话原文")
    p_session.add_argument("sid", help="会话 ID 或 sessions.json 里的别名")
    _add_dir(p_session)
    p_session.add_argument("--role", choices=("user", "assistant", "tool", "system"),
                           help="只提取指定角色")
    p_session.add_argument("--tools", action="store_true",
                           help="时间线里标注工具调用")
    p_session.add_argument("--limit", type=int, default=0,
                           help="最多提取 N 条消息（默认全部）")
    p_session.add_argument("--json", action="store_true", help="输出 JSON")
    p_session.add_argument("--no-redact", action="store_true",
                           help="关闭默认脱敏")

    p_stats = sub.add_parser("stats", help="会话统计汇总")
    _add_dir(p_stats)
    p_stats.add_argument("-s", "--session", metavar="SID",
                         help="只统计指定会话 ID / 别名")
    p_stats.add_argument("--daily", action="store_true", help="输出每日汇总")
    p_stats.add_argument("--json", action="store_true", help="输出 JSON")

    p_tools = sub.add_parser("tools", help="工具调用次数排行")
    _add_dir(p_tools)
    p_tools.add_argument("-s", "--session", metavar="SID",
                         help="只统计指定会话 ID / 别名")
    p_tools.add_argument("--json", action="store_true", help="输出 JSON")

    args = ap.parse_args(argv)
    try:
        if args.command == "version":
            print("%s %s" % (TOOL_NAME, VERSION))
            return 0

        if args.command == "locate":
            found = discover_dirs()
            if args.json:
                print(json.dumps({"dirs": found}, ensure_ascii=False, indent=2))
            elif found:
                for d in found:
                    print(d)
            else:
                print("未发现已知会话日志目录。")
                return 1
            return 0

        if args.command == "scan":
            d = resolve_dir(args)
            res = scan_sessions(d)
            if args.limit > 0:
                res["rows"] = res["rows"][:args.limit]
                res["total_sessions"] = len(res["rows"])
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(fmt_scan(res))
            return 0 if res["rows"] else 1

        if args.command == "search":
            d = resolve_dir(args)
            res = search_sessions(
                d, args.query, regex=args.regex, date=args.date,
                sessions=args.session, role=args.role, limit=args.limit,
                context=args.context, no_redact=args.no_redact)
            if args.json:
                print(json.dumps({
                    "command": "search",
                    "tool": TOOL_NAME,
                    "version": VERSION,
                    "query": args.query,
                    "regex": args.regex,
                    "dir": str(d),
                    "total_matches": len(res["matches"]),
                    "sessions_hit": res["sessions_hit"],
                    "truncated": res["truncated"],
                    "matches": res["matches"],
                }, ensure_ascii=False, indent=2))
            else:
                print(fmt_search(res, args.query, d, args.regex))
            return 0 if res["matches"] else 1

        if args.command == "session":
            d = resolve_dir(args)
            res = extract_session(d, args.sid, role=args.role,
                                  with_tools=args.tools,
                                  no_redact=args.no_redact)
            if args.limit > 0:
                res["messages"] = res["messages"][:args.limit]
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(fmt_session(res))
            return 0

        if args.command == "stats":
            d = resolve_dir(args)
            res = session_stats(d, session_id=args.session, daily=args.daily)
            res["dir"] = str(d)
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(fmt_stats(res, args.daily))
            return 0 if res["sessions"] else 1

        if args.command == "tools":
            d = resolve_dir(args)
            items = tool_breakdown(d, session_id=args.session)
            if args.json:
                print(json.dumps({
                    "command": "tools",
                    "tool": TOOL_NAME,
                    "version": VERSION,
                    "dir": str(d),
                    "tools": [{"name": n, "count": c} for n, c in items],
                }, ensure_ascii=False, indent=2))
            else:
                print(fmt_tools(items))
            return 0
    except BrokenPipeError:
        # 管道被提前关闭（如 scan | head）：静默收尾，不算错误
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 4
        msg = e.code if isinstance(e.code, str) else None
        if msg:
            print(msg, file=sys.stderr)
        return code if code in (0, 4) else 4
    except Exception as e:  # noqa: BLE001
        print("错误：%s" % e, file=sys.stderr)
        return 4
    return 4


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
