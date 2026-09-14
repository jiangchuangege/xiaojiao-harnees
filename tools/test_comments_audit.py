# -*- coding: utf-8 -*-
"""阶段 D · 重点函数注释审计（"为什么这么设计？去掉会怎样？"覆盖验收）

提示词要求：**10 处重点函数**逐个补注释，每个注释必须回答两个问题：
    ① 这段代码为什么这么设计？ ② 去掉它会怎样？

为什么要做成可跑的审计而不是人工看一眼：
    "注释齐全"这种事最容易在后续改动里悄悄退化（有人删了注释、或新加的函数没写）。
    做成断言之后，每次跑测试都会检查一遍 —— 缺了就是红的。

本审计**只读**（不改代码）：读源码里的 docstring / 紧邻注释，按关键词判定。
"""
import inspect
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as app  # noqa: E402
from core import continuation as C  # noqa: E402
from core import retriever as R  # noqa: E402
from core import memory_vec as MV  # noqa: E402
from core import input_splitter as IS  # noqa: E402
from core import memory_deep as MD  # noqa: E402
from core import persona as P  # noqa: E402
from core import central as CE  # noqa: E402
from core import preinstall as PI  # noqa: E402
from core.security import no_delete as ND  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)) if info else ""))


# 提示词列的 10 处重点函数 → 实际落点（模块/函数名）
TARGETS = (
    ("1. compose_system_prompt（按意图装配，不做全量）", app.compose_system_prompt),
    ("2. _detect_intent（规则路由，不靠模型判断）", app._detect_intent),
    ("3. _fit_context（单次不超，靠装配不靠砍）", app._fit_context),
    ("4. core/continuation.py（多次请求+无缝拼接）", C.generate_unlimited),
    ("5. core/retriever.py（记忆外部化）", R.retrieve),
    ("6. core/memory_vec.py（对话记忆独立于训练数据）", MV.add_memory),
    ("7. agent_run（载体编排，模型只执行单步）", app.agent_run),
    ("8. 工具调度（意图强制，不靠模型自觉）", app._plan_tools),
    # 这一处用 `check_command`（命令入口守卫）：它是"给用户看的拒绝提示"的出口，
    # 也正是删除红线**对用户说话**的地方；`is_delete_command` 只是它下面的判据函数。
    ("9. 文件操作（删除红线：载体层硬约束）", getattr(ND, "check_command", None)
     or getattr(ND, "is_delete_command", None)),
    ("10. 健康/自主/世界/变形金刚/元认知/人格层各自设计意图", None),
)


def _has_two_questions(text):
    """docstring 或紧邻注释里是否**同时**回答了两个问题。"""
    t = text or ""
    why = ("为什么" in t) or ("设计" in t)
    gone = ("去掉" in t) or ("不写" in t) or ("没有它" in t) or ("否则" in t)
    return why and gone


def main():
    print("=" * 78)
    print("  阶段 D · 重点函数注释审计（为什么这么设计？去掉会怎样？）")
    print("=" * 78)

    print("\n[一] 提示词列的 10 处重点函数逐条核对")
    resolved = 0
    for label, fn in TARGETS:
        if fn is None:
            continue
        resolved += 1
        try:
            doc = inspect.getdoc(fn) or ""
        except Exception as e:      # noqa: silent-ok — 取不到 docstring 就按"没有"算并如实报告
            doc = ""
            ck(label, False, "%s" % e)
            continue
        ck(label, _has_two_questions(doc),
           "%d 字" % len(doc) if doc else "**没有 docstring**")
    ck("10 处都能定位到真实函数（没有指向空气）", resolved >= 9, resolved)

    print("\n[二] 第 10 处：六个新增子系统**各自**有设计意图说明")
    subs = (("健康系统", None, "core/health/monitor.py"),
            ("自主性", None, "core/autonomy/scheduler.py"),
            ("世界层", None, "core/world/perception.py"),
            ("变形金刚", None, "core/carrier/brain_registry.py"),
            ("元认知", None, "core/metacognition/selfrate.py"),
            ("人格层", None, "core/persona/__init__.py"))
    for name, _, rel in subs:
        p = os.path.join(_ROOT, rel)
        if not os.path.exists(p):
            ck("%s 的模块存在（%s）" % (name, rel), False, "文件不存在")
            continue
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(7000)
        ck("%s 有设计意图说明（为什么/去掉）" % name, _has_two_questions(head),
           rel)

    print("\n[三] 总纲注释：每个核心模块顶部都有四行总纲")
    MOTTO = "小焦系统本身不依赖任何具体模型"
    for rel in ("core/memory_deep.py", "core/persona/__init__.py",
                "core/central/__init__.py", "core/preinstall/__init__.py",
                "core/boost/__init__.py", "core/metacognition/__init__.py",
                "core/continuation.py", "core/retriever.py", "core/memory_vec.py",
                "core/input_splitter.py"):
        p = os.path.join(_ROOT, rel)
        if not os.path.exists(p):
            ck("总纲：%s 存在" % rel, False, "文件不存在")
            continue
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(600)
        ck("总纲：%s" % rel, MOTTO in head, "")

    print("\n[四] 新增模块的设计意图（本轮六个子系统 + 两个阶段层）")
    for label, fn in (("记忆深度 classify（分类为什么靠载体）", MD.classify),
                      ("绝假记忆 recall（为什么不能说没有的）", MD.recall),
                      ("人格层 strip_flavor（为什么做硬后处理）", P.strip_flavor),
                      ("人格层 pick_form（为什么用户要什么给什么）", P.pick_form),
                      ("协同网络 publish（为什么吞异常又记账）", CE.publish),
                      ("协同网络 snapshot（为什么不许编造模块状态）", CE.snapshot),
                      ("预置数据 verify（为什么要能说缺）", PI.verify),
                      ("输入切片 split_input（为什么不切在句中）", IS.split_input)):
        doc = inspect.getdoc(fn) or ""
        ck(label, _has_two_questions(doc), "%d 字" % len(doc))

    print("\n" + "=" * 78)
    print("  通过 %d / 共 %d%s" % (len(PASS), len(PASS) + len(FAIL),
                                  ("（失败：%s）" % "、".join(FAIL)) if FAIL else ""))
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
