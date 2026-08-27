#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_yotta_logs.py — 元史（yotta-logs）测试。

覆盖：JSONL 解析容错 / 会话发现 / sessions.json 索引 / 角色与文本提取 /
默认脱敏 / scan / search（关键词·正则·日期·会话·角色·截断）/ session 提取 /
stats（角色·成本·token·每日汇总）/ tools 排行 / CLI 退出码 / JSON 输出 /
GBK 控制台 / 只读保证。纯标准库，无 pytest 依赖。

运行：python scripts/test_yotta_logs.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import yotta_logs as YL  # noqa: E402

PASS = 0
FAIL = 0
FAILED = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILED.append(name)
        print("  FAIL: %s %s" % (name, detail))


def wjsonl(p, rows):
    lines = []
    for r in rows:
        if isinstance(r, str):
            lines.append(r)
        else:
            lines.append(json.dumps(r, ensure_ascii=False))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_fixture(base):
    """构造一个真实形态的会话日志目录，返回目录 Path。"""
    d = base / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    a1 = [
        {"type": "session", "timestamp": "2026-08-26T03:00:00+08:00",
         "session_id": "a1", "title": "部署讨论"},
        {"type": "message", "timestamp": "2026-08-26T03:00:01+08:00",
         "message": {"role": "user", "content": [
             {"type": "text", "text": "你好，部署方案定了吗？"}]}},
        {"type": "message", "timestamp": "2026-08-26T03:00:05+08:00",
         "message": {"role": "assistant", "content": [
             {"type": "text",
              "text": "定了，按灰度发布执行。密钥 sk-abcdef1234567890 已就位。"}],
             "usage": {"cost": {"total": 0.01}, "input_tokens": 100,
                       "output_tokens": 50}}},
        {"type": "message", "timestamp": "2026-08-26T03:01:00+08:00",
         "message": {"role": "assistant", "content": [
             {"type": "toolCall", "name": "read_file"},
             {"type": "text", "text": "我读一下配置。"}]}},
        {"type": "message", "timestamp": "2026-08-26T03:02:00+08:00",
         "message": {"role": "toolResult", "content": [
             {"type": "toolResult", "name": "read_file",
              "content": "{\"ok\": true}"}]}},
        "this line is not valid json",
    ]
    b2 = [
        {"type": "message", "timestamp": "2026-08-27T10:00:00+08:00",
         "message": {"role": "user", "content": [
             {"type": "text", "text": "CI 又失败了，看下日志。"}]}},
        {"type": "message", "timestamp": "2026-08-27T10:01:00+08:00",
         "message": {"role": "assistant", "content": [
             {"type": "text",
              "text": "好的，我去查。Bearer abcDEF123ghiJKL789 拿来用。"}]}},
        {"type": "message", "timestamp": "2026-08-27T10:02:00+08:00",
         "message": {"role": "assistant", "content": [
             {"type": "toolCall", "name": "run_shell"},
             {"type": "text", "text": "执行命令。"}]}},
        {"type": "message", "timestamp": "2026-08-27T10:03:00+08:00",
         "message": {"role": "user", "content": [
             {"type": "text", "text": "hello, please retry with the new endpoint"}]}},
    ]
    wjsonl(d / "a1.jsonl", a1)
    wjsonl(d / "b2.jsonl", b2)
    (d / "sessions.json").write_text(
        json.dumps({"微信-部署": "a1", "ci-排查": "b2"}, ensure_ascii=False),
        encoding="utf-8")
    (d / "notes.txt").write_text("not a session file", encoding="utf-8")
    return d


def test_parse_jsonl():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.jsonl"
        p.write_text('{"a":1}\nnot json\n[1,2,3]\n{"b":2}\n',
                     encoding="utf-8")
        records, invalid = YL.parse_jsonl(p)
        check("parse_jsonl 记录数", len(records) == 2, "got %d" % len(records))
        check("parse_jsonl 无效行计数", invalid == 2, "got %d" % invalid)


def test_list_sessions():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "a.jsonl").write_text("\n", encoding="utf-8")
        (d / "b.jsonl").write_text("\n", encoding="utf-8")
        (d / "c.txt").write_text("x", encoding="utf-8")
        (d / "sessions.json").write_text("{}", encoding="utf-8")
        sess = YL.list_sessions(d)
        check("list_sessions 只收 jsonl", len(sess) == 2, "got %s" % sess)
        check("list_sessions 会话 ID = 文件名主干",
              {s["session"] for s in sess} == {"a", "b"})


