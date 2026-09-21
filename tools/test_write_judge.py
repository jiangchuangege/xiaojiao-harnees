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
       ("不要建文件" in src or "这一轮不写文件" in src)
       and ("当场把内容说出来" in src or "当场看见内容" in src or "原样输出" in src), "")
    # 【这条是拿惨痛教训换来的，必须钉死】载体自己的拦截文字**必须带 CARRIER_MARKS 里的标记**，
    #   否则健康系统会把它当成 `tool_misuse`（模型乱调工具）→ 连中两轮 → 诊断 HEAVY →
    #   **三级治疗把大脑切到备用火种** → 去慢盘重载 4GB → 用户看到"正在组织回答…十分钟不动"
    #   （2026-09-21 实测，就是这一条没做才出的）。
    ck("拦截文字带载体标记（否则会被健康系统误判成模型乱调 → 换火种 → 卡死）",
       "【载体动作】" in src or "已被载体层拦截" in src or "删除禁区" in src, "")
    # 【2026-09-21 再加一条，是用户骂回来的那次】这一拦**不许给用户看告警横幅**：
    #   用户要的是"写段代码给我看看"，不是「⚠️ 删除操作被载体层拦截（安全红线）」——
    #   载体只是顺手没让它写文件，那就把内容端出来，别拿告警吓人。
    _shown = app._carrier_block_answer("content", "【载体动作】这一轮不写文件\nprint('hi')")
    ck("「要内容」这一类**不带 ⚠️ 告警横幅**", "⚠️" not in _shown, _shown[:60])
    ck("但内容原样端出来给用户", "print('hi')" in _shown, _shown[:80])
    ck("机器标记对用户不可见", "【载体动作】" not in _shown, _shown[:60])
    ck("删除那一类**仍然**保留用户点名要的那句横幅",
       app._carrier_block_answer("delete", "🚫 …删除禁区…").startswith(
           "⚠️ 删除操作被载体层拦截（安全红线）。文件未被删除。"), "")
    from core.health.monitor import is_carrier_action
    ck("带机器标记的结果仍被健康系统认成载体动作（不然会去换火种）",
       is_carrier_action("【载体动作】这一轮不写文件\nprint(1)"), "")
    # 【2026-09-21 改：从"只能有一处调用"改成"**只有这两处**调用"】
    #   原来写的是 `count(...) == 2`（一处定义 + 一处在 run_tool）——用意是**不许把这个判据
    #   顺手套到别的链路（尤其代码治病链）上去**。但用户实测后提了一个更硬的要求，他的原话：
    #     「**我没让他写进文件，我让他写代码给我看，而不是调用工具写到文件里！！**」
    #   —— 光在 `run_tool` 拦不够：拦得住"真写"，拦不住"它去调"，界面上照样冒出一次工具调用。
    #   所以新增了一处**前置**：判为"要内容"时，**这一轮的工具表里就没有 write_file**
    #   （`「写」闸·前置`，与"渠道隔离"同一条思路）。两处调的是**同一个判据函数**，不是两套逻辑。
    #   这条现在守的是：**只有这两处**用它（工具表前置 + 工具唯一入口），别处一个都不许用。
    _calls = src.count("_wants_content_not_file(")
    ck("判据只有一个定义", src.count("def _wants_content_not_file(") == 1, _calls)
    ck("**只有两处用它**（工具表前置 + run_tool），别处一处都不许用", _calls == 3, _calls)
    ck("两处都在（前置拿掉工具表 / 入口拦真写）",
       "「写」闸·前置" in src and "「写」闸：判为**要内容**" in src)
    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d" % (_COUNT["pass"], _COUNT["total"]))
    if _FAILED:
        print("  ❌ 未通过：%s" % "、".join(_FAILED))
    print("=" * 78)
    sys.exit(0 if not _FAILED else 1)


if __name__ == "__main__":
    main()
