# -*- coding: utf-8 -*-
"""「写文件撞上已存在的文件」这条路自测（离线）：**拦截要给得出路，且原文件一个字不动**。

【实测现场（2026-09-21，用户截图）】用户让它写段代码看：
  · 模型 `write_file` → 目标 `C:/Users/Jiao/Desktop/a.txt` 已存在 → 删除禁区拦下；
  · `_carrier_block()` 把载体原文**直接当回答** → 用户再问一次「写一段代码我看看」；
  · 模型（上下文里还是那个计划）**又调同一个 write_file** → 又是一模一样的一段话。
  连着三轮：**一句代码都没拿到**，界面反复刷同一段拦截。
  根因：拦截提示里那句「换成新建（换个文件名）或追加（mode='a'）」
  **对模型是空话** —— `write_file` 根本没有 mode 参数，它照着做不了，只能重试原动作。

这里钉四件事：
  ① 撞上已存在文件时，载体**换一个没被占用的名字**把内容写进去，并如实说清"原文件没动、新文件在哪"；
  ② **原文件逐字节不变**（红线不许破），而且第二次、第三次会接着换 `_3`、`_4`；
  ③ 只在"覆盖已有文件"这一种拦截上动手 —— 别的拦截（比如删除）一个字都不碰；
  ④ 「写一段代码我看看」要的是**当场看见**那段代码，不是建文件（这条判对了，模型就不会去写文件）。
"""
import io
import os
import shutil
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import xiaojiao_app as A  # noqa: E402

PASS, FAIL = [], []


def ck(name, cond, info=""):
    (PASS if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("  ← " + str(info)[:170]) if info else ""))


def main():
    tmp = tempfile.mkdtemp(prefix="xj_altwrite_")
    target = os.path.join(tmp, "a.txt")
    io.open(target, "w", encoding="utf-8").write("旧内容：不许被改")
    before = io.open(target, "rb").read()
    try:
        print("一、写文件撞上已存在的文件 → 载体换名写，并说清")
        deny = ("⚠️ 删除操作被载体层拦截（安全红线）。文件未被删除。\n"
                "🚫 这条操作被载体的「删除禁区」拦下了：覆盖已经存在的文件「%s」。" % target)
        out = A._alt_write_on_overwrite("write_file",
                                       {"path": target, "content": "print(1)  # 新代码"},
                                       deny)
        ck("换名写成了一条出路（不是那句空话）", bool(out) and "删除禁区" in out and "新文件" in out, out[:60])
        alt = os.path.join(tmp, "a_2.txt")
        ck("新文件真的写进去了", os.path.exists(alt) and "print(1)" in io.open(alt, encoding="utf-8").read())
        ck("说明里写明了原文件没动 + 新文件在哪",
           (target.replace("\\", "/") in out) and ("a_2.txt" in out), out[:200])
        ck("**原文件逐字节不变**", io.open(target, "rb").read() == before)
        ck("这段文字会被 `_carrier_block()` 认成「载体的决定」（原样交给用户，不让模型转述）",
           A._carrier_block(out))

        print("\n二、再撞一次就接着换名字（不会覆盖上一次的）")
        out2 = A._alt_write_on_overwrite("write_file", {"path": target, "content": "第二段"},
                                         deny)
        ck("第二次 → a_3.txt", os.path.exists(os.path.join(tmp, "a_3.txt")), out2[:80])
        ck("第一次那个 a_2.txt 没被覆盖",
           "print(1)" in io.open(alt, encoding="utf-8").read())

        print("\n三、只认「覆盖已有文件」这一种拦截；别的拦截一个字都不碰")
        ck("删除类的拦截 → 不换名（返回空，走原来的拒绝）",
           A._alt_write_on_overwrite("write_file", {"path": target, "content": "x"},
                                     "🚫 …删除「%s」" % target) == "")
        ck("别的工具 → 不管",
           A._alt_write_on_overwrite("edit_file", {"path": target, "content": "x"}, deny) == "")
        ck("没内容 → 不写（不做无意义的建空文件）",
           A._alt_write_on_overwrite("write_file", {"path": target, "content": ""}, deny) == "")

        print("\n四、「写一段代码我看看」= 要内容（当场说），不是要文件")
        cases = [("写一段代码我看看", True), ("写段代码给我看看", True),
                 ("写一个 Python 函数我看看", True), ("写一段自我介绍", True),
                 ("把这段代码保存到 C:/Users/x/Desktop/b.py", False),
                 ("写个脚本存成 demo.py", False), ("帮我写个文件", False),
                 ("今天天气怎么样", None)]
        for text, want in cases:
            got = A._wants_content_not_file(text)
            ck("「%s」→ %s" % (text, {True: "要内容", False: "要文件", None: "判不出来"}[want]),
               got is want, got)

        print("\n五、红线本身没松：`check_file_op` 照样拒绝覆盖")
        sys.path.insert(0, _ROOT)
        from core.security import no_delete as ND
        r = ND.check_file_op("write", target, "新内容")
        ck("覆盖已存在文件 → 仍然拦", bool(r), r[:80])
        ck("提示改成了**做得到**的建议（不再提 mode='a'）",
           ("换个文件名" in r or "edit_file" in r) and "mode='a'" not in r, r[:120])
        ck("删除仍然一律拒绝", bool(ND.check_file_op("delete", target)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    print("写文件撞车自测：通过 %d / 共 %d%s"
          % (len(PASS), len(PASS) + len(FAIL), ("　失败：" + str(FAIL)) if FAIL else ""))
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
