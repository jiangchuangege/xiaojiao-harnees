# -*- coding: utf-8 -*-
"""代码治病判据自测（**创作类不许进治病链**）

用法：python tools/test_code_judge.py

【为什么要单独钉住这一条】用户实测：说「写个童话故事吧」，结果走了代码治病链 ——
把故事包进 `def tell_a_fairy_tale() -> str: ... return story` 真跑一遍，回"已跑通并验证"。
根因：`_CODE_WRITE` 里有「写个/写一个/写一段」，这三个在中文里太常见。
这个自测同时钉两头：**创作类不许进**、**真代码请求不许被误伤**。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xiaojiao_app as app           # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
# (问法, 期望走代码治病吗)
CASES = [
    ("写个童话故事吧", False),
    ("写一个童话", False),
    ("写篇小说", False),
    ("写篇关于猫的文章", False),
    ("写一段自我介绍", False),
    ("写首诗", False),
    ("写首歌词", False),
    ("写个笑话", False),
    ("写个段子", False),
    ("写份文案", False),
    ("写个剧本", False),
    ("写封情书", False),
    ("帮我写个对联", False),
    # ---- 真代码请求：一个都不许被误伤 ----
    ("写个函数计算斐波那契", True),
    ("帮我写个脚本", True),
    ("写一个 Python 函数把列表去重", True),
    ("帮我写个去重函数", True),
    ("写个能跑的", True),
    ("写个试试", True),
    ("帮我写一个爬虫", True),
    ("编写一个类", True),
    ("生成代码", True),
    # ---- 评审类：本来就不该进 ----
    ("帮我看看这段代码为什么慢", False),
]


def ck(name, cond, extra=""):
    _COUNT["total"] += 1
    if cond:
        _COUNT["pass"] += 1
        print("  [OK]   %s%s" % (name, ("  | " + str(extra)) if extra else ""))
    else:
        _FAILED.append(name)
        print("  [FAIL] %s  | %s" % (name, extra))


def main():
    print("=" * 78)
    print("  代码治病判据自测")
    print("=" * 78)
    bad = []
    for q, want in CASES:
        got = app._code_request_question(q)
        ok = (got == want)
        if not ok:
            bad.append(q)
        print("  %s %-30s → %s（期望 %s）"
              % ("[OK]  " if ok else "[FAIL]", q,
                 "走代码治病" if got else "不走", "走" if want else "不走"))
        _COUNT["total"] += 1
        if ok:
            _COUNT["pass"] += 1
        else:
            _FAILED.append(q)
    print("\n  创作类排除词表：%d 个｜正例词表未删（%d 个）"
          % (len(app._CODE_NOT_WRITE_CREATIVE), len(app._CODE_WRITE)))
    ck("正例词一个都没删（只加排除，不改正例）", len(app._CODE_WRITE) >= 18, len(app._CODE_WRITE))
    ck("真代码请求没有被误伤", not [q for q, w in CASES if w and not app._code_request_question(q)],
       [q for q, w in CASES if w and not app._code_request_question(q)])
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