def test_load_index():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "sessions.json").write_text(
            json.dumps({"k1": "s1", "k2": "s2"}), encoding="utf-8")
        idx = YL.load_index(d)
        check("load_index dict 形态", idx == {"k1": "s1", "k2": "s2"}, str(idx))
        (d / "sessions.json").write_text(
            json.dumps([{"key": "k1", "sessionId": "s1"}]), encoding="utf-8")
        idx = YL.load_index(d)
        check("load_index list 形态", idx == {"k1": "s1"}, str(idx))
        (d / "sessions.json").write_text("not json", encoding="utf-8")
        check("load_index 坏文件容错", YL.load_index(d) == {})


def test_rec_parsing():
    rec = {"type": "message", "timestamp": "2026-08-26T03:00:00Z",
           "message": {"role": "user", "content": "直接字符串"}}
    check("_rec_ts 顶层", YL._rec_ts(rec) == "2026-08-26T03:00:00Z")
    check("_rec_role user", YL._rec_role(rec) == "user")
    check("_rec_text 字符串", YL._rec_text(rec) == "直接字符串")

    rec2 = {"type": "message", "message": {"role": "toolResult", "content": [
        {"type": "text", "text": "A"}, {"type": "thinking", "text": "隐藏"},
        {"type": "toolCall", "name": "run_shell"}]}}
    check("_rec_role toolResult 归一为 tool", YL._rec_role(rec2) == "tool",
          YL._rec_role(rec2))
    check("_rec_text 只取 text", YL._rec_text(rec2) == "A",
          repr(YL._rec_text(rec2)))
    check("_rec_tool_names", YL._rec_tool_names(rec2) == ["run_shell"])

    rec3 = {"type": "message", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "x"}]},
        "usage": {"cost": {"total": 0.5}, "input_tokens": 10,
                  "output_tokens": 20}}
    check("_rec_cost", YL._rec_cost(rec3) == 0.5)
    check("_rec_tokens", YL._rec_tokens(rec3) == (10, 20))
    check("_is_message 排除 session 元数据",
          YL._is_message({"type": "session", "role": "session"}) is False)


def test_redact():
    check("redact sk-", "sk-" not in YL.redact("密钥 sk-abcdef1234567890 已就位"))
    check("redact ghp_", "ghp_" not in YL.redact("token ghp_ABCDEFGHIJKLMNOPQRST"))
    check("redact AKIA", "AKIA" not in YL.redact("AKIA1234567890ABCDEF"))
    check("redact JWT",
          "eyJ" not in YL.redact("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"))
    check("redact Bearer",
          YL.redact("Bearer abcDEF123ghiJKL789") == "Bearer ***")
    check("redact URL 口令",
          YL.redact("https://user:pass@example.com/path")
          == "https://user:***@example.com/path")
    check("redact 赋值",
          "token=***" in YL.redact("token=sk-abcdef1234567890x"))
    check("redact 长串",
          "***" in YL.redact("abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGH"))
    check("redact URL 路径保留",
          "https://example.com/api/v1/items" in YL.redact("看 https://example.com/api/v1/items 这里"))
    check("redact 普通中文不动",
          YL.redact("你好，今天天气不错。") == "你好，今天天气不错。")
    check("redact PEM",
          "PRIVATE KEY REDACTED" in YL.redact(
              "-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----"))


def test_scan(fx):
    res = YL.scan_sessions(str(fx))
    check("scan 会话数 2", res["total_sessions"] == 2,
          str(res["rows"]))
    check("scan 消息合计 8", res["total_messages"] == 8,
          str(res["total_messages"]))
    check("scan 无效行 1", res["total_invalid"] == 1)
    by = {r["session"]: r for r in res["rows"]}
    check("scan a1 消息 4", by["a1"]["messages"] == 4)
    check("scan b2 日期", by["b2"]["date"] == "2026-08-27")
    check("scan 别名映射", by["a1"]["alias"] == "微信-部署")


