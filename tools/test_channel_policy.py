# -*- coding: utf-8 -*-
"""渠道隔离自测：外部通道下**只能聊天，不能执行任何工具**。

【为什么这份自测重要】这不是洁癖，是真实安全问题：
  小焦手上有 `run_command` / `read_file` / `write_file`，接到任何"别人能给它发消息"的地方
  （微信/QQ/任何 IM）就等于**把电脑钥匙递出去**。而"不能删文件"那条红线**挡不住 run_command**。

【要钉住的三件事】
  [A] 本机请求**不受影响**（不能因为加了隔离把自家的网页搞瘫）
  [B] 声明了渠道 → 默认**纯聊天**（一个工具都不给）；配置里没写策略的渠道**按最严**处理
  [C] **执行闸真的拦得住** —— 走真实的 `app.run_tool()`，不是只看策略函数
"""
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core import channel_policy as CH      # noqa: E402
import xiaojiao_app as app                 # noqa: E402

_C = {"pass": 0, "total": 0, "failed": []}


def ck(name, cond, got=""):
    _C["total"] += 1
    if cond:
        _C["pass"] += 1
        print("  ✅ %s" % name)
    else:
        _C["failed"].append(name)
        print("  ❌ %s   ← %s" % (name, got))


print("=" * 76)
print("【A】本机请求不受限（不能把自家网页搞瘫）")
CH.reset()
ck("没声明渠道 → 不受限（allowed_tools 返回 None）", CH.allowed_tools() is None, CH.allowed_tools())
ck("没声明渠道 → 任何工具都放行", CH.is_allowed("run_command") is True, "")
ck("没声明渠道 → enabled() 为 False", CH.enabled() is False, CH.enabled())

print("\n【B】声明了渠道 → 默认纯聊天")
CH.set_channel("wechat")
ck("渠道生效", CH.enabled() is True, "")
ck("默认策略 = 一个工具都不给", CH.allowed_tools() == set(), CH.allowed_tools())
ck("run_command 被拒", CH.is_allowed("run_command") is False, "")
ck("read_file 被拒", CH.is_allowed("read_file") is False, "")
ck("write_file 被拒", CH.is_allowed("write_file") is False, "")
ck("web_search 也被拒（默认纯聊天，啥都不给）", CH.is_allowed("web_search") is False, "")
ck("render() 标成 chat_only", CH.render().get("chat_only") is True, CH.render())
CH.reset()
ck("reset() 之后恢复不受限", CH.allowed_tools() is None, CH.allowed_tools())

print("\n【C】执行闸：走真实 `run_tool()`，确认真的拦得住")
CH.reset()
# 这条先证明"本机调用是通的"（否则下面拦住了也说明不了问题）
# ⚠️ 工具名要对：第一版我写了 `calc`，但直算走的是载体内部、**根本没有这个工具**，
#    于是"对照组"和"白名单能跑"两条都红 —— 是我的自测写错了，不是隔离有问题。
out_local = app.run_tool("list_files", {"path": "."})
ck("本机调用 list_files 正常（对照组）", "未知工具" not in str(out_local), str(out_local)[:70])

CH.set_channel("wechat")
out_ch = app.run_tool("list_files", {"path": "."})
ck("★ 渠道下 list_files 被拒（执行闸生效）", "只开放聊天" in str(out_ch), str(out_ch)[:90])
out_rm = app.run_tool("run_command", {"command": "echo hi"})
ck("★ 渠道下 run_command 被拒（这条最要命）", "只开放聊天" in str(out_rm), str(out_rm)[:90])
out_wf = app.run_tool("write_file", {"path": "x.txt", "content": "hi"})
ck("★ 渠道下 write_file 被拒", "只开放聊天" in str(out_wf), str(out_wf)[:90])
CH.reset()

print("\n【D】配置里写了白名单 → 只给这些")
CTRL = os.path.join(ROOT, "xiaojiao_control.json")
bak = None
try:
    if os.path.exists(CTRL):
        bak = io.open(CTRL, encoding="utf-8").read()
    cfg = json.loads(bak) if bak else {}
    cfg["channels"] = {"family": {"tools": ["list_files"]}}
    io.open(CTRL, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
    CH.reload()
    CH.set_channel("family")
    ck("白名单内 list_files 放行", CH.is_allowed("list_files") is True, "")
    ck("白名单外 run_command 仍被拒", CH.is_allowed("run_command") is False, "")
    o = app.run_tool("list_files", {"path": "."})
    ck("★ 白名单内工具在渠道下真的能跑",
       "未知工具" not in str(o) and "只开放聊天" not in str(o), str(o)[:70])
    o2 = app.run_tool("run_command", {"command": "echo hi"})
    ck("★ 白名单外工具在渠道下仍被拒", "只开放聊天" in str(o2), str(o2)[:70])
finally:
    if bak is not None:
        io.open(CTRL, "w", encoding="utf-8").write(bak)
    elif os.path.exists(CTRL):
        os.remove(CTRL)
    CH.reload()
    CH.reset()

print("\n" + "=" * 76)
print("  通过 %d / 共 %d" % (_C["pass"], _C["total"]))
if _C["failed"]:
    print("  ❌ 未通过：%s" % "、".join(_C["failed"]))
print("=" * 76)
sys.exit(0 if not _C["failed"] else 1)
