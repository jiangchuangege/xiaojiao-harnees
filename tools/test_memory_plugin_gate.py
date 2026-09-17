# -*- coding: utf-8 -*-
"""`plugins/memory.py` 写闸自测（**离线、不调模型**，可进 CI）

【这个测试钉的是什么】
2026-09-17 用户看见的那张卡片里是模型退化乱码（`亻命鸵次次次亻扑…`），它来自早期那份
遗留存盘 —— 而那个文件的写入侧当年是**裸的**（`save_memory` 拿到什么写什么）。
存量已经搬进隔离区，这个测试钉的是**源头**：以后不该进的东西进不去。

判据本身在 `core/mem_filter.py`（和"对话记忆"那条链**同一条**，不另造一套），
这个测试只验"这条工具路径真的接上了它"。

运行：python tools/test_memory_plugin_gate.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:150]) if info else ""))


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "memplug", os.path.join(_ROOT, "plugins", "memory.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    tmp = tempfile.mkdtemp(prefix="_memgate_")
    old_cwd = os.getcwd()
    memo = os.path.join(tmp, "xiaojiao_memory.txt")
    try:
        os.chdir(tmp)                       # ⚠️ 插件用的是**相对路径** —— 换目录跑，不碰真文件
        mem = _load_plugin()
        p = mem.MemoryPlugin()

        print("一、正常内容：能写进去（不许把功能弄没）")
        r1 = p.execute("save_memory", {"content": "用户喜欢喝黑咖啡"})
        ck("正常内容 → 已记住", r1.startswith("已记住"), r1)
        ck("文件里真的有一行", os.path.exists(memo)
           and "用户喜欢喝黑咖啡" in open(memo, encoding="utf-8").read(), memo)

        print("\n二、工具原始返回：**一个字都不许进**")
        p.execute("save_memory", {"content":
                                  "🌐 **https://example.com** · HTTP 200 <html><body>原始正文在这里"
                                  "</body></html>"})
        body = open(memo, encoding="utf-8").read()
        ck("文件里没有 `HTTP 200`（工具原文没进）", "HTTP 200" not in body, body[:120])
        ck("文件里没有 `<html>`", "<html>" not in body, body[:120])

        print("\n三、坏回复 / 占位符：不许进")
        r3 = p.execute("save_memory", {"content": "⏳ 正在调用工具：net_ip"})
        ck("占位符 → 明确回「没有记」并给原因", r3.startswith("这条**没有记**"), r3)
        ck("占位符没进文件", "正在调用工具" not in open(memo, encoding="utf-8").read())

        print("\n四、复读与不成话：不许进")
        r4 = p.execute("save_memory", {"content": "次次次次次次"})
        ck("同一字符连 5 次以上 → 判复读、不写", r4.startswith("这条**没有记**"), r4)
        r5 = p.execute("save_memory", {"content": "！！！？？？……"})
        ck("整条没有中文/字母数字 → 不写", r5.startswith("这条**没有记**"), r5)

        print("\n五、完全重复：不重复追加")
        n_before = len(open(memo, encoding="utf-8").read().splitlines())
        r6 = p.execute("save_memory", {"content": "用户喜欢喝黑咖啡"})   # 和第一条一模一样
        n_after = len(open(memo, encoding="utf-8").read().splitlines())
        ck("同一条再存 → 回「已经记过了」", "已经记过" in r6, r6)
        ck("文件行数没变", n_before == n_after, (n_before, n_after))

        print("\n六、空内容")
        r7 = p.execute("save_memory", {"content": ""})
        ck("空内容 → 不写并说明", r7.startswith("这条**没有记**"), r7)

        print("\n七、读回来：文件里只有该有的东西")
        out = p.execute("read_memory", {})
        ck("read_memory 能读（非空）", bool(out.strip()), out[:80])
        ck("读回来的内容里没有乱码/原始返回", ("亻" not in out) and ("HTTP 200" not in out), out[:120])

        print("\n八、文件不存在时（隔离之后就是这个状态）")
        os.remove(memo)
        ck("没有文件 → 「还没有任何记忆」", p.execute("read_memory", {}) == "还没有任何记忆")
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    print("记忆插件写闸自测：通过 %d / 共 %d" % (len(PASS), len(PASS) + len(FAIL)))
    if FAIL:
        print("❌ 失败：%s" % FAIL)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