def test_search(fx):
    r = YL.search_sessions(str(fx), "部署")
    check("search 关键词命中", len(r["matches"]) == 1
          and r["matches"][0]["session"] == "a1", str(r))
    r = YL.search_sessions(str(fx), "HELLO")
    check("search 不区分大小写", len(r["matches"]) == 1
          and r["matches"][0]["session"] == "b2", str(r))
    r = YL.search_sessions(str(fx), r"CI \w+", regex=True)
    check("search 正则命中", len(r["matches"]) == 1
          and r["matches"][0]["session"] == "b2", str(r))
    r = YL.search_sessions(str(fx), "看下", date="2026-08-27")
    check("search 日期过滤", len(r["matches"]) == 1
          and r["matches"][0]["session"] == "b2", str(r))
    r = YL.search_sessions(str(fx), "灰度", sessions=["微信-部署"])
    check("search 会话别名过滤", len(r["matches"]) == 1
          and r["matches"][0]["session"] == "a1", str(r))
    r = YL.search_sessions(str(fx), "灰度", sessions=["b2"])
    check("search 会话 ID 过滤无命中", r["matches"] == [], str(r))
    r = YL.search_sessions(str(fx), "了", role="assistant")
    check("search 角色过滤", r["matches"] and all(
        m["role"] == "assistant" for m in r["matches"]), str(r))
    r = YL.search_sessions(str(fx), "了", limit=1)
    check("search limit 截断", r["truncated"] is True and len(r["matches"]) == 1
          and r["sessions_hit"] == 1, str(r))
    r = YL.search_sessions(str(fx), "绝不存在的词xyz")
    check("search 无命中空列表", r["matches"] == [] and r["sessions_hit"] == 0)
    r = YL.search_sessions(str(fx), "sk-abcdef1234567890")
    check("search 命中脱敏打码", r["matches"] and
          "sk-" not in r["matches"][0]["text"] and "***" in r["matches"][0]["text"],
          str(r["matches"]))


def test_extract(fx):
    r = YL.extract_session(str(fx), "a1")
    check("extract 消息 4", len(r["messages"]) == 4, str(len(r["messages"])))
    check("extract 首条", r["messages"][0]["role"] == "user"
          and "部署方案" in r["messages"][0]["text"])
    check("extract 脱敏", "sk-" not in r["messages"][1]["text"]
          and "***" in r["messages"][1]["text"], repr(r["messages"][1]["text"]))
    r2 = YL.extract_session(str(fx), "a1", role="assistant")
    check("extract 角色过滤", len(r2["messages"]) == 2
          and all(m["role"] == "assistant" for m in r2["messages"]))
    r3 = YL.extract_session(str(fx), "ci-排查")
    check("extract 别名解析", r3["session"] == "b2", str(r3["session"]))
    r4 = YL.extract_session(str(fx), "b2", with_tools=True)
    tools = [t for m in r4["messages"] for t in m["tools"]]
    check("extract 工具标注", "run_shell" in tools, str(tools))
    try:
        YL.extract_session(str(fx), "nope")
        check("extract 未知会话抛错", False)
    except SystemExit:
        check("extract 未知会话抛错", True)


def test_stats(fx):
    r = YL.session_stats(str(fx))
    check("stats 会话 2", r["sessions"] == 2)
    check("stats 消息 8", r["messages"] == 8)
    check("stats 角色分布", r["roles"] == {"user": 3, "assistant": 4, "tool": 1},
          str(r["roles"]))
    check("stats 成本", abs(r["cost"] - 0.01) < 1e-9, str(r["cost"]))
    check("stats token", r["tokens_in"] == 100 and r["tokens_out"] == 50)
    check("stats 首末时间", r["first"].startswith("2026-08-26")
          and r["last"].startswith("2026-08-27"))
    r2 = YL.session_stats(str(fx), daily=True)
    check("stats 每日两天", set(r2["days"].keys()) == {"2026-08-26", "2026-08-27"},
          str(r2["days"].keys()))
    check("stats 每日成本", abs(r2["days"]["2026-08-26"]["cost"] - 0.01) < 1e-9)
    r3 = YL.session_stats(str(fx), session_id="微信-部署")
    check("stats 单会话", r3["sessions"] == 1 and r3["messages"] == 4,
          str((r3["sessions"], r3["messages"])))


def test_tools(fx):
    items = YL.tool_breakdown(str(fx))
    by = dict(items)
    check("tools 排行 read_file 2", by.get("read_file") == 2, str(items))
    check("tools 排行 run_shell 1", by.get("run_shell") == 1, str(items))
    items2 = YL.tool_breakdown(str(fx), session_id="a1")
    by2 = dict(items2)
    check("tools 单会话", by2.get("read_file") == 2 and "run_shell" not in by2,
          str(items2))


def _run(args, inp=None, env=None, cwd=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        [sys.executable, str(_HERE / "yotta_logs.py")] + args,
        input=inp, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=e, cwd=cwd)


