# -*- coding: utf-8 -*-
"""修四 自测：修饰词不许当检索词。

【实测症状】模型会把「动态」「永久」这类**修饰词**当成检索词丢给 web_search，
搜回来一堆跟用户想问的毫无关系的东西 —— 跟当初拿「用」「索」去搜是同一个病。

【判据】提取出来的关键词**只剩一个修饰词** → 不搜，反问用户要搜什么。

【⚠️ 这个自测最要紧的一条是"别误伤"】
修饰词在很多真请求里就是**内容本身**：
「汇总今天的科技动态」的检索词是「今日科技动态」—— 把「动态」当噪声删掉就错了。
所以本文件里"不该拦"的用例比"该拦"的用例更重要。
"""
import io
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import xiaojiao_app as app      # noqa: E402

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
print("【A】规格点名的那 10 个修饰词：单独出现一律不搜")
FORBIDDEN = ["动态", "静态", "永久", "临时", "长期", "短期",
             "可以", "能不能", "是否", "关于"]
for w in FORBIDDEN:
    q, hint = app.resolve_search_query(w)
    ck("「%s」不许拿去搜" % w, q == "" and hint != "", "q=%r hint=%r" % (q, hint))
ck("拒绝时的提示语点明了是「修饰词」（不是笼统说关键词无效）",
   "修饰词" in app.resolve_search_query("动态")[1], app.resolve_search_query("动态")[1])

q2, h2 = app.resolve_search_query("动态 永久")
ck("两个修饰词叠在一起也不搜", q2 == "" and h2 != "", "q=%r" % q2)

print("\n【B】★ 别误伤：修饰词**在真有内容时**必须照常搜")
KEEP = [
    ("汇总今天的科技动态", "今日科技动态"),
    ("今日科技动态", "今日科技动态"),
    ("永久 存储方案", "永久 存储方案"),
    ("长期 记忆 方案", "长期 记忆 方案"),
    ("2026 年 AI 新闻", "2026 年 AI 新闻"),
    ("济南天气", "济南天气"),
]
for raw, expect in KEEP:
    q, hint = app.resolve_search_query(raw)
    ck("「%s」照常搜（不许误伤）" % raw, q != "" and hint == "", "q=%r hint=%r" % (q, hint))
    ck("「%s」关键词没被啃掉内容" % raw, expect in q, "得到 %r" % q)

print("\n【C】判据本身（`_is_only_modifier`）")
ck("只有修饰词 → True", app._is_only_modifier("动态") is True, "")
ck("修饰词 + 实义词 → False", app._is_only_modifier("科技动态") is False, "")
ck("不含修饰词 → False", app._is_only_modifier("济南天气") is False, "")
ck("空串 → False（空是另一条判据管的）", app._is_only_modifier("") is False, "")
ck("只有标点/空格 → False", app._is_only_modifier("  ") is False, "")
ck("「能不能」这种 3 字修饰词也算修饰词", app._is_only_modifier("能不能") is True, "")

print("\n【D】验收用例：『记忆机制改成动态能永久吗』——绝不拿「动态」去搜")
raw = "记忆机制改成动态能永久吗"
candidates = [raw, app.extract_search_keywords(raw)]
for c in candidates:
    q, hint = app.resolve_search_query(c)
    ck("候选 %r 的检索词**不是**光秃秃的「动态」" % c[:14], q.strip() != "动态",
       "q=%r" % q)
    if q:
        ck("  → 若真的搜，带上了实义内容（不是纯修饰词）",
           not app._is_only_modifier(q), "q=%r" % q)

print("\n" + "=" * 78)
print("  通过 %d / 共 %d" % (_C["pass"], _C["total"]))
if _C["failed"]:
    print("  ❌ 未通过：%s" % "、".join(_C["failed"]))
print("=" * 78)
sys.exit(0 if not _C["failed"] else 1)
