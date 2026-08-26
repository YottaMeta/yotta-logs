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
    print("")
    print("通过 %d 项，失败 %d 项" % (PASS, FAIL))
    if FAILED:
        print("失败清单：")
        for name in FAILED:
            print("  - " + name)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
