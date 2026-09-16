# -*- coding: utf-8 -*-
"""修三 自测：记忆注入**必须标明来源**（谁说的）。

为什么这条单独测：实测症状是它答
「我确实记得一些**你曾经提到过的内容**：…哔哩哔哩…」——
而那句里的东西**根本不是用户说的**（是抓取结果残留）。
根因是注入时"只要不是『用户：…』的形状就一律贴『用户曾说过』"，
**等于把「它说的／工具给的／它学到的」说成了「用户说的」**。
这个自测钉的就是这件事：**标不出"用户说的"，就不许说是用户说的。**
"""
import io
import os
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import memory_vec, retriever      # noqa: E402

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
print("【A】来源判定（只看一个字：谁说的）")
CASES = [
    ("用户：我叫张三\n小焦：好的张三，记住了。",
     ["【你说过的】我叫张三", "【小焦说过的】好的张三，记住了。"], True),
    ("小焦：我今天有点累。", ["【小焦说过的】我今天有点累。"], False),
    ("用户：我住在济南", ["【你说过的】我住在济南"], True),
    ("【http】HTTP 是一个协议，用于传输网页。", ["【它自己记下的一条】"], False),
]
for text, must_have, has_user in CASES:
    line = retriever.format_memory_line(text)
    ck("含应有标记：%s" % must_have[0], all(m in line for m in must_have), line)
    if has_user:
        ck("该是用户说的 → 有【你说过的】", "【你说过的】" in line, line)
    else:
        ck("**不该**是用户说的 → 绝不能出现【你说过的】", "【你说过的】" not in line, line)

ck("老实现的坏前缀「用户曾说过」已彻底不用",
   "用户曾说过" not in retriever.format_memory_line("【http】随便一条知识"),
   retriever.format_memory_line("【http】随便一条知识"))
ck("多行续行归当前说话人",
   retriever.format_memory_line("小焦：第一行\n第二行") == "- 【小焦说过的】第一行 第二行",
   retriever.format_memory_line("小焦：第一行\n第二行"))
ck("空正文不产生行", retriever.format_memory_line("") == "",
   retriever.format_memory_line(""))

print("\n【B】接线：走真实 `retrieve()`，注入文本里每条都带来源标记")
tmp = os.path.join(tempfile.gettempdir(), "xiaojiao_src_test.jsonl")
if os.path.exists(tmp):
    os.remove(tmp)
memory_vec._VS_PATH = tmp
memory_vec._INDEX.update({"loaded": True, "count": 0, "rows": [], "meta": [], "mat": None})
try:
    memory_vec.add_memory("用户：我最喜欢的城市是济南\n小焦：好的，济南记下了。",
                          kind="dialogue", key_text="我最喜欢的城市")
    memory_vec.add_memory("小焦：我以前说过我喜欢下雨天。",
                          kind="dialogue", key_text="我喜欢下雨天")
    memory_vec.add_memory("【知识】泉城是济南的别称。", kind="fact", key_text="济南 别称")
    res = retriever.retrieve("我最喜欢的城市是哪里", top_k=5, threshold=0.0, log=False)
    text = res["text"]
    print("    注入文本：%s" % text.replace("\n", "\n    "))
    ck("注入了至少 1 条", bool(text.strip()), text)
    lines = [ln for ln in text.split("\n") if ln.strip()]
    ck("**每一行都带来源标记**",
       all(any(m in ln for m in ("【你说过的】", "【小焦说过的】", "【它自己记下的一条】"))
           for ln in lines), text)
    ck("注入文本里没有「用户曾说过」这种旧说法", "用户曾说过" not in text, text)
    # 造一条"只有它自己说的话"的记忆，确认**不会**被贴成用户说的
    memory_vec.add_memory("小焦：我记得我说过我偏爱安静的地方。", kind="dialogue",
                          key_text="我偏爱安静的地方")
    res2 = retriever.retrieve("我偏爱安静的地方", top_k=3, threshold=0.0, log=False)
    t2 = res2["text"]
    bad = [ln for ln in t2.split("\n")
           if "记得我说过" in ln and "【你说过的】" in ln]
    ck("★ 它自己说的话，绝不会被标成「你说过的」", not bad, str(bad))
finally:
    if os.path.exists(tmp):
        os.remove(tmp)

print("\n" + "=" * 78)
print("  通过 %d / 共 %d" % (_C["pass"], _C["total"]))
if _C["failed"]:
    print("  ❌ 未通过：%s" % "、".join(_C["failed"]))
print("=" * 78)
sys.exit(0 if not _C["failed"] else 1)