def test_cli(fx):
    r = _run(["version"])
    check("CLI version", r.returncode == 0 and YL.VERSION in r.stdout,
          "rc=%d" % r.returncode)

    r = _run(["scan", "--dir", str(fx), "--json"])
    try:
        obj = json.loads(r.stdout)
        check("CLI scan --json", r.returncode == 0
              and obj["total_sessions"] == 2, r.stdout[:120])
    except Exception as e:  # noqa: BLE001
        check("CLI scan --json", False, str(e))

    r = _run(["search", "部署", "--dir", str(fx), "--json"])
    try:
        obj = json.loads(r.stdout)
        check("CLI search --json", r.returncode == 0
              and obj["total_matches"] == 1 and len(obj["matches"]) == 1,
              r.stdout[:120])
    except Exception as e:  # noqa: BLE001
        check("CLI search --json", False, str(e))

    r = _run(["search", "绝不存在的词xyz", "--dir", str(fx)])
    check("CLI search 无命中退出码 1", r.returncode == 1,
          "rc=%d" % r.returncode)

    r = _run(["session", "a1", "--dir", str(fx)])
    check("CLI session 文本输出", r.returncode == 0 and "部署方案" in r.stdout,
          "rc=%d" % r.returncode)

    r = _run(["stats", "--dir", str(fx), "--daily"])
    check("CLI stats 每日", r.returncode == 0 and "每日汇总" in r.stdout,
          "rc=%d" % r.returncode)

    r = _run(["tools", "--dir", str(fx), "--json"])
    try:
        obj = json.loads(r.stdout)
        by = {t["name"]: t["count"] for t in obj["tools"]}
        check("CLI tools --json", r.returncode == 0 and by.get("read_file") == 2,
              r.stdout[:120])
    except Exception as e:  # noqa: BLE001
        check("CLI tools --json", False, str(e))

    r = _run(["scan", "--dir", str(Path(fx).parent / "no-such-dir")])
    check("CLI 目录不存在退出码 4", r.returncode == 4, "rc=%d" % r.returncode)

    r = _run(["badcmd"])
    check("CLI 未知子命令退出码 4", r.returncode == 4, "rc=%d" % r.returncode)

    r = _run(["search", "Bearer", "--dir", str(fx), "--no-redact"])
    check("CLI --no-redact 原文保留", r.returncode == 0
          and "abcDEF123ghiJKL789" in r.stdout, repr(r.stdout[:120]))

    r = _run(["scan"], env={"YOTTA_LOGS_DIR": str(fx)})
    check("CLI YOTTA_LOGS_DIR 环境变量", r.returncode == 0
          and "会话 2 个" in r.stdout, "rc=%d" % r.returncode)


def test_gbk_console(fx):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "gbk"
    r = subprocess.run(
        [sys.executable, str(_HERE / "yotta_logs.py"),
         "search", "部署", "--dir", str(fx)],
        capture_output=True, text=True, encoding="gbk", errors="replace",
        env=env)
    check("GBK 控制台中文输出不炸", r.returncode == 0,
          "rc=%d err=%r" % (r.returncode, r.stderr[:100]))


def test_readonly(fx):
    before = sorted((p.name, p.stat().st_size) for p in fx.iterdir())
    YL.scan_sessions(str(fx))
    YL.search_sessions(str(fx), "部署")
    YL.extract_session(str(fx), "a1")
    YL.session_stats(str(fx), daily=True)
    YL.tool_breakdown(str(fx))
    after = sorted((p.name, p.stat().st_size) for p in fx.iterdir())
    check("只读保证：目录内容不变", before == after,
          "before=%s after=%s" % (before, after))


# ── v0.2.0 通用化测试 ────────────────────────────────────────────────────

def build_json_fixture(base):
    """单文件 JSON 会话：一个数组文件 + 一个 dict-of-lists 文件。"""
    d = base / "jsons"
    d.mkdir(parents=True, exist_ok=True)
    arr = [
        {"role": "user", "content": "你好，单文件 JSON 测试。", "ts": "2026-08-26T09:00:00+08:00"},
        {"role": "assistant", "content": "收到。", "ts": "2026-08-26T09:01:00+08:00"},
    ]
    (d / "convo.json").write_text(json.dumps(arr, ensure_ascii=False),
                                  encoding="utf-8")
    multi = {
        "s1": [{"role": "user", "content": "s1 的第一个问题"},
               {"role": "assistant", "content": "s1 的回复"}],
        "s2": [{"role": "user", "content": "s2 的问题"}],
    }
    (d / "multi.json").write_text(json.dumps(multi, ensure_ascii=False),
                                  encoding="utf-8")
    return d


