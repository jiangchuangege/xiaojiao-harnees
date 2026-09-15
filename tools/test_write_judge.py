# -*- coding: utf-8 -*-
"""「写」别乱动手 自测（要内容 vs 要文件）

用法：python tools/test_write_judge.py

【实测来源】用户说「写一段自我介绍」→ 判据**正确地**没让它进代码治病链，
但**模型自己去建了个 `self_intro.txt`**。用户要的是"当场说一段"，它却动手建了文件。
根因：「写」在中文里太常见（写代码/写文件/写故事/写诗/写自我介绍…），
模型只学会"写 = 动手"，不知道"写 = 当场说"。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import xiaojiao_app as app           # noqa: E402

_COUNT = {"pass": 0, "total": 0}
_FAILED = []
CASES = [
    # (输入, 期望)  True=要内容（拦 write_file）/ False=要文件（放行）/ None=判不出（不拦）
    ("写一段自我介绍", True),
    ("写首诗", True),
    ("写篇日记", True),
    ("写个笑话", True),
    ("写个段子", True),
    ("写篇小说", True),
    ("写首歌词", True),
    ("帮我把这段自我介绍写到 C:\\a.txt", False),
    ("生成一个自我介绍.txt", False),
    ("导出成 markdown 保存到桌面", False),
    ("把这首诗存下来", False),
    ("帮我保存到桌面", False),
    ("写个 Python 脚本", None),        # 真代码请求：不受影响（判不出 → 不拦）
    ("帮我写个去重函数", None),
    ("你好", None),
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
    print("  「写」别乱动手 自测")
    print("=" * 78)
    lab = {True: "要内容(拦)", False: "要文件(放行)", None: "判不出(不拦)"}
    for q, want in CASES:
        got = app._wants_content_not_file(q)
        ck("%-30s → %s" % (q, lab[got]), got == want, "期望 %s" % lab[want])
    print("\n[A] 判据的形状")
    ck("**判不出来一律不拦**（保守：宁可多建一次，也不误拦真文件请求）",
       app._wants_content_not_file("随便说点什么") is None, "")
    ck("明确路径 → 要文件", app._wants_content_not_file("写到 C:\\x\\y.md") is False, "")
    ck("明确扩展名 → 要文件", app._wants_content_not_file("生成 score.json") is False, "")
    ck("「存下来」算要文件（规格点名的边界情形）",
       app._wants_content_not_file("把这首诗存下来") is False, "")
    print("\n[B] 闸加在哪、拦什么")
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "xiaojiao_app.py"), encoding="utf-8").read()
    ck("加在 `run_tool`（工具唯一入口，与删除红线/去重同层）",
       "「写」别乱动手" in src and "_wants_content_not_file" in src, "")
    ck("只拦写文件的工具（write_file / append_file / save_to）",
       'name in ("write_file", "append_file", "save_to")' in src, "")
    ck("拦下来时**告诉它怎么办**（当场说），不是硬报错",
       "不要建文件" in src and "当场把内容说出来" in src, "")
    ck("**不动代码治病链**（判据只在这一处用）", src.count("_wants_content_not_file(") == 2,
       src.count("_wants_content_not_file("))
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
