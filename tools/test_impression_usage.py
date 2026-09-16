# -*- coding: utf-8 -*-
"""那道门：印象**进到 system 里**算不算跨过去？——不算。要它**在回复里用上**才算。

所以这个测试量的是"用没用上"，不是"召没召到"：
  · 每条一句话，问一个**必须用到那条印象**的问题
  · 回复里出现"用上了"的标志词 → 记 1 分
  · 回复里出现"不认账"的说法（不记得/没说过/不知道你…）→ 直接判没过
  · **负对照**：问一句跟任何印象都无关的（1+1等于几），回复里**不该**冒出那些印象 ——
    没有这一条，"它用上了"就可能只是"它把上下文里的东西全倒出来"

数据来源：服务器自己的日志（`印象（画像系统）：命中…｜<原文>` 与 `画像召回：…｜<原文>`），
所以"是哪条印象起了作用"可以逐条对回。

运行：python tools/test_impression_usage.py     （要小焦在跑）
"""
import io
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import requests  # noqa: E402

BASE = "http://127.0.0.1:5000"
LOG = os.path.join(_ROOT, "logs", "xiaojiao.log")

# (用户这句, 用上了的标志词, 说明)
CASES = (
    ("海鲜我能吃吗", ("海鲜", "过敏", "疹"), "约束：海鲜过敏"),
    ("早上想喝点东西，推荐一下", ("乳糖", "牛奶", "咖啡"), "约束/偏好：乳糖不耐 + 黑咖啡"),
    ("推荐本书看看", ("村上",), "偏好：村上春树"),
    ("我家狗最近不爱吃饭", ("旺财", "柯基", "狗"), "背景：柯基旺财"),
    ("晚上想点外卖，帮我推荐两个菜", ("花生", "过敏"), "约束：花生过敏"),
)

# 负对照：跟印象无关的一句话。它**不该**把印象硬倒出来。
CONTROL_Q = "1+1等于几"
CONTROL_FORBID = ("失恋", "花生", "旺财", "村上", "乳糖", "柯基", "游泳", "吉他")

# 不认账的说法：出现即判没过（规格里"回复必须认账"那条的同一把尺）
DENY = ("不记得", "没提过", "没说过", "没有印象", "不知道你", "没告诉过我",
        "不掌握", "没有记录", "无法得知你的", "不清楚你", "你不曾")


def tail_mark():
    try:
        return os.path.getsize(LOG)
    except Exception:      # noqa: silent-ok — 日志不在就从 0 开始
        return 0


def read_since(mark):
    try:
        with io.open(LOG, "r", encoding="utf-8", errors="replace") as f:
            f.seek(mark)
            return f.read()
    except Exception:      # noqa: silent-ok — 读不到就当空，断言会如实报缺
        return ""


def ask(q, timeout=300):
    r = requests.post(BASE + "/api/chat", json={"message": q}, timeout=timeout)
    return str((r.json() or {}).get("answer") or "")


def injected(got):
    """这一轮注进 system 的印象（两条链各自的日志行）。"""
    out = []
    for ln in got.split("\n"):
        if "（画像系统）：命中" in ln or "画像召回：命中" in ln:
            out.append(ln.split("｜")[-1].strip() if "｜" in ln else ln.split("] ")[-1])
    return out


def main():
    ok = 0
    print("=" * 78)
    print("门 · 印象用量测试（看的是回复里有没有用上，不是召没召到）")
    print("=" * 78)
    for i, (q, marks, why) in enumerate(CASES, 1):
        mark = tail_mark()
        t0 = time.time()
        try:
            reply = ask(q)
        except Exception as e:      # noqa: silent-ok — 连不上就如实报，不假装成功
            print("\n【%d】%s → ❌ 请求失败：%s" % (i, q, e))
            continue
        dt = time.time() - t0
        got = read_since(mark)
        inj = injected(got)
        deny = [d for d in DENY if d in reply]
        used = [m for m in marks if m in reply]
        hit = bool(used) and not deny
        ok += 1 if hit else 0
        print("\n【%d】%s    （%s）" % (i, q, why))
        print("  注入的印象：%s" % (inj or "（没有注入日志 ← 没接上）"))
        print("  回复：%s" % reply.replace("\n", " ")[:170])
        print("  标志词命中：%s%s" % (used or "无", ("｜不认账：%s" % deny) if deny else ""))
        print("  判定：%s（%.1fs）" % ("用上了 ✅" if hit else "**没用上** ❌", dt))

    print("\n" + "-" * 78)
    print("负对照：%s（跟任何印象都无关，回复里不该冒出那些印象）" % CONTROL_Q)
    mark = tail_mark()
    try:
        reply = ask(CONTROL_Q)
        got = read_since(mark)
        bad = [k for k in CONTROL_FORBID if k in reply]
        print("  回复：%s" % reply.replace("\n", " ")[:150])
        print("  冒出来的无关印象：%s" % (bad or "无"))
        print("  判定：%s" % ("干净 ✅（没有硬塞印象）" if not bad else "**硬塞了印象** ❌"))
        if not bad:
            ok += 1
    except Exception as e:      # noqa: silent-ok — 失败如实报
        print("  ❌ 请求失败：%s" % e)

    total = len(CASES) + 1
    print("\n" + "=" * 78)
    print("印象用量：%d/%d" % (ok, total))
    print("=" * 78)
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