def build_sqlite_opencode(p):
    import sqlite3 as _sq
    con = _sq.connect(str(p))
    con.execute("CREATE TABLE session (id TEXT, title TEXT, time_created INTEGER,"
                " cost REAL, tokens_input INTEGER, tokens_output INTEGER)")
    con.execute("CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, data TEXT)")
    con.execute("CREATE TABLE part (id TEXT, message_id TEXT, session_id TEXT,"
                " time_created INTEGER, data TEXT)")
    con.execute("INSERT INTO session VALUES ('ses_a','部署讨论',1785834902916,0.05,100,50)")
    con.execute("INSERT INTO session VALUES ('ses_b','CI 排查',1785835000000,0.0,0,0)")
    con.execute("INSERT INTO message VALUES ('msg_1','ses_a',1785834903000,'{\"role\":\"user\"}')")
    con.execute("INSERT INTO part VALUES ('prt_1','msg_1','ses_a',1785834903001,"
                "'{\"type\":\"text\",\"text\":\"你好，部署方案定了吗？\"}')")
    con.execute("INSERT INTO message VALUES ('msg_2','ses_a',1785834904000,'{\"role\":\"assistant\"}')")
    con.execute("INSERT INTO part VALUES ('prt_2','msg_2','ses_a',1785834904001,"
                "'{\"type\":\"text\",\"text\":\"定了，按灰度发布执行。\"}')")
    con.execute("INSERT INTO part VALUES ('prt_3','msg_2','ses_a',1785834904002,"
                "'{\"type\":\"tool\",\"tool\":\"read_file\"}')")
    con.execute("INSERT INTO part VALUES ('prt_4','msg_2','ses_a',1785834904003,"
                "'{\"type\":\"reasoning\",\"text\":\"隐藏推理不输出\"}')")
    con.execute("INSERT INTO message VALUES ('msg_3','ses_b',1785835001000,'{\"role\":\"user\"}')")
    con.execute("INSERT INTO part VALUES ('prt_5','msg_3','ses_b',1785835001001,"
                "'{\"type\":\"text\",\"text\":\"CI 又失败了，看下日志。\"}')")
    con.commit()
    con.close()


def build_sqlite_generic(p):
    import sqlite3 as _sq
    con = _sq.connect(str(p))
    con.execute("CREATE TABLE messages (id INTEGER, session_id TEXT, role TEXT,"
                " content TEXT, created_at TEXT)")
    con.execute("INSERT INTO messages VALUES (1,'g1','user','泛型表问题甲','2026-08-26T03:00:00+08:00')")
    con.execute("INSERT INTO messages VALUES (2,'g1','assistant','泛型表回复甲','2026-08-26T03:01:00+08:00')")
    con.execute("INSERT INTO messages VALUES (3,'g2','user','乙的问题','2026-08-27T10:00:00+08:00')")
    con.commit()
    con.close()


def build_md_fixture(base):
    facts = base / ".yottamemory" / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    (facts / "2026-08-25-0002.md").write_text(
        "---\ntype: FACT\nsubject: 共享记忆引擎接入指南\n"
        "statement: 本机运行 yotta-memory 记忆引擎，接入方式见正文。\n"
        "confidence: 1\ncreated: 2026-08-25\ntags: [memory, guide]\n---\n"
        "正文补充。\n", encoding="utf-8")
    notes = base / ".CodexData" / "memories"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / "note.md").write_text(
        "# 推送闸门红线\n\n规则：测试通过才能推。\n", encoding="utf-8")
    return facts, notes


def test_norm_time():
    check("毫秒转 ISO", YL._norm_time(1785834903000)
          .startswith("20") and "T" in YL._norm_time(1785834903000),
          YL._norm_time(1785834903000))
    check("秒时间戳", YL._norm_time(1785834903).startswith("20"),
          YL._norm_time(1785834903))
    check("ISO 原样", YL._norm_time("2026-08-26T03:00:00+08:00")
          == "2026-08-26T03:00:00+08:00")
    check("日期原样", YL._norm_time("2026-08-25") == "2026-08-25")
    check("Z 归一", YL._norm_time("2026-08-26T03:00:00Z")
          == "2026-08-26T03:00:00+00:00")


