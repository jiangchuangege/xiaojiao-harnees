# -*- coding: utf-8 -*-
"""看它"逛"的内容：把 logs/world/ 下四个文件最近几条挑重点打印成人话。"""
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
W = "logs/world"


def _lines(p, n):
    if not os.path.exists(p):
        return []
    out = [l for l in io.open(p, encoding="utf-8", errors="replace").read().split("\n") if l.strip()]
    return out[-n:]


def _ts(x):
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(float(x)))
    except Exception:      # noqa: silent-ok
        return "?"


print("=" * 78)
print("  它今天逛了什么（logs/world/）")
print("=" * 78)

print("\n【1】吸收入库的内容 —— absorption.jsonl（逛到并留下的）")
for raw in _lines(os.path.join(W, "absorption.jsonl"), 5):
    try:
        d = json.loads(raw)
    except Exception:      # noqa: silent-ok
        continue
    t = str(d.get("text") or d.get("title") or "")[:90].replace("\n", " ")
    print("  %s  判定=%-10s 来源=%s" % (_ts(d.get("ts")), str(d.get("decision") or d.get("passed"))[:10],
                                        str(d.get("domain") or d.get("url") or "")[:34]))
    print("      %s" % t)

print("\n【2】它看到过什么 —— snapshots.jsonl（每次出门的快照）")
for raw in _lines(os.path.join(W, "snapshots.jsonl"), 4):
    try:
        d = json.loads(raw)
    except Exception:      # noqa: silent-ok
        continue
    print("  %s  %s ｜ 话题=%s" % (_ts(d.get("ts")), str(d.get("url") or "")[:52],
                                  str(d.get("topic") or "")[:20]))

print("\n【3】世界变了什么 —— changes.jsonl（新增/改动/消失）")
for raw in _lines(os.path.join(W, "changes.jsonl"), 5):
    try:
        d = json.loads(raw)
    except Exception:      # noqa: silent-ok
        continue
    print("  %s  %-10s %s ｜ %s" % (_ts(d.get("ts")), str(d.get("kind") or "")[:10],
                                   str(d.get("url") or "")[:44],
                                   str(d.get("detail") or "")[:40].replace("\n", " ")))

print("\n【4】它心里的世界地图 —— model.json（记住了哪些站/话题）")
p = os.path.join(W, "model.json")
if os.path.exists(p):
    try:
        m = json.load(io.open(p, encoding="utf-8", errors="replace"))
        print("  顶层字段：%s" % list(m.keys())[:8])
        for k, v in list(m.items())[:6]:
            if isinstance(v, dict):
                print("   %-14s %d 项 ｜ 例：%s" % (k, len(v), list(v.keys())[:3]))
            elif isinstance(v, list):
                print("   %-14s %d 项 ｜ 例：%s" % (k, len(v), str(v[:2])[:60]))
            else:
                print("   %-14s %s" % (k, str(v)[:50]))
    except Exception as e:
        print("  读不动：%r" % e)
