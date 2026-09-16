# -*- coding: utf-8 -*-
"""修五 自测：时间性问题走**时间线检索**（不走语义检索）。

为什么要有这条路：用户问「你还记得上一次吗」时，语义检索是按"像不像"找的，
而"上一次"这句话本身跟任何一段历史都不像 —— 它捞回来的是一堆**别的**记忆，
再被贴上"你提到过"，就答出了"哔哩哔哩"那种驴唇不对马嘴的东西。
时间性问题要的是**时间顺序**：按 ts 排、取最近几轮就对了。

本自测最后一组【E】**故意断言那个已知的误触发**（「前面提到的函数」会被判成时间问题）——
不粉饰：判据里「前面」这个词天生有歧义，这一条如实留着，写进文档。
"""
import io
import os
import sys
import tempfile
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import xiaojiao_app as app               # noqa: E402
from core import memory_vec              # noqa: E402

_C = {"pass": 0, "total": 0, "failed": []}


def ck(name, cond, got=""):
    _C["total"] += 1
    if cond:
        _C["pass"] += 1
        print("  ✅ %s" % name)
    else:
        _C["failed"].append(name)
        print("  ❌ %s   ← %s" % (name, got))


print("=" * 78)
print("【A】规格点名的 8 个触发词，逐个都要命中")
WORDS = ["上一次", "上次", "刚才", "刚刚", "之前", "昨天", "接着上次", "前面"]
for w in WORDS:
    ck("「%s」判为时间性问题" % w, app._is_time_question("你还记得%s吗" % w) is True, "")

print("\n【B】非时间性问题**不许**被当成时间问题（照旧走语义检索）")
NORMAL = ["我的名字是什么", "帮我写个函数", "北京天气怎么样", "介绍一下 Python 的装饰器",
          "347 乘 892 等于多少", "你好", "总结一下这篇文档"]
for q in NORMAL:
    ck("「%s」判为普通问题" % q, app._is_time_question(q) is False, "")

print("\n【C】接线：真造几轮对话，走真实 `_timeline_memory()`")
tmp = os.path.join(tempfile.gettempdir(), "xiaojiao_tl_test.jsonl")
if os.path.exists(tmp):
    os.remove(tmp)
memory_vec._VS_PATH = tmp
memory_vec._INDEX.update({"loaded": True, "count": 0, "rows": [], "meta": [], "mat": None})
try:
    now = time.time()
    memory_vec.add_memory("用户：第一轮我说我喜欢猫\n小焦：记住了，你喜欢猫。",
                          kind="dialogue", ts=now - 300, key_text="我喜欢猫")
    memory_vec.add_memory("用户：第二轮我说我住在济南\n小焦：好，济南。",
                          kind="dialogue", ts=now - 200, key_text="我住在济南")
    memory_vec.add_memory("用户：第三轮我说我在写代码\n小焦：在写什么？",
                          kind="dialogue", ts=now - 100, key_text="我在写代码")
    memory_vec.add_memory("【知识】泉城是济南别称。", kind="fact", ts=now - 50,
                          key_text="济南别称")
    tl = app._timeline_memory("你还记得上一次吗", n=3)
    print("    时间线输出：")
    for ln in tl.split("\n"):
        print("      " + ln[:100])
    ck("时间线有输出", bool(tl.strip()), tl[:60])
    ck("标明了自己走的是**时间线**（不是相似度检索）", "时间线" in tl, tl[:80])
    ck("**按时间正序**：第一轮在最前、第三轮在最后",
       tl.find("我喜欢猫") < tl.find("我住在济南") < tl.find("我在写代码"),
       "顺序 idx：猫=%d 济南=%d 代码=%d" % (tl.find("我喜欢猫"), tl.find("我住在济南"),
                                            tl.find("我在写代码")))
    ck("只取对话类，**不含** fact 知识条目", "泉城" not in tl, tl[-80:])
    ck("每条都带来源标记（与修三一致）",
       tl.count("【你说过的】") == 3, "命中 %d 次" % tl.count("【你说过的】"))
    ck("N 起作用：n=2 只给两轮", app._timeline_memory("上次", n=2).count("【你说过的】") == 2,
       app._timeline_memory("上次", n=2))

    print("\n【D】走真实入口 `_retrieve_memory()`：时间性问题 → 时间线；普通问题 → 语义")
    got = app._retrieve_memory("你还记得上一次吗")
    ck("「你还记得上一次吗」走的是时间线", "时间线" in got, got[:80])
    got2 = app._retrieve_memory("我住在济南吗")
    ck("普通问题**没有**被塞时间线头（照旧语义检索）", "时间线" not in got2, got2[:80])
finally:
    if os.path.exists(tmp):
        os.remove(tmp)

print("\n【E】如实记：已知的误触发（**不粉饰**）")
ck("「前面提到的函数」会被判成时间问题 —— 这是判据里「前面」天生的歧义，如实留着",
   app._is_time_question("前面提到的那个函数怎么改") is True, "")
print("     ↑ 这条不是「通过」，是**把已知缺陷钉在自测里**，免得以后没人数它。")

print("\n" + "=" * 78)
print("  通过 %d / 共 %d" % (_C["pass"], _C["total"]))
if _C["failed"]:
    print("  ❌ 未通过：%s" % "、".join(_C["failed"]))
print("=" * 78)
sys.exit(0 if not _C["failed"] else 1)