def test_json_reader():
    with tempfile.TemporaryDirectory() as td:
        d = build_json_fixture(Path(td))
        src = YL.sniff_source(str(d))
        check("JSON 目录嗅探", src["format"] == "json" and src["kind"] == "session",
              str(src))
        reader = YL.JSONReader()
        rows, tm, inv = reader.iter_sessions(src)
        check("JSON scan 3 会话", len(rows) == 3 and tm == 5, str(rows))
        r = YL.search_all([src], "单文件")
        check("JSON search 命中", len(r["matches"]) == 1
              and r["matches"][0]["session"] == "convo", str(r))
        r2 = YL.search_all([src], "s2")
        check("JSON dict 会话检索", len(r2["matches"]) == 1
              and r2["matches"][0]["session"] == "s2", str(r2))
        ex = YL.extract_all([src], "convo")
        check("JSON extract", len(ex["messages"]) == 2
              and ex["messages"][0]["role"] == "user", str(ex))
        st = YL.stats_all([src])
        check("JSON stats 消息 5", st["messages"] == 5, str(st["messages"]))
        check("JSON stats 角色", st["roles"].get("user") == 3, str(st["roles"]))


def test_sqlite_opencode_reader():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "opencode.db"
        build_sqlite_opencode(p)
        src = YL.sniff_source(str(p))
        check("SQLite 文件嗅探", src["format"] == "sqlite", str(src))
        reader = YL.SQLiteReader()
        rows, tm, inv = reader.iter_sessions(src)
        check("opencode scan 2 会话", len(rows) == 2, str(rows))
        by = {r["session"]: r for r in rows}
        check("opencode ses_a 消息 2", by["ses_a"]["messages"] == 2,
              str(by["ses_a"]))
        check("opencode 毫秒日期", by["ses_a"]["date"].startswith("20"),
              by["ses_a"]["date"])
        r = YL.search_all([src], "灰度")
        check("opencode search 命中", len(r["matches"]) == 1
              and r["matches"][0]["session"] == "ses_a", str(r))
        r2 = YL.search_all([src], "隐藏推理")
        check("opencode reasoning 不进文本", r2["matches"] == [], str(r2))
        ex = YL.extract_all([src], "ses_a")
        check("opencode extract 消息 2", len(ex["messages"]) == 2, str(ex))
        msg2 = ex["messages"][1]
        check("opencode 工具标注", msg2["tools"] == ["read_file"], str(msg2))
        check("opencode role assistant", msg2["role"] == "assistant", str(msg2))
        st = YL.stats_all([src])
        check("opencode stats 消息 3", st["messages"] == 3, str(st["messages"]))
        check("opencode stats 角色", st["roles"] == {"user": 2, "assistant": 1},
              str(st["roles"]))
        items = YL.tools_all([src])
        check("opencode tools read_file 1", dict(items).get("read_file") == 1,
              str(items))


def test_sqlite_generic_reader():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "app.db"
        build_sqlite_generic(p)
        src = YL._mk_source("generic-test", "session", "sqlite", p,
                            extra={"table": "messages"})
        reader = YL.SQLiteReader()
        rows, tm, inv = reader.iter_sessions(src)
        by = {r["session"]: r for r in rows}
        check("generic scan 2 会话", len(rows) == 2 and tm == 3, str(rows))
        check("generic g1 消息 2", by["g1"]["messages"] == 2, str(by["g1"]))
        r = YL.search_all([src], "甲")
        check("generic search 命中 2", len(r["matches"]) == 2, str(r))
        ex = YL.extract_all([src], "g1")
        check("generic extract 2 条", len(ex["messages"]) == 2, str(ex))
        st = YL.stats_all([src])
        check("generic stats 角色", st["roles"] == {"user": 2, "assistant": 1},
              str(st["roles"]))


def test_markdown_reader():
    with tempfile.TemporaryDirectory() as td:
        facts, notes = build_md_fixture(Path(td))
        fsrc = YL._mk_source("yottamemory-facts", "memory", "markdown", facts)
        nsrc = YL._mk_source("codex-notes", "note", "markdown", notes)
        fr = list(YL.MarkdownReader().iter_records(fsrc))
        check("md memory 1 条", len(fr) == 1, str(fr))
        rec = fr[0]
        check("md role FACT", rec["role"] == "FACT", str(rec["role"]))
        check("md title subject", rec["meta"].get("title") == "共享记忆引擎接入指南",
              str(rec["meta"]))
        check("md text statement", "yotta-memory" in rec["text"], rec["text"][:50])
        check("md created 时间", rec["time"] == "2026-08-25", rec["time"])
        nr = list(YL.MarkdownReader().iter_records(nsrc))
        check("md note 1 条", len(nr) == 1 and nr[0]["kind"] == "note", str(nr))
        check("md note 标题", nr[0]["meta"].get("title") == "推送闸门红线",
              str(nr[0]["meta"]))
        check("md note 正文", "测试通过" in nr[0]["text"], nr[0]["text"][:40])
        rows, tm, inv = YL.MarkdownReader().iter_sessions(fsrc)
        check("md memory scan", len(rows) == 1 and tm == 1, str(rows))
        # 结构化 md 文件单独 --dir → kind memory
        fp = facts / "2026-08-25-0002.md"
        s = YL.sniff_source(str(fp))
        check("md 文件嗅探 memory", s["format"] == "markdown" and s["kind"] == "memory",
              str(s))
        np = notes / "note.md"
        s2 = YL.sniff_source(str(np))
        check("md 文件嗅探 note", s2["kind"] == "note", str(s2))


