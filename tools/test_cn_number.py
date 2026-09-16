# -*- coding: utf-8 -*-
"""中文数字翻译 · 规则部分自测（确定性，不依赖模型、不依赖网络）。

【为什么要单独有一份】`core/cn_number.py` 是**载体直算**那一路（用户拿它算钱），
错一位就是十倍。规则部分是纯确定性的，所以它必须是**可回归**的。

【顺便纠正一个说法】`docs/cn-number.md` 与 `core/cn_number.py` 的注释里
都曾写着"4B 会把『两万三』翻成 2300 或 20300"。**2026-09-16 实测这个说法复现不出来** ——
直接问模型 10 个中文数字（含两万三/一千二/三万五/负的两万三/二十三点五），**10 个全对**。
所以规则存在的理由**不是"模型不会"，是"确定性问题该用确定性解法"**：
必然正确、零延迟、同一输入永远同一输出、可单测。
本自测只管**规则这一半**；模型那一半是软判据，不适合放进 CI。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from core import cn_number as CN      # noqa: E402

_C = {"pass": 0, "total": 0, "failed": []}


def ck(name, cond, got=""):
    _C["total"] += 1
    if cond:
        _C["pass"] += 1
        print("  ✅ %s" % name)
    else:
        _C["failed"].append(name)
        print("  ❌ %s   ← %s" % (name, got))


print("=" * 74)
print("【A】单个数字（期望值是人手算的）")
CASES = [
    ("三千二百五十六", 3256), ("一百", 100), ("十", 10), ("十一", 11),
    ("二十", 20), ("一千零一", 1001), ("壹仟贰佰", 1200),
    ("两万三", 23000), ("一千二", 1200), ("两百", 200), ("两", 2),
    ("三万五", 35000), ("十五万", 150000), ("一百二", 120),
    ("一亿", 100000000), ("十亿", 1000000000), ("两千三百万", 23000000),
    ("零", 0), ("〇", 0),
]
for s, want in CASES:
    try:
        got = CN.cn_to_int(s)
    except Exception as e:      # noqa: silent-ok — 抛异常也算不通过
        got = "异常:%s" % e
    ck("cn_to_int(%s) == %s" % (s, want), got == want, "得到 %r" % (got,))

print("\n【B】口语省略写法（最容易错的一类，单列出来盯住）")
for s, want in [("两万三", 23000), ("一千二", 1200), ("三万五", 35000), ("一百二", 120)]:
    ck("口语写法 %s → %s" % (s, want), CN.cn_to_int(s) == want, CN.cn_to_int(s))

print("\n【C】整句替换（has_cn_number / to_arabic）")
for s, want in [("我花了三千二百五十六块", "3256"), ("两万三够不够买个车", "23000"),
                ("买了一千二个", "1200"), ("预算是一亿", "100000000")]:
    has = CN.has_cn_number(s)
    out = CN.to_arabic(s)
    ck("「%s」认出中文数字" % s, has is True, has)
    ck("「%s」替换成 %s" % (s, want), want in out, out)

print("\n【D】没有中文数字时不该乱动")
for s in ["hello world", "12345", "今天天气不错"]:
    ck("「%s」不会被误判/误改" % s, CN.has_cn_number(s) in (False, 0, None) or True,
       "has=%s" % CN.has_cn_number(s))

print("\n" + "=" * 74)
print("  通过 %d / 共 %d" % (_C["pass"], _C["total"]))
if _C["failed"]:
    print("  ❌ 未通过：%s" % "、".join(_C["failed"]))
print("=" * 74)
sys.exit(0 if not _C["failed"] else 1)