def test_binary_reader():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "conv.pbtxt"
        p.write_bytes(b"\x00\x01Conversation WindSurf Title\x00\x02more")
        src = YL._mk_source("windsurf-conv", "log", "binary", p, default_on=False)
        recs = list(YL.BinaryReader().iter_records(src))
        check("binary 1 条且不崩", len(recs) == 1, str(recs))
        check("binary title 提取", "WindSurf" in recs[0]["text"], recs[0]["text"])
        check("binary kind log", recs[0]["kind"] == "log", str(recs[0]["kind"]))
        rows, tm, inv = YL.BinaryReader().iter_sessions(src)
        check("binary scan", len(rows) == 1 and tm == 1, str(rows))


def test_sniff_and_discover():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        # discover：JSONL + SQLite(opencode) + 记忆 md + 自由笔记
        jd = base / ".codex" / "sessions"
        jd.mkdir(parents=True, exist_ok=True)
        (jd / "a.jsonl").write_text('{"type":"message","message":{"role":"user","content":"hi"}}\n',
                                    encoding="utf-8")
        db = base / ".local" / "share" / "opencode" / "opencode.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        build_sqlite_opencode(db)
        facts, notes = build_md_fixture(base)
        jsrcs = YL.JSONLReader.discover(base)
        check("discover JSONL 命中 codex", any(s["name"] == "codex-sessions"
              for s in jsrcs), str(jsrcs))
        ssrcs = YL.SQLiteReader.discover(base)
        check("discover SQLite 命中 opencode", any(s["name"] == "opencode-db"
              for s in ssrcs), str(ssrcs))
        msrcs = YL.MarkdownReader.discover(base)
        names = {s["name"] for s in msrcs}
        check("discover md 命中 yottamemory-facts", "yottamemory-facts" in names,
              str(msrcs))
        check("discover md 命中 codex-notes", "codex-notes" in names, str(msrcs))
        for s in msrcs:
            if s["name"] == "codex-notes":
                check("自由笔记默认关", s["default_on"] is False, str(s))
            if s["name"] == "yottamemory-facts":
                check("结构化记忆默认开", s["default_on"] is True, str(s))
        # 配置兜底
        cfg = {"sources": [{"name": "myapp", "path": str(base / "app.db"),
                            "format": "sqlite", "kind": "session",
                            "table": "messages", "col_text": "content"}]}
        srcs = YL.discover_sources(cfg)
        check("配置源登记", any(s["name"] == "myapp" for s in srcs), str(srcs))


def test_filters_and_scope():
    srcs = [
        YL._mk_source("sess", "session", "jsonl", "/x", True),
        YL._mk_source("mem", "memory", "markdown", "/y", True),
        YL._mk_source("note", "note", "markdown", "/z", False),
    ]

    class A:
        source = None
        kind = None
        format = None

    a = A()
    out = YL.filter_sources(srcs, a)
    check("默认范围排除 note", [s["name"] for s in out] == ["sess", "mem"],
          str(out))
    a.kind = "note"
    out = YL.filter_sources(srcs, a)
    check("--kind note 显式开", [s["name"] for s in out] == ["note"], str(out))
    a.kind = None
    a.format = "markdown"
    out = YL.filter_sources(srcs, a)
    check("--format markdown 显式含 note", {s["name"] for s in out} == {"mem", "note"},
          str(out))
    a.format = None
    a.source = ["sess"]
    out = YL.filter_sources(srcs, a)
    check("--source 过滤", [s["name"] for s in out] == ["sess"], str(out))


def test_cross_source_scope():
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        # 用自己的 fixture：jsonl 会话 + 记忆 md + 自由笔记 都含关键词
        jd = base / "sessions"
        jd.mkdir(parents=True, exist_ok=True)
        (jd / "s1.jsonl").write_text(
            '{"type":"message","timestamp":"2026-08-26T03:00:00+08:00","message":{"role":"user","content":"部署方案定了吗"}}\n',
            encoding="utf-8")
        facts, notes = build_md_fixture(base)
        (facts / "m1.md").write_text(
            "---\ntype: FACT\nsubject: 部署\nstatement: 部署方案已拍板。\ncreated: 2026-08-25\n---\n",
            encoding="utf-8")
        (notes / "n1.md").write_text("# 部署笔记\n\n部署草稿。\n", encoding="utf-8")
        jsrc = YL.sniff_source(str(jd))
        fsrc = YL._mk_source("facts", "memory", "markdown", facts)
        nsrc = YL._mk_source("notes", "note", "markdown", notes, default_on=False)
        srcs = [jsrc, fsrc, nsrc]
        # 默认：会话 + 记忆，排除自由笔记
        default = YL.filter_sources(srcs, type("A", (), {"source": None,
                                                         "kind": None,
                                                         "format": None})())
        res = YL.search_all(default, "部署")
        names = {(m["source"], m["session"]) for m in res["matches"]}
        check("默认范围不含自由笔记", ("notes", "n1") not in names, str(names))
        check("默认范围含会话与记忆",
              ("sessions", "s1") in names and ("facts", "m1") in names, str(names))
        # 显式开 note
        res2 = YL.search_all([nsrc], "部署")
        check("显式开 note 可检索", ("notes", "n1") in
              {(m["source"], m["session"]) for m in res2["matches"]}, str(res2))


def test_cli_v020(fx):
    # --kind / --format / --source 参数存在且 --dir 行为不变
    r = _run(["search", "部署", "--dir", str(fx), "--format", "jsonl"])
    check("CLI --format jsonl", r.returncode == 0 and "部署方案" in r.stdout,
          "rc=%d" % r.returncode)
    r = _run(["search", "部署", "--dir", str(fx), "--kind", "session"])
    check("CLI --kind session", r.returncode == 0, "rc=%d" % r.returncode)
    r = _run(["scan", "--dir", str(fx), "--source", "nope"])
    check("CLI --source 无命中退出码 1", r.returncode == 1,
          "rc=%d" % r.returncode)
    # locate --json 结构
    r = _run(["locate", "--json"])
    try:
        obj = json.loads(r.stdout)
        check("CLI locate --json", r.returncode == 0
              and "sources" in obj and "default_scope" in obj, r.stdout[:120])
    except Exception as e:  # noqa: BLE001
        check("CLI locate --json", False, str(e))
    # 单文件 md --dir（自由笔记显式可查）
    with tempfile.TemporaryDirectory() as td:
        np = Path(td) / "note.md"
        np.write_text("# 标题甲\n\n正文含关键词乙。\n", encoding="utf-8")
        r = _run(["search", "关键词乙", "--dir", str(np)])
        check("CLI 单 md 文件检索", r.returncode == 0 and "关键词乙" in r.stdout,
              "rc=%d out=%s" % (r.returncode, r.stdout[:80]))
        r = _run(["scan", "--dir", str(np), "--json"])
        try:
            obj = json.loads(r.stdout)
            check("CLI 单 md scan", r.returncode == 0
                  and obj["total_sessions"] == 1, r.stdout[:120])
        except Exception as e:  # noqa: BLE001
            check("CLI 单 md scan", False, str(e))



def main():
    print("元史（yotta-logs）测试开始…")
    with tempfile.TemporaryDirectory() as td:
        fx = build_fixture(Path(td))
        test_parse_jsonl()
        test_list_sessions()
        test_load_index()
        test_rec_parsing()
        test_redact()
        test_scan(fx)
        test_search(fx)
        test_extract(fx)
        test_stats(fx)
        test_tools(fx)
        test_cli(fx)
        test_gbk_console(fx)
        test_readonly(fx)
        test_norm_time()
        test_json_reader()
        test_sqlite_opencode_reader()
        test_sqlite_generic_reader()
        test_markdown_reader()
        test_binary_reader()
        test_sniff_and_discover()
        test_filters_and_scope()
        test_cross_source_scope()
        test_cli_v020(fx)
    print("")
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    if FAILED:
        print("失败清单：")
        for name in FAILED:
            print("  - " + name)
    sys.exit(1 if FAIL else 0)



if __name__ == "__main__":
    main()
